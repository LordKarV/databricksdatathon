"""Step 2: one row per gold facility-service pair with merged web verdicts and the frozen split.

Inputs: model/gold/splits.json (176 pairs, frozen test split), audit/ground_truth/web_1..3.json (36 v1 pairs),
model/gold/labels_*.json (v2 batches, some pairs labelled twice). Merge rule for a pair labelled more than once:
a verdict field keeps the most informative value (yes/no, confirmed/contradicted beat unclear/no_info) from
the highest-confidence batch; two informative values that disagree become 'conflict' and are not used.
Writes derived/v1/_work/gold_pairs.parquet.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ss_common import ROOT, WORK

SERVICE_MAP = {"dialysis": "dialysis", "emergency_csection": "csection", "nicu": "nicu", "mri": "mri",
               "cardiac_surgery": "cardiac_surgery", "burn_care": "burns", "trauma_emergency": "trauma"}
CONF = {"high": 3, "medium": 2, "low": 1}
INFORMATIVE = {"exists": {"yes", "no"}, "location_ok": {"yes", "no"}, "service": {"confirmed", "contradicted"}}


def load_labels() -> list[dict]:
    files = sorted((ROOT / "audit/ground_truth").glob("web_*.json")) + sorted((ROOT / "model/gold").glob("labels_*.json"))
    out = []
    for f in files:
        for r in json.loads(f.read_text())["results"]:
            out.append({**r, "location_ok": r.get("location_ok", r.get("location_matches")),
                        "label_file": str(f.relative_to(ROOT))})
    return out


def merge_field(labels: list[dict], field: str) -> str:
    vals = [(CONF.get(x.get("confidence"), 0), x[field]) for x in labels if x.get(field) in INFORMATIVE[field]]
    if not vals:
        return labels[0].get(field) or "unclear"
    if len({v for _, v in vals}) > 1:
        return "conflict"
    return max(vals)[1]


def main() -> None:
    splits = json.loads((ROOT / "model/gold/splits.json").read_text())["pairs"]
    by_pair: dict[str, list[dict]] = {}
    for x in load_labels():
        by_pair.setdefault(x["pair_id"], []).append(x)
    rows = []
    for p in splits:
        labs = by_pair.get(p["pair_id"], [])
        if not labs:
            continue
        labs = sorted(labs, key=lambda x: -CONF.get(x.get("confidence"), 0))
        rows.append(dict(
            pair_id=p["pair_id"], unique_id=p["unique_id"], service=SERVICE_MAP[p["service"]], stratum=p["stratum"],
            split=p["split"], n_labels=len(labs), exists=merge_field(labs, "exists"),
            location_ok=merge_field(labs, "location_ok"), service_verdict=merge_field(labs, "service"),
            confidence=labs[0].get("confidence"),
            evidence_urls=json.dumps(sorted({u for x in labs for u in x.get("evidence_urls") or []})[:6]),
            label_files="|".join(sorted({x["label_file"] for x in labs}))))
    g = pd.DataFrame(rows)
    g.to_parquet(WORK / "gold_pairs.parquet", index=False)
    st = {"pairs_in_splits": len(splits), "pairs_with_labels": len(g),
          **{f"{c}_by_split": g.groupby("split")[c].value_counts().unstack(fill_value=0).to_dict("index")
             for c in ("service_verdict", "location_ok", "exists")}}
    (WORK / "s2_stats.json").write_text(json.dumps(st, indent=1, default=int))
    print(json.dumps(st, indent=1, default=int))


if __name__ == "__main__":
    assert merge_field([{"service": "confirmed", "confidence": "low"}, {"service": "no_info", "confidence": "high"}], "service") == "confirmed"
    assert merge_field([{"service": "confirmed"}, {"service": "contradicted"}], "service") == "conflict"
    main()
