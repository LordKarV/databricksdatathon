"""Label views for the final refit. Reads model/v2/labels/out only; writes final/out/labels_{cc,sens}/.

- gold: primary rows only (4 e2e rows duplicated by v3 are dropped), target y_S set to the view's rule:
  cc = confirmed 1 / contradicted 0 / no_info missing (headline); sens = MODEL_SPEC 3.2 rule (labels.py y_S).
- pu_labels: trauma_care rows dropped (decision: trauma_care trains only on v3 gold labels).
- TEST block: every facility in out/test_blocked_facilities.parquet (TEST facilities plus their leakage groups)
  must be absent from every training table, by unique_id and by leakage_group_id (asserted).
"""
import shutil
import json
from pathlib import Path

import pandas as pd

ROOT = Path("/Users/karthikvattem/projects/datathon")
LAB = ROOT / "model/v2/labels/out"
OUT = ROOT / "model/v2/final/out"


def blocked() -> tuple[set, set]:
    t = pd.read_parquet(LAB / "test_blocked_facilities.parquet")
    test_ids = {r["unique_id"] for r in json.load(open(ROOT / "model/gold/v3/test_sample.json"))}  # ids only
    ff = pd.read_parquet(ROOT / "derived/v2/facility_features.parquet", columns=["unique_id", "leakage_group_id"])
    ff = ff.drop_duplicates("unique_id")
    groups = set(ff[ff.unique_id.isin(test_ids)].leakage_group_id)
    uids = set(ff[ff.leakage_group_id.isin(groups)].unique_id)
    assert uids == set(t.unique_id), "blocked list differs from the TEST groups recomputed here"
    return uids, groups


def assert_clean(df: pd.DataFrame, uids: set, groups: set, name: str) -> None:
    lg = pd.read_parquet(ROOT / "derived/v2/facility_features.parquet", columns=["unique_id", "leakage_group_id"])
    lg = lg.drop_duplicates("unique_id").set_index("unique_id").leakage_group_id
    assert not df.unique_id.isin(uids).any(), f"{name}: TEST facility present"
    assert not df.unique_id.map(lg).isin(groups).any(), f"{name}: TEST leakage group present"


def main() -> None:
    uids, groups = blocked()
    gold = pd.read_parquet(LAB / "gold_dev_pairs.parquet")
    gold = gold[gold.primary].reset_index(drop=True)
    assert gold.pair_id.is_unique and not gold.duplicated(["unique_id", "service"]).any()
    fac = pd.read_parquet(LAB / "gold_dev_facility.parquet")
    pu = pd.read_parquet(LAB / "pu_labels.parquet")
    n_tc = int((pu.service == "trauma_care").sum())
    pu = pu[pu.service != "trauma_care"].reset_index(drop=True)
    for d, n in [(gold, "gold"), (fac, "facility"), (pu, "pu")]:
        assert_clean(d, uids, groups, n)
    stats = dict(blocked_facilities=len(uids), blocked_groups=len(groups), pu_trauma_care_rows_dropped=n_tc,
                 gold_primary=len(gold))
    for view, col in [("cc", "y_S_cc"), ("sens", "y_S")]:
        d = OUT / f"labels_{view}"
        d.mkdir(parents=True, exist_ok=True)
        g = gold.assign(y_S=gold[col])
        g.to_parquet(d / "gold_dev_pairs.parquet", index=False)
        fac.to_parquet(d / "gold_dev_facility.parquet", index=False)
        pu.to_parquet(d / "pu_labels.parquet", index=False)
        for f in ("c_estimates.parquet", "crossfit_plan.parquet", "test_blocked_facilities.parquet"):
            shutil.copy(LAB / f, d / f)
        stats[view] = dict(n=int(g.y_S.notna().sum()), pos=int(g.y_S.sum()), neg=int((g.y_S == 0).sum()))
    json.dump(stats, open(OUT / "labels_view_stats.json", "w"), indent=1)
    print(stats)


if __name__ == "__main__":
    main()
