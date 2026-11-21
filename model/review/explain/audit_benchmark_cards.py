"""Counts over the WL benchmark answers (40 queries) for the card-level problems found in the six reviewed cases.
Read-only. Run: /Users/karthikvattem/projects/datathon/.venv/bin/python -B audit_benchmark_cards.py
"""
import json
import math
from pathlib import Path

import pandas as pd

ROOT = Path("/Users/karthikvattem/projects/datathon")
FUS = ROOT / "model/proto/fusion"
OFF_TYPE = r"(?i)\b(eye|dental|dent|allergy|asthma|skin|derma|ivf|fertility|physio|homoeo|ayur|diagnostic|lab|pathology)"


def wilson(k: int, n: int, z: float = 1.96) -> list:
    if n == 0:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 3), round(c + h, 3)]


def frac(mask: pd.Series) -> dict:
    k, n = int(mask.sum()), int(len(mask))
    return dict(k=k, n=n, share=round(k / n, 3) if n else None, wilson95=wilson(k, n))


b = pd.read_parquet(ROOT / "model/proto/decision/benchmark_answers.parquet")
w = b[b.system == "WL"].copy()
pf = pd.read_parquet(FUS / "features_pairs.parquet", columns=["unique_id", "service", "T", "P"])
ff = pd.read_parquet(FUS / "features_facility.parquet", columns=["unique_id", "phone_class", "v_city", "d_city_km", "d_pin_km"])
pc = pd.read_parquet(FUS / "pair_contributions.parquet", columns=["unique_id", "service", "group", "contribution_logit"])
grp = pc.groupby(["unique_id", "service", "group"]).contribution_logit.sum().unstack(fill_value=0).reset_index()
w = w.merge(pf, on=["unique_id", "service"], how="left").merge(ff, on="unique_id", how="left").merge(grp, on=["unique_id", "service"], how="left")
top = w[w["rank"] == 1]
plan = w[w.in_plan.astype(bool)]
# the card's "where" line: share of location belief that lies outside the radius used
p_in = w.P_L * (w.d1_km <= w.R_used) + (1 - w.P_L) * w.d2_km.fillna(1e9).le(w.R_used)
out = dict(
    n_queries=int(top.query_id.nunique()),
    top1_abstained=frac(top.abstained.astype(bool)),
    top1_no_own_sentence_T_lt_2=frac(top["T"] < 2),
    top1_context_logit_exceeds_evidence_logit=frac(top.context > top.evidence),
    plan_members=int(len(plan)),
    plan_off_type_name=frac(plan.name.str.contains(OFF_TYPE)),
    plan_off_type_examples=plan[plan.name.str.contains(OFF_TYPE)][["query_id", "service", "name", "plan_role"]].head(12).to_dict("records"),
    plan_P_location_inside_radius_lt_0_5=frac(p_in.loc[plan.index] < 0.5),
    plan_primary_point_outside_radius=frac(plan.d1_km > plan.R_used),
    plan_primary_point_outside_radius_examples=plan[plan.d1_km > plan.R_used][["query_id", "name", "d1_km", "d2_km", "P_L", "R_used"]].round(2).head(10).to_dict("records"),
    # template "(no sentence of its own names the service: the score rests on facility type and size)" is shown when T < 2
    cards_T_lt_2=int((w["T"] < 2).sum()),
    cards_T_lt_2_where_P_prereq_fires=frac((w.loc[w["T"] < 2, "P"] >= 1)),
    cards_T_lt_2_where_context_logit_negative=frac(w.loc[w["T"] < 2, "context"] < 0),
    # "[4] phone none" while "[8] Call first" shows a number
    cards_phone_class_none_but_number_shown=frac((w.phone_class.isin(["none", "invalid"])) & w.phone.fillna("").ne("")),
    cards_city_vote_abstained_unresolved_city=frac(w.d_city_km.isna()),
    plan_p_any_when_abstained_mean=round(float(top.loc[top.abstained.astype(bool), "plan_p_any"].mean()), 3),
)
Path("audit_benchmark_cards.json").write_text(json.dumps(out, indent=1, default=str))
print(json.dumps(out, indent=1, default=str))
