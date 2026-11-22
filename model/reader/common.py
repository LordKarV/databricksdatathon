"""Shared pieces for the evidence reader: service ids, the rule baseline, model input and the model.

Rule baseline (what the reader has to beat)
  about_this  1 unless claims.parquet attribution is 'other_facility'
  offers      1 when the sentence matches the service in kb/taxonomy/lexicon.json (include hits,
              exclude does not, a clause with the include hit survives exclude_clause), no shared
              non-offer cue fires (negation, referral, future, past, camp, plus the service's
              negation_extra), and the sentence kind is not template, research, directory or staff
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HERE = Path(__file__).resolve().parent
MAX_LEN = 160
MAX_CELLS = 64 * 160 * 160   # memory guard, rows x padded_length^2 per chunk with gradients (see train.py)
NON_OFFER_KINDS = {"template", "research", "directory", "staff"}


class Lexicon:
    def __init__(self):
        lex = json.loads((ROOT / "kb/taxonomy/lexicon.json").read_text(encoding="utf-8"))
        tax = json.loads((ROOT / "kb/taxonomy/services.json").read_text(encoding="utf-8"))
        self.services = list(lex["services"])
        self.label, self.alias = {}, {}
        for cat in tax["categories"]:
            for s in cat["services"]:
                self.label[s["id"]] = s["names"]["en"][0]
                for a in s.get("aliases", []):
                    self.alias[a] = s["id"]
        # ids used by older files
        self.alias.update({"trauma_emergency": "trauma_care", "csection": "emergency_csection", "burns": "burn_care"})
        for s in self.services:
            self.label.setdefault(s, s.replace("_", " "))
        f = re.IGNORECASE
        self.clause_split = re.compile(lex["clause_split"])
        self.nonoffer = re.compile("|".join(f"(?:{p})" for p in lex["shared_cues"]["nonoffer"].values()), f)
        self.weakening = re.compile("|".join(f"(?:{p})" for p in lex["shared_cues"]["weakening"].values()), f)
        self.rx = {}
        for s, d in lex["services"].items():
            self.rx[s] = {k: re.compile(d[k], f) for k in ("include", "exclude", "related", "exclude_clause", "negation_extra",
                                                           "strip_before_match") if d.get(k)}
        self.include_src = {s: d["include"] for s, d in lex["services"].items()}
        self.related_src = {s: d["related"] for s, d in lex["services"].items()}

    def canon(self, service):
        return self.alias.get(service, service)

    def match(self, text, service):
        """(matches the service, a non-offer cue fires). Follows the 'about' text of lexicon.json."""
        rx = self.rx[service]
        t = rx["strip_before_match"].sub(" ", text) if "strip_before_match" in rx else text
        if not rx["include"].search(t) or ("exclude" in rx and rx["exclude"].search(t)):
            return False, False
        if "exclude_clause" in rx:
            clauses = [c for c in self.clause_split.split(t) if rx["include"].search(c)]
            if clauses and all(rx["exclude_clause"].search(c) for c in clauses):
                return False, False
        cue = bool(self.nonoffer.search(text)) or ("negation_extra" in rx and bool(rx["negation_extra"].search(text)))
        return True, cue

    def rule_offers(self, text, service, kind):
        m, cue = self.match(text, service)
        return int(m and not cue and kind not in NON_OFFER_KINDS)


def context(name, city, service_label):
    """First segment of the model input. The sentence is the second segment."""
    return f"{name}, {city} | {service_label or 'any service'}"


def pick_device():
    """MPS when available, else CUDA, else CPU. READER_DEVICE=cpu forces the CPU."""
    import os

    import torch
    if os.environ.get("READER_DEVICE"):
        return torch.device(os.environ["READER_DEVICE"])
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def build_model(backbone):
    import torch
    from transformers import AutoModel

    class Reader(torch.nn.Module):
        """Encoder, mean pooling over tokens, one linear layer with two outputs: about_this, offers."""

        def __init__(self):
            super().__init__()
            self.enc = AutoModel.from_pretrained(backbone)
            self.drop = torch.nn.Dropout(0.1)
            self.head = torch.nn.Linear(self.enc.config.hidden_size, 2)

        def forward(self, input_ids=None, attention_mask=None, token_type_ids=None, inputs_embeds=None):
            kw = {"attention_mask": attention_mask}
            if token_type_ids is not None:
                kw["token_type_ids"] = token_type_ids
            if inputs_embeds is not None:
                h = self.enc(inputs_embeds=inputs_embeds, **kw).last_hidden_state
            else:
                h = self.enc(input_ids=input_ids, **kw).last_hidden_state
            m = attention_mask.unsqueeze(-1).to(h.dtype)
            pooled = (h * m).sum(1) / m.sum(1).clamp(min=1)
            return self.head(self.drop(pooled))

    return Reader()


def load_reader(run_dir, device=None):
    """Model, tokenizer and config saved by train.py."""
    import torch
    from transformers import AutoTokenizer
    run_dir = Path(run_dir)
    cfg = json.loads((run_dir / "config.json").read_text())
    tok = AutoTokenizer.from_pretrained(cfg["backbone"])
    model = build_model(cfg["backbone"])
    model.load_state_dict(torch.load(run_dir / "model.pt", map_location="cpu"))
    device = device or pick_device()
    return model.to(device).eval(), tok, cfg, device


def predict(model, tok, device, contexts, sentences, batch_size=128, temperature=(1.0, 1.0), max_len=MAX_LEN,
            max_cells=4 * MAX_CELLS):
    """Probabilities (n, 2): p_about_this, p_offers. temperature divides each head's logit."""
    import numpy as np
    import torch
    out = []
    order = sorted(range(len(sentences)), key=lambda i: len(sentences[i]))
    with torch.no_grad():
        for i in range(0, len(order), batch_size):
            idx = order[i:i + batch_size]
            enc = tok([contexts[j] for j in idx], [sentences[j] for j in idx], truncation="only_second", max_length=max_len,
                      padding=True, return_tensors="pt")
            length = int(enc["input_ids"].shape[1])
            size = max(1, min(len(idx), max_cells // (length * length)))
            logits = np.concatenate([model(**{k: v[j:j + size].to(device) for k, v in enc.items()}).float().cpu().numpy()
                                     for j in range(0, len(idx), size)])
            out.append((idx, logits))
    res = np.zeros((len(sentences), 2), dtype="float32")
    for idx, logits in out:
        res[idx] = logits
    t = np.asarray(temperature, dtype="float32")
    return 1 / (1 + np.exp(-res / t))


STOP = {"the", "a", "an", "and", "or", "of", "in", "at", "to", "for", "with", "by", "on", "is", "are", "was", "were", "as", "it",
        "its", "this", "that", "from", "has", "have", "be", "been", "also", "which", "their", "our", "we"}


def top_tokens(model, tok, device, contexts, sentences, k=3, batch_size=64, max_len=MAX_LEN, max_cells=MAX_CELLS):
    """For each input, the k words of the sentence that most support each head's predicted class.

    Method: gradient x input on the input embeddings (a one-step approximation of integrated
    gradients), summed over the embedding dimension and over the word pieces of each word. The sign
    is taken toward the predicted class, so for a sentence flagged as another facility the words
    returned are the ones pushing p_about_this down. Returns (about_words, offers_words), each a
    list of lists of strings.
    """
    import torch
    emb_layer = model.enc.get_input_embeddings()
    res = [[None, None] for _ in sentences]
    order = sorted(range(len(sentences)), key=lambda i: len(sentences[i]))
    start = 0
    while start < len(order):
        # sentences are sorted by length, so the longest in the next batch bounds the padded length
        longest = len(tok(contexts[order[min(start + batch_size, len(order)) - 1]],
                          sentences[order[min(start + batch_size, len(order)) - 1]], truncation="only_second",
                          max_length=max_len)["input_ids"])
        step = max(1, min(batch_size, max_cells // (longest * longest)))
        idx = order[start:start + step]
        start += step
        enc = tok([contexts[j] for j in idx], [sentences[j] for j in idx], truncation="only_second", max_length=max_len,
                  padding=True, return_tensors="pt", return_offsets_mapping=True)
        offsets = enc.pop("offset_mapping").numpy()
        seq_ids = [enc.sequence_ids(b) for b in range(len(idx))]
        enc = enc.to(device)
        for head in (0, 1):
            emb = emb_layer(enc["input_ids"]).detach().requires_grad_(True)
            kw = {"attention_mask": enc["attention_mask"], "inputs_embeds": emb}
            if "token_type_ids" in enc:
                kw["token_type_ids"] = enc["token_type_ids"]
            logits = model(**kw)[:, head]
            sign = torch.where(logits >= 0, 1.0, -1.0).detach()
            (logits * sign).sum().backward()
            attr = (emb.grad * emb).sum(-1).detach().float().cpu().numpy()
            for b, j in enumerate(idx):
                text, words = sentences[j], {}
                for t, (s, e) in enumerate(offsets[b]):
                    if seq_ids[b][t] != 1 or e <= s:
                        continue
                    ws = text.rfind(" ", 0, s) + 1
                    we = text.find(" ", e)
                    we = len(text) if we < 0 else we
                    words[(ws, we)] = words.get((ws, we), 0.0) + float(attr[b, t])
                ranked = sorted(words.items(), key=lambda x: -x[1])
                out = []
                for (ws, we), score in ranked:
                    w = text[ws:we].strip(" ,.;:()[]\"'|/-")
                    if score <= 0 or len(w) < 2 or w.lower() in STOP or w in out:
                        continue
                    out.append(w)
                    if len(out) == k:
                        break
                res[j][head] = out
        model.zero_grad(set_to_none=True)
    return [r[0] for r in res], [r[1] for r in res]
