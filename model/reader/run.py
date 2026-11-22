"""One unattended entry point for the evidence reader.

    python -m model.reader.run --config model/reader/configs/full.yaml

Steps (each is skipped when its output already exists, so an interrupted run can be started again
with the same command and picks up where it stopped):
  1. build the hand-labelled eval set            model/reader/eval/eval_set.csv
  2. build the weak-label training set           model/reader/data/train.parquet
  3. train every backbone in the config          model/reader/weights/<name>/   (resumes from checkpoints;
                                                 each in its own process, a crash in one does not stop the rest)
  4. score the rule baseline and every backbone on the hand-labelled eval set
  5. choose the backbone with the lowest validation loss on the facility-grouped validation split
     (weak labels; the hand labels are reported for every backbone but never used to choose)
  6. score all claims with the chosen backbone   derived/v2/reader_scores.parquet
  7. write model/reader/out/metrics_<config name>.json

Options
  --force         redo every step
  --skip-score    stop after step 5 (no parquet written)
  READER_DEVICE=cpu forces the CPU; otherwise MPS, then CUDA, then CPU.
"""
import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))


def sh(args):
    print("+ " + " ".join(args), flush=True)
    subprocess.run([sys.executable, *args], check=True, cwd=ROOT)


def hardware():
    import torch
    info = {"platform": platform.platform(), "machine": platform.machine(), "python": platform.python_version(),
            "torch": torch.__version__, "mps": bool(torch.backends.mps.is_available()), "cpu_count": os.cpu_count()}
    try:
        info["cpu"] = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip()
        info["memory_gb"] = round(int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout) / 2**30)
    except (OSError, ValueError):
        pass
    return info


def main():
    ap = argparse.ArgumentParser(prog="python -m model.reader.run")
    ap.add_argument("--config", required=True)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--skip-score", action="store_true")
    a = ap.parse_args()
    import yaml
    cfg_path = Path(a.config)
    cfg = yaml.safe_load(cfg_path.read_text())
    name = cfg.get("name", cfg_path.stem)
    t0 = time.time()
    timings = {}

    if a.force or not (HERE / "eval" / "eval_set.csv").exists():
        sh(["model/reader/build_eval.py"])
    if a.force or not (HERE / "data" / "train.parquet").exists():
        sh(["model/reader/make_data.py"])

    # each backbone trains in its own process: a hard crash in one (for example a Metal assertion,
    # which Python cannot catch) is recorded and the run goes on with the others
    train_keys = ("epochs", "bs", "lr", "eps", "max_len", "seed", "limit", "checkpoint_every", "eval_bs", "log_every", "max_cells")
    runs, failed = {}, {}
    for b in cfg["backbones"]:
        t = time.time()
        opts = {**{k: cfg[k] for k in train_keys if k in cfg}, **b.get("overrides", {})}
        args = ["-m", "model.reader.train", "--name", b["name"], "--backbone", b["backbone"]]
        for k, v in opts.items():
            args += [f"--{k}", str(v)]
        if a.force:
            args.append("--force")
        print("+ " + " ".join(args), flush=True)
        done = subprocess.run([sys.executable, *args], cwd=ROOT)
        timings[f"train_{b['name']}"] = round(time.time() - t)
        cfg_file = HERE / "weights" / b["name"] / "config.json"
        if done.returncode == 0 and cfg_file.exists():
            runs[b["name"]] = json.loads(cfg_file.read_text())
        else:
            failed[b["name"]] = {"backbone": b["backbone"], "returncode": done.returncode,
                                 "note": "training did not finish; run the same command again to resume, or remove this backbone"}
            print(f"[{b['name']}] FAILED with return code {done.returncode}; continuing with the other backbones", flush=True)
    if not runs:
        sys.exit("no backbone finished training")

    sh(["model/reader/evaluate.py"])
    for run in runs:
        if a.force or not (HERE / "eval" / f"results_{run}.json").exists():
            sh(["model/reader/evaluate.py", "--run", run])
    best = min(runs, key=lambda r: runs[r]["val"]["loss"])
    print(f"chosen backbone: {best} (lowest validation loss {runs[best]['val']['loss']:.4f})", flush=True)

    score_stats = None
    if not a.skip_score:
        t = time.time()
        stats_path = HERE / "eval" / f"score_stats_{best}.json"
        if a.force or not stats_path.exists() or not (ROOT / "derived/v2/reader_scores.parquet").exists():
            args = ["model/reader/score.py", "--run", best]
            if cfg.get("score_limit"):
                args += ["--limit", str(cfg["score_limit"])]
            sh(args)
        score_stats = json.loads(stats_path.read_text())
        timings["score"] = round(time.time() - t)

    results = {r: json.loads((HERE / "eval" / f"results_{r}.json").read_text()) for r in runs}
    rules = json.loads((HERE / "eval" / "results_rules.json").read_text())["rules"]
    summary = {"config": name, "config_file": str(cfg_path), "settings": cfg, "hardware": hardware(), "chosen": best,
               "failed_backbones": failed,
               "chosen_by": "lowest validation loss on the facility-grouped validation split (weak labels)",
               "runs": {r: {"backbone": runs[r]["backbone"], "params": runs[r]["params"], "train_seconds": runs[r]["train_seconds"],
                            "best_epoch": runs[r]["best_epoch"], "validation": runs[r]["val"], "temperature": runs[r]["temperature"],
                            "hand_labels": {t: {"reader": results[r]["reader"][t], "reader_vs_rules": results[r]["reader_vs_rules"][t],
                                                "calibration": results[r]["calibration_reader"][t],
                                                "disagreements_on_eval": results[r]["disagreements_on_eval"][t]}
                                            for t in results[r]["reader"]}}
                        for r in runs},
               "rules_on_hand_labels": rules, "eval_rows": results[best]["eval_rows"], "scoring": score_stats,
               "timings_seconds": timings, "total_seconds": round(time.time() - t0)}
    (HERE / "out").mkdir(exist_ok=True)
    out = HERE / "out" / f"metrics_{name}.json"
    out.write_text(json.dumps(summary, indent=1))
    print(f"wrote {out.relative_to(ROOT)}", flush=True)
    for t in rules:
        r, m = rules[t]["class_0"], results[best]["reader"][t]["class_0"]
        d = results[best]["reader_vs_rules"][t]["class_0"]
        print(f"{t}: detecting label 0. rules P {r['precision']} R {r['recall']} F1 {r['f1']} | reader P {m['precision']} "
              f"R {m['recall']} F1 {m['f1']} | F1 difference {d['f1_reader_minus_rules']} CI {d['ci95']}", flush=True)


if __name__ == "__main__":
    main()
