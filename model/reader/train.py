"""Fine-tune a small cross-encoder with two heads (about_this, offers) on the weak labels.

Normally called by model/reader/run.py with a config. Stand-alone:

    .venv/bin/python -m model.reader.train --backbone microsoft/MiniLM-L12-H384-uncased --name minilm

Loss: binary cross-entropy per head with label smoothing (targets eps and 1 - eps), masked where a
head has no label, weighted by the example weight. Weak labels are noisy, so smoothing keeps the
model from being pushed to certainty by them.
Selection: the epoch with the lowest validation loss on the facility-grouped validation split is
kept. The hand-labelled eval set is never used for training or selection.
After training, one temperature per head is fitted on the validation split (weak labels).

Checkpoints: every `checkpoint_every` steps and at each epoch end the model, optimiser, scheduler
and position are saved to weights/<name>/checkpoint.pt. Starting again with the same name resumes
from it (the shuffle of each epoch is derived from the seed and the epoch number, so the resumed
run sees the same batches). A finished run is not repeated unless force=True.

Writes model/reader/weights/<name>/{model.pt, config.json, log.json} (git-ignored).
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import torch  # noqa: E402
from sklearn.metrics import average_precision_score, roc_auc_score  # noqa: E402
from transformers import AutoTokenizer, get_linear_schedule_with_warmup  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import HERE, MAX_LEN, build_model, pick_device  # noqa: E402

DEFAULTS = {"epochs": 2, "bs": 64, "lr": 3e-5, "eps": 0.05, "max_len": MAX_LEN, "seed": 7, "limit": 0,
            "checkpoint_every": 500, "eval_bs": 256, "log_every": 100,
            # memory guard: a chunk sent to the device holds at most max_cells = rows x padded_length^2
            # (attention memory grows with the square of the length). 64 x 160^2 is what a 16 GB
            # Apple M5 trains without swapping; raise it on a larger machine.
            "max_cells": 64 * 160 * 160}


def epoch_batches(lengths, bs, seed, epoch, pool=50):
    """Batches for one epoch, the same for a given (seed, epoch) so a resumed run sees them again.
    Examples are shuffled, cut into pools of `pool` batches, sorted by length inside a pool and cut
    into batches, and the batches are shuffled. Sentences of similar length share a batch, which
    cuts padding (less memory, faster) while keeping the order random."""
    rng = np.random.default_rng([seed, epoch])
    perm = rng.permutation(len(lengths))
    out = []
    for i in range(0, len(perm), bs * pool):
        chunk = perm[i:i + bs * pool]
        chunk = chunk[np.argsort(lengths[chunk], kind="stable")]
        out += [chunk[j:j + bs] for j in range(0, len(chunk), bs)]
    return [out[k] for k in rng.permutation(len(out))]


def is_oom(err):
    msg = str(err).lower()
    return isinstance(err, torch.OutOfMemoryError) or "out of memory" in msg or "insufficient memory" in msg


def free_memory():
    if torch.backends.mps.is_available():
        torch.mps.empty_cache()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def encode(tok, part, max_len):
    """Tokenise a batch on the CPU. Returns (encoding, labels, weights, padded length)."""
    enc = tok(part.a.tolist(), part.b.tolist(), truncation="only_second", max_length=max_len, padding=True, return_tensors="pt")
    y = torch.tensor(part[["y_about", "y_offers"]].values, dtype=torch.float32)
    w = torch.tensor(part.w.values, dtype=torch.float32)
    return enc, y, w, int(enc["input_ids"].shape[1])


def chunks(enc, y, w, size, device):
    """Slices of a tokenised batch, moved to the device."""
    for j in range(0, len(y), size):
        yield {k: v[j:j + size].to(device) for k, v in enc.items()}, y[j:j + size].to(device), w[j:j + size].to(device)


def chunk_size(limit, length, max_cells):
    return max(1, min(limit, max_cells // (length * length)))


def loss_fn(logits, y, w, eps):
    mask = (y >= 0).float()
    target = y.clamp(min=0) * (1 - 2 * eps) + eps
    per = torch.nn.functional.binary_cross_entropy_with_logits(logits, target, reduction="none") * mask * w.unsqueeze(1)
    return per.sum() / mask.sum().clamp(min=1)


def run_eval(model, tok, df, device, bs, eps, max_len, max_cells=DEFAULTS["max_cells"]):
    model.eval()
    order = np.argsort(df.b.str.len().values, kind="stable")
    tot, n, logits_all, ys = 0.0, 0, [], []
    i = 0
    with torch.no_grad():
        while i < len(order):
            part = df.iloc[order[i:i + bs]]
            enc, y, w, length = encode(tok, part, max_len)
            try:
                # no gradients are kept in evaluation, so four times the training budget fits
                lg = torch.cat([model(**e) for e, _, _ in chunks(enc, y, w, chunk_size(bs, length, 4 * max_cells), device)])
                y, w = y.to(device), w.to(device)
                batch_loss = float(loss_fn(lg, y, w, eps))
            except RuntimeError as err:          # out of memory: halve the batch and try again
                if not is_oom(err) or bs == 1:
                    raise
                bs = max(1, bs // 2)
                free_memory()
                print(f"out of memory in evaluation, batch size now {bs}", flush=True)
                continue
            tot += batch_loss * len(part)
            n += len(part)
            logits_all.append(lg.float().cpu().numpy())
            ys.append(y.cpu().numpy())
            i += len(part)
    lg, y = np.concatenate(logits_all), np.concatenate(ys)
    out = {"loss": tot / n}
    for j, head in enumerate(("about", "offers")):
        m = y[:, j] >= 0
        if m.sum() and len(set(y[m, j])) == 2:
            out[f"{head}_auroc"] = float(roc_auc_score(y[m, j], lg[m, j]))
            out[f"{head}_ap"] = float(average_precision_score(y[m, j], lg[m, j]))
        out[f"{head}_acc"] = float(((lg[m, j] > 0) == (y[m, j] > 0.5)).mean()) if m.sum() else None
    return out, lg, y


def fit_temperature(lg, y):
    """One temperature per head minimising validation log loss (grid search)."""
    temps = []
    for j in range(2):
        m = y[:, j] >= 0
        grid = np.exp(np.linspace(np.log(0.5), np.log(5.0), 60))
        nll = [np.mean(np.logaddexp(0, lg[m, j] / t) - y[m, j] * lg[m, j] / t) for t in grid]
        temps.append(float(grid[int(np.argmin(nll))]))
    return temps


def train_one(name, backbone, force=False, **overrides):
    """Train (or resume) one backbone. Returns the saved config dict."""
    a = {**DEFAULTS, **{k: v for k, v in overrides.items() if v is not None}}
    out = HERE / "weights" / name
    out.mkdir(parents=True, exist_ok=True)
    if (out / "config.json").exists() and (out / "model.pt").exists() and not force:
        print(f"[{name}] already trained, skipping (force=True to retrain)", flush=True)
        return json.loads((out / "config.json").read_text())
    torch.manual_seed(a["seed"])
    device = pick_device()
    d = pd.read_parquet(HERE / "data" / "train.parquet")
    tr, va = d[d.split == "train"].reset_index(drop=True), d[d.split == "val"].reset_index(drop=True)
    if a["limit"]:
        tr, va = tr.iloc[:a["limit"]], va.iloc[:max(500, a["limit"] // 8)]
    tok = AutoTokenizer.from_pretrained(backbone)
    model = build_model(backbone).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    opt = torch.optim.AdamW(model.parameters(), lr=a["lr"], weight_decay=0.01)
    per_epoch = (len(tr) + a["bs"] - 1) // a["bs"]
    steps = a["epochs"] * per_epoch
    sched = get_linear_schedule_with_warmup(opt, int(0.06 * steps), steps)
    log = {"name": name, "backbone": backbone, "device": str(device), "params": n_params, "train_examples": len(tr),
           "val_examples": len(va), "args": a, "epochs": [], "resumed_from_step": []}
    state = {"epoch": 0, "step_in_epoch": 0, "step": 0, "best": None, "temps": [1.0, 1.0], "seconds": 0.0, "run": 0.0,
             "micro_bs": a["bs"]}
    lengths = tr.b.str.len().values
    ck = out / "checkpoint.pt"
    if ck.exists() and not force:
        c = torch.load(ck, map_location="cpu", weights_only=False)
        if c["signature"] == [backbone, len(tr), a["bs"], a["epochs"], a["seed"], a["max_len"]]:
            model.load_state_dict(c["model"])
            opt.load_state_dict(c["opt"])
            sched.load_state_dict(c["sched"])
            state, log = c["state"], c["log"]
            log["resumed_from_step"].append(state["step"])
            print(f"[{name}] resuming at epoch {state['epoch']} step {state['step']}/{steps}", flush=True)
        else:
            print(f"[{name}] checkpoint is from different settings, starting fresh", flush=True)

    def save_checkpoint():
        tmp = out / "checkpoint.tmp"
        torch.save({"model": model.state_dict(), "opt": opt.state_dict(), "sched": sched.state_dict(), "state": state, "log": log,
                    "signature": [backbone, len(tr), a["bs"], a["epochs"], a["seed"], a["max_len"]]}, tmp)
        tmp.replace(ck)

    t0 = time.time() - state["seconds"]
    while state["epoch"] < a["epochs"]:
        ep = state["epoch"]
        batches = epoch_batches(lengths, a["bs"], a["seed"], ep)
        model.train()
        for b in range(state["step_in_epoch"], per_epoch):
            part = tr.iloc[batches[b]]
            n_lab = max(int((part[["y_about", "y_offers"]].values >= 0).sum()), 1)
            while True:
                # the batch is sent to the device in chunks and the gradients are added up, so the
                # update is that of the whole batch. Chunk size is set by the memory guard
                # (max_cells) and halved again if the device still reports out of memory.
                try:
                    opt.zero_grad()
                    lv = 0.0
                    enc_all, y_all, w_all, length = encode(tok, part, a["max_len"])
                    size = chunk_size(state["micro_bs"], length, a["max_cells"])
                    for enc, y, w in chunks(enc_all, y_all, w_all, size, device):
                        share = float((y >= 0).sum()) / n_lab
                        loss = loss_fn(model(**enc), y, w, a["eps"]) * share
                        loss.backward()
                        lv += float(loss.detach())
                    break
                except RuntimeError as err:
                    if not is_oom(err) or state["micro_bs"] == 1:
                        raise
                    state["micro_bs"] = max(1, state["micro_bs"] // 2)
                    free_memory()
                    print(f"[{name}] out of memory, processing batches in chunks of {state['micro_bs']}", flush=True)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            state["step"] += 1
            state["step_in_epoch"] = b + 1
            state["run"] = 0.98 * state["run"] + 0.02 * lv if state["step"] > 1 else lv
            state["seconds"] = time.time() - t0
            if state["step"] % a["log_every"] == 0:
                rate = state["step"] * a["bs"] / max(state["seconds"], 1e-9)
                print(f"[{name}] ep {ep} step {state['step']}/{steps} loss {state['run']:.4f} {state['seconds']:.0f}s "
                      f"{rate:.0f} ex/s", flush=True)
            if a["checkpoint_every"] and state["step"] % a["checkpoint_every"] == 0 and b + 1 < per_epoch:
                save_checkpoint()
        ev, lg, y = run_eval(model, tok, va, device, a["eval_bs"], a["eps"], a["max_len"], a["max_cells"])
        ev.update({"epoch": ep, "train_loss_ema": state["run"], "seconds": round(time.time() - t0)})
        log["epochs"].append(ev)
        print(f"[{name}] " + json.dumps(ev), flush=True)
        if state["best"] is None or ev["loss"] < state["best"]["loss"]:
            state["best"] = ev
            torch.save(model.state_dict(), out / "model.pt")
            state["temps"] = fit_temperature(lg, y)
        state["epoch"], state["step_in_epoch"] = ep + 1, 0
        state["seconds"] = time.time() - t0
        save_checkpoint()

    best = state["best"]
    log["best_epoch"] = best["epoch"]
    log["train_seconds"] = round(state["seconds"])
    cfg = {"backbone": backbone, "name": name, "max_len": a["max_len"], "temperature": state["temps"], "best_epoch": best["epoch"],
           "params": n_params, "model_version": f"reader-{name}-v1", "val": {k: best[k] for k in best if k != "seconds"},
           "train_seconds": log["train_seconds"], "device": str(device), "train_examples": len(tr),
           "batch_size": a["bs"], "micro_batch_size": state["micro_bs"]}
    (out / "config.json").write_text(json.dumps(cfg, indent=1))
    (out / "log.json").write_text(json.dumps(log, indent=1))
    ck.unlink(missing_ok=True)
    print(f"[{name}] done " + json.dumps(cfg), flush=True)
    return cfg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backbone", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--force", action="store_true")
    for k, v in DEFAULTS.items():
        ap.add_argument(f"--{k}", type=type(v))
    a = vars(ap.parse_args())
    train_one(a.pop("name"), a.pop("backbone"), force=a.pop("force"), **a)


if __name__ == "__main__":
    main()
