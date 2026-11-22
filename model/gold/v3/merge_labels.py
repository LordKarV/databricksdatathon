"""Merge web-labelling batches into gold v3 labels and report agreement (issue #51).

    .venv-app/bin/python model/gold/v3/merge_labels.py dev  <batch dir>   # writes dev_labels.json + dev_report.json
    .venv-app/bin/python model/gold/v3/merge_labels.py test <batch dir> --out <path outside the repo>

Batch files are <dir>/A*_out.json (primary labeller) and <dir>/B*_out.json (independent second labeller on the
overlap ids). Every primary label is kept as the label of record; second labels are kept alongside for audit.
Cohen's kappa is computed on the overlap for the service verdict (3 classes) and for "decided" (confirmed or
contradicted vs no_info). The TEST labels must never be written inside the repo before the model is frozen
(seal.py commits only their hash).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
VERDICTS = ("confirmed", "contradicted", "no_info")
BUDGET = re.compile(r"search (tool |budget )?(budget|limit|unavailable|exhausted|ran out|stopped)"
                    r"|budget (ran out|exhausted)", re.IGNORECASE)
KEEP = ("exists", "location_ok", "service", "confidence", "evidence_urls", "quote", "notes", "searches_used")


def kappa(a: list[str], b: list[str]) -> float | None:
    n = len(a)
    if not n:
        return None
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / n**2
    return round((po - pe) / (1 - pe), 3) if pe < 1 else 1.0


def weighted(rows: list[dict]) -> dict:
    """Design-weighted rates (weight 1 / inclusion_prob) with Kish's effective n.

    headline: confirmed / (confirmed + contradicted); a dead or empty website is not evidence of absence (PR #76).
    sensitivity: MODEL_SPEC 3.2, a searched no_info counts as not offered: confirmed / all pairs.
    """
    def rate(sel: list[dict], num: str) -> dict:
        w = [1 / r["inclusion_prob"] for r in sel if r.get("inclusion_prob")]
        if not w:
            return {"rate": None, "n": 0, "n_eff": 0}
        hit = sum(1 / r["inclusion_prob"] for r in sel if r.get("inclusion_prob") and r["service"] == num)
        return {"rate": round(hit / sum(w), 3), "n": len(w), "n_eff": round(sum(w) ** 2 / sum(x * x for x in w), 1)}
    decided = [r for r in rows if r["service"] != "no_info"]
    return {"headline_confirmed_of_decided": rate(decided, "confirmed"),
            "sensitivity_confirmed_of_all": rate(rows, "confirmed")}


def method(r: dict) -> str:
    """search (up to 5 searches plus fetches) or fetch_only (no search: the session's search budget ran out)."""
    if r.get("method") == "fetch_only" or BUDGET.search(r.get("notes") or ""):
        return "fetch_only"
    return "search"


def load(dirpath: Path, prefix: str) -> dict[str, dict]:
    out = {}
    for f in sorted(dirpath.glob(f"{prefix}*_out.json")):
        doc = json.loads(f.read_text())
        for r in doc["results"]:
            if r.get("service") not in VERDICTS:
                raise SystemExit(f"{f.name}: {r.get('pair_id')} has service {r.get('service')!r}")
            q = r.get("quote") or ""
            if len(q.split()) > 25:
                raise SystemExit(f"{f.name}: {r['pair_id']} quote has more than 25 words")
            out[r["pair_id"]] = {k: r.get(k) for k in KEEP} | {"batch": doc.get("batch"), "method": method(r)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("split", choices=["dev", "test"])
    ap.add_argument("batches", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    sample = json.loads((HERE / f"{a.split}_sample.json").read_text())
    overlap = set(json.loads((HERE / "overlap.json").read_text())[a.split])
    prim, second = load(a.batches, "A"), load(a.batches, "B")
    ids = [p["pair_id"] for p in sample]
    missing = [i for i in ids if i not in prim]
    if missing:
        raise SystemExit(f"{len(missing)} pairs have no primary label, e.g. {missing[:5]}")
    meta = {p["pair_id"]: p for p in sample}
    rows = []
    for i in ids:
        r = {"pair_id": i, "unique_id": meta[i]["unique_id"], "service_id": meta[i]["service"],
             "stratum": meta[i].get("stratum"), "inclusion_prob": meta[i].get("inclusion_prob"), **prim[i]}
        if i in second:
            r["second_label"] = {k: second[i][k] for k in ("exists", "location_ok", "service", "confidence")}
        rows.append(r)
    both = [i for i in ids if i in second and i in overlap]
    found = [i for i in both if prim[i]["service"] != "no_info" or second[i]["service"] != "no_info"]
    va, vb = [prim[i]["service"] for i in both], [second[i]["service"] for i in both]
    dec = [("decided" if v != "no_info" else "no_info") for v in va]
    decb = [("decided" if v != "no_info" else "no_info") for v in vb]
    by_stratum: dict[str, Counter] = {}
    for r in rows:
        by_stratum.setdefault(r["stratum"] or "?", Counter())[r["service"]] += 1
    report = {
        "split": a.split, "pairs": len(rows), "verdicts": dict(Counter(r["service"] for r in rows)),
        "no_info_rate": round(sum(r["service"] == "no_info" for r in rows) / len(rows), 3),
        "by_stratum": {k: dict(v) for k, v in sorted(by_stratum.items())},
        "by_service": {s: dict(Counter(r["service"] for r in rows if r["service_id"] == s))
                       for s in sorted({r["service_id"] for r in rows})},
        "overlap": {"planned": len(overlap), "double_labelled": len(both),
                    "agreement": (round(sum(x == y for x, y in zip(va, vb, strict=True)) / len(both), 3)
                                  if both else None),
                    "kappa_service": kappa(va, vb), "kappa_decided": kappa(dec, decb),
                    "found_by_either": len(found),
                    "kappa_service_found_by_either": kappa([prim[i]["service"] for i in found],
                                                           [second[i]["service"] for i in found]),
                    "confusion": dict(Counter(f"{x}|{y}" for x, y in zip(va, vb, strict=True)))},
        "no_info_rate_by_method": {m: round(sum(r["service"] == "no_info" for r in rows if r["method"] == m)
                                            / max(1, sum(r["method"] == m for r in rows)), 3)
                                   for m in ("search", "fetch_only")},
        "pairs_by_method": dict(Counter(r["method"] for r in rows)),
        "weighted": weighted(rows),
        "provenance": "agent-labelled, not human-checked",
        "searches": sum(int(r.get("searches_used") or 0) for r in rows),
    }
    doc = {"about": "Gold v3 web labels (issue #51); rubric and method in model/gold/v3/README.md.",
           "report": report, "results": rows}
    if a.split == "dev":
        (HERE / "dev_labels.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    else:
        if not a.out or ROOT in a.out.resolve().parents:
            raise SystemExit("TEST labels go outside the repo: pass --out ~/.cache/referral-saathi-gold-v3/...")
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
        report = {k: report[k] for k in ("split", "pairs")}  # nothing about TEST verdicts is printed
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
