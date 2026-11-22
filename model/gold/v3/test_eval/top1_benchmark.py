"""End-to-end top-1 of the app engine on the 40 benchmark queries, scored against every gold label (issue #66).

    cd app && ../.venv-app/bin/python facts/build.py          # once, if app/facts/out is empty
    .venv-app/bin/python model/gold/v3/test_eval/top1_benchmark.py [--alt-ref origin/issue-92-emergency-rank]

Writes test_eval/top1_benchmark.json; evaluate.py copies its summary into results.json and model_card_test.json.

- **Queries:** model/gold/queries.json (built by model/gold/build_queries.py), each at its stored lat / lon.
- **Top-1:** options[0] of Engine.plan(), the first listing the app shows. With no options the query has no top-1.
- **Engines:** the working tree's app/facts/engine.py ("current"), and the same file at --alt-ref ("alt"), read with
  git show and run on the same facts file, so only the ranking code differs.
- **Gold:** the top-1 pair (facility, service; app trauma_emergency = taxonomy trauma_care, the model's join) looked
  up in the DEV gold the model was fitted on (model/v2/labels/out/gold_dev_pairs.parquet: v1, v2, e2e, v3 DEV) and in
  the opened v3 TEST labels. Verdicts: confirmed, contradicted, no_info (labelled, nothing decisive found) or
  no_label. Only TEST labels are held out from the fit; the e2e labels were drawn from prototype top-1 answers.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
APP = ROOT / "app"
QUERIES = ROOT / "model/gold/queries.json"
GOLD_DEV = ROOT / "model/v2/labels/out/gold_dev_pairs.parquet"
GOLD_TEST = HERE.parent / "test_labels.json"
APP_TO_TAXONOMY = {"trauma_emergency": "trauma_care"}  # as app/facts/build.py
VERSION_RANK = {"v3_dev": 0, "v2": 1, "v1": 2, "e2e": 3}  # as model/v2/labels/labels.py: which label wins

sys.path.insert(0, str(APP))


def wilson(k: int, n: int) -> dict:
    if not n:
        return {"k": 0, "n": 0, "rate": None, "ci95": None}
    z, ph = 1.96, k / n
    c = (ph + z * z / (2 * n)) / (1 + z * z / n)
    h = z * np.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return {"k": k, "n": n, "rate": round(ph, 3), "ci95": [round(c - h, 3), round(c + h, 3)]}


def gold_index() -> dict[tuple[str, str], dict]:
    """(unique_id, taxonomy service) -> label. One label per pair: TEST, else the DEV primary by VERSION_RANK."""
    g = pd.read_parquet(GOLD_DEV, columns=["pair_id", "version", "unique_id", "service", "label_service",
                                           "label_exists", "label_location", "primary"])
    g = g[g.primary].assign(r=lambda x: x.version.map(VERSION_RANK)).sort_values("r")
    g = g.drop_duplicates(["unique_id", "service"])
    idx = {(r.unique_id, r.service): {"source": r.version, "pair_id": r.pair_id, "service": r.label_service,
                                      "exists": r.label_exists, "location_ok": r.label_location}
           for r in g.itertuples()}
    for r in json.loads(GOLD_TEST.read_text())["results"]:
        k = (r["unique_id"], r["service_id"])
        assert k not in idx, f"TEST pair also in DEV gold: {k}"
        idx[k] = {"source": "v3_test", "pair_id": r["pair_id"], "service": r["service"], "exists": r["exists"],
                  "location_ok": r["location_ok"]}
    return idx


def load_engine_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses look the module up by name
    spec.loader.exec_module(mod)
    return mod


def top1(engine, queries: list[dict]) -> list[dict]:
    out = []
    for q in queries:
        plan = engine.plan(q["service"], q["lat"], q["lon"], None, "benchmark")
        o = plan["options"][0] if plan["options"] else None
        out.append({"query_id": q["query_id"], "service": q["service"], "urgency": q["urgency"],
                    "facility_id": o and o["facility_id"], "band": o and o["band"], "p": o and o["p"],
                    "minutes": o and o["travel"]["minutes"], "abstained": plan["abstain"] is not None})
    return out


def score(rows: list[dict], gold: dict) -> dict:
    for r in rows:
        svc = APP_TO_TAXONOMY.get(r["service"], r["service"])
        lab = gold.get((r["facility_id"], svc)) if r["facility_id"] else None
        r["gold_source"] = lab and lab["source"]
        r["gold_pair_id"] = lab and lab["pair_id"]
        r["verdict"] = "no_answer" if not r["facility_id"] else (lab["service"] if lab else "no_label")
        r["usable"] = bool(lab and lab["service"] == "confirmed" and lab["exists"] == "yes"
                           and lab["location_ok"] == "yes")
    v = pd.Series([r["verdict"] for r in rows])
    k_c, k_x = int((v == "confirmed").sum()), int((v == "contradicted").sum())
    decided = [r["gold_source"] for r in rows if r["verdict"] in ("confirmed", "contradicted")]
    held = [r for r in rows if r["gold_source"] == "v3_test" and r["verdict"] in ("confirmed", "contradicted")]
    return {
        "n_queries": len(rows), "answered": int(sum(bool(r["facility_id"]) for r in rows)),
        "n_with_gold_verdict": k_c + k_x, "confirmed": k_c, "contradicted": k_x,
        "unknown": int(len(rows) - k_c - k_x), "unknown_no_info": int((v == "no_info").sum()),
        "unknown_no_label": int((v == "no_label").sum()), "no_answer": int((v == "no_answer").sum()),
        "confirmed_of_decided": wilson(k_c, k_c + k_x),
        "usable_top1": int(sum(r["usable"] for r in rows)),
        # Side check, not in the counts above: old v1 / v2 / e2e trauma labels were relabelled emergency_24x7
        # (model/v2/labels), so a trauma top-1 may carry that label instead of a trauma_care one.
        "trauma_top1_emergency_24x7_verdicts": pd.Series(
            [gold[k]["service"] for r in rows if r["service"] == "trauma_emergency"
             and (k := (r["facility_id"], "emergency_24x7")) in gold], dtype=object).value_counts().to_dict(),
        "decided_by_source": pd.Series(decided, dtype=object).value_counts().to_dict(),
        "held_out_test_decided": wilson(sum(r["verdict"] == "confirmed" for r in held), len(held)),
        "top1_band": pd.Series([r["band"] or "none" for r in rows]).value_counts().to_dict(),
        "per_query": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--alt-ref", default="origin/issue-92-emergency-rank")
    a = ap.parse_args()
    from facts.engine import OUT, Engine  # noqa: PLC0415  app/ on sys.path above

    eng = Engine.load()
    assert eng is not None, "app/facts/out/facts.json.gz is missing: run app/facts/build.py first"
    queries = json.loads(QUERIES.read_text())
    assert len(queries) == 40
    gold = gold_index()
    git = ["git", "-C", str(ROOT)]
    blob = subprocess.run([*git, "hash-object", str(APP / "facts/engine.py")], capture_output=True, text=True,
                          check=True).stdout.strip()
    alt_sha = subprocess.run([*git, "rev-parse", a.alt_ref], capture_output=True, text=True, check=True).stdout.strip()
    src = subprocess.run([*git, "show", f"{alt_sha}:app/facts/engine.py"], capture_output=True, text=True,
                         check=True).stdout
    alt_blob = subprocess.run([*git, "rev-parse", f"{alt_sha}:app/facts/engine.py"], capture_output=True, text=True,
                              check=True).stdout.strip()
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "engine_alt.py"
        p.write_text(src)
        alt_mod = load_engine_module("facts.engine_alt", p)
    alt = alt_mod.Engine.load(OUT)  # the same facts file, other ranking code
    res = {
        "about": "Top-1 (first option the app shows) on the 40 benchmark queries, scored against every gold label. "
                 "Agent-labelled, not human-checked. DEV gold was used to fit the model; only v3 TEST is held out.",
        "facts_sha": eng.sha, "scores": eng.meta.get("scores"),
        "n_gold_pairs": len(gold),
        "current": {"engine": "app/facts/engine.py", "engine_blob": blob, **score(top1(eng, queries), gold)},
        "alt": {"engine": f"app/facts/engine.py at {a.alt_ref} (PR #101, emergency nearest-plausible order)",
                "commit": alt_sha, "engine_blob": alt_blob, **score(top1(alt, queries), gold)},
    }
    res["same_top1"] = sum(x["facility_id"] == y["facility_id"]
                           for x, y in zip(res["current"]["per_query"], res["alt"]["per_query"], strict=True))
    (HERE / "top1_benchmark.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "per_query"} if isinstance(v, dict) else v
                      for k, v in res.items()}, indent=1))


if __name__ == "__main__":
    main()
