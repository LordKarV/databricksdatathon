"""Print every number WEB_EVIDENCE.md cites. Run: .venv/bin/python report_numbers.py > out/report_numbers.txt"""
from __future__ import annotations

import json
import os

import pandas as pd

from compare_dataset import OUT, ROOT, SERVICE_IDS

USABLE_STATUS = ("ok", "flagged")


def main() -> None:
    loc = pd.read_parquet(f"{ROOT}/cleaning/geo_identity/facility_location.parquet", columns=["unique_id", "state_final"]).drop_duplicates("unique_id")
    ft = pd.read_parquet(f"{ROOT}/audit/scale/scale_flags.parquet", columns=["unique_id", "facility_type_norm"]).drop_duplicates("unique_id")
    loc = loc.merge(ft, on="unique_id", how="left").fillna({"facility_type_norm": "other_or_null"})
    si = pd.read_parquet(os.path.join(OUT, "site_identity.parquet"))
    print("site_identity rows by kind x confidence\n", si.groupby(["kind", "confidence"]).size().unstack(fill_value=0).to_string())
    print("attributable rows:", int(si.attributable.sum()), "of", len(si), "| own site and branch rows:", int((si.kind != "shared_home").sum()))
    print("name_how among attributable:", si[si.attributable].name_how.value_counts().to_dict())
    print("pin found among attributable:", int(si[si.attributable].pin_found.sum()), "| locality found:", int(si[si.attributable].locality_found.sum()))
    print("conflicts: other_pin_only", int(si.other_pin_only.sum()), "| other place in host or name line", int((si.domain_other_place != "").sum()), "| parked", int(si.parked_page.sum()))
    att = set(si[si.attributable].unique_id)
    reached = set(si.unique_id)
    cov = loc.assign(reached=loc.unique_id.isin(reached), att=loc.unique_id.isin(att)).groupby("facility_type_norm")[["reached", "att"]].agg(["sum", "count"])
    print("records by type: reachable site linked / attributable\n", cov.to_string())
    st = loc.assign(att=loc.unique_id.isin(att)).groupby("state_final").att.agg(["sum", "count"])
    st["share"] = (st["sum"] / st["count"]).round(3)
    print("states with >=1 attributable record:", int((st["sum"] > 0).sum()), "of", len(st))
    print("lowest shares (states with 10+ records):\n", st[st["count"] >= 10].sort_values("share").head(5).to_string())

    svc = pd.read_parquet(os.path.join(OUT, "web_services.parquet"))
    a = svc[svc.attributable]
    print("service rows:", len(svc), "| attributable:", len(a), "| chain_home rows:", int((svc.scope == "chain_home").sum()))
    print("attributable by strength:", a.strength.value_counts().to_dict(), "| negated:", int(a.negated.sum()), "| nonoffer cue:", a[a.nonoffer_cue != ""].nonoffer_cue.value_counts().to_dict())
    print("not positive because kind:", a[~a.negated & (a.nonoffer_cue == "")].kind.value_counts().to_dict(), "| edu:", int((a.edu & ~a.negated).sum()))
    ss = pd.read_parquet(os.path.join(OUT, "web_service_summary.parquet"))
    print("records with >=1 positive service:", ss[ss.web_positive].unique_id.nunique(), "| strong:", ss[ss.web_positive_strong].unique_id.nunique())
    per = pd.DataFrame({"records_positive": ss[ss.web_positive].groupby("service_id").unique_id.nunique(),
                        "records_strong": ss[ss.web_positive_strong].groupby("service_id").unique_id.nunique()}).reindex(SERVICE_IDS).fillna(0).astype(int)
    print("per service\n", per.to_string())

    h = pd.read_parquet(os.path.join(OUT, "web_hours.parquet"))
    hu = h[h.attributable & h.status.isin(USABLE_STATUS) & (h.polarity == "positive")]
    print("hour rows:", len(h), "| usable attributable:", len(hu), "| by method:", hu.method.value_counts().to_dict())
    print("records per hours attribute\n", hu.groupby(["fact_type", "attribute"]).unique_id.nunique().to_string())
    e = hu[(hu.fact_type == "hours_24x7") & (hu.attribute == "emergency")]
    print("records with 24x7 emergency:", e.unique_id.nunique(), "| with status ok:", e[e.status == "ok"].unique_id.nunique())
    o = hu[(hu.fact_type == "opd_hours") & hu.attribute.isin(["opd", "general"])]
    print("records with an OPD or general schedule:", o.unique_id.nunique(), "| opd scope:", o[o.attribute == "opd"].unique_id.nunique())

    d = pd.read_parquet(os.path.join(OUT, "web_details.parquet"))
    du = d[d.attributable & d.status.isin(USABLE_STATUS) & (d.polarity == "positive")]
    print("detail rows:", len(d), "| usable attributable:", len(du))
    print("records per detail attribute\n", du.groupby(["fact_type", "attribute"]).unique_id.nunique().to_string())
    for f in ("stats_build.json", "stats_compare.json", "selfcheck.json", "llm_statements.json"):
        print(f, json.dumps(json.load(open(os.path.join(OUT, f))), default=str)[:1500])
    llm = pd.read_parquet(os.path.join(OUT, "llm_hours.parquet"))
    print("llm verdicts:", llm.verdict.value_counts().to_dict())
    for r in ("round1", "round2"):
        x = pd.read_csv(os.path.join(OUT, f"selfcheck_{r}.csv"))
        print(r, int(x.correct.sum()), "/", len(x), x.groupby("stratum").correct.agg(["sum", "count"]).to_dict("index"))


if __name__ == "__main__":
    main()
