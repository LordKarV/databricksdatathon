"""Gold pairs for evaluation: v1 (web_1..3) and v2 (labels_p*, primary) with split, stratum and IPW weight.

label: 1 confirmed, 0 contradicted, None no_info (unlabelled for precision metrics; counted as 0 only for
the spec's primary target y_primary = confirmed vs not confirmed).
"""
import glob
import json

import pandas as pd

from common import ROOT

GOLD = ROOT / "model/gold"
V1 = ROOT / "audit/ground_truth"


def load_gold() -> pd.DataFrame:
    splits = {p["pair_id"]: p for p in json.load(open(GOLD / "splits.json"))["pairs"]}
    rows = []
    v1s = {p["pair_id"]: p for p in json.load(open(V1 / "sample.json"))}
    for f in sorted(glob.glob(str(V1 / "web_*.json"))):
        for r in json.load(open(f))["results"]:
            p = v1s[r["pair_id"]]
            rows.append(dict(pair_id=r["pair_id"], version="v1", unique_id=p["unique_id"], service=p["service"],
                             stratum=p["stratum"], service_label=r["service"], exists=r.get("exists"),
                             location_ok=r.get("location_matches")))
    v2s = {p["pair_id"]: p for p in json.load(open(GOLD / "sample_v2.json"))}
    for f in sorted(glob.glob(str(GOLD / "labels_p*.json"))):
        for r in json.load(open(f))["results"]:
            p = v2s[r["pair_id"]]
            rows.append(dict(pair_id=r["pair_id"], version="v2", unique_id=p["unique_id"], service=p["service"],
                             stratum=p["stratum"], service_label=r["service"], exists=r.get("exists"),
                             location_ok=r.get("location_ok")))
    g = pd.DataFrame(rows)
    g["split"] = g.pair_id.map(lambda k: splits[k]["split"])
    g["group"] = g.pair_id.map(lambda k: splits[k]["group"])
    g["label"] = g.service_label.map({"confirmed": 1, "contradicted": 0})
    g["y_primary"] = (g.service_label == "confirmed").astype(int)
    pools = json.load(open(GOLD / "sample_v2_stats.json"))["pool_sizes"]
    g["ipw"] = [pools[f"{s}_{st}"] / 5 if v == "v2" else float("nan") for s, st, v in zip(g.service, g.stratum, g.version)]
    assert g.pair_id.is_unique
    return g


if __name__ == "__main__":
    g = load_gold()
    print(g.groupby(["version", "split", "service_label"]).size().unstack(fill_value=0))
