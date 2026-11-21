"""Before/after counts for every cleaning issue. Writes out/measure.json.
Run after build_claims.py and grade.py: /Users/karthikvattem/projects/datathon/.venv/bin/python measure.py
"""
import json, os, re
import duckdb, pandas as pd

D = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(D, "out")
RAW = "/Users/karthikvattem/projects/datathon/data/raw/facilities.parquet"
AUD = "/Users/karthikvattem/projects/datathon/audit/claims/out"
MERGE = "/Users/karthikvattem/projects/datathon/audit/merge/out"
UUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


def main():
    c = pd.read_parquet(f"{OUT}/claims.parquet")
    sv = c[c.services != ""]
    g1, g2 = pd.read_parquet(f"{OUT}/grades_v1.parquet"), pd.read_parquet(f"{OUT}/grades.parquet")
    g2n = pd.read_parquet(f"{OUT}/grades_noquarantine.parquet")
    m = {}
    m["rows"] = duckdb.sql(f"select count(*) n, count(distinct unique_id) d from read_parquet('{RAW}') where regexp_matches(unique_id,'{UUID}') and source='kie'").df().iloc[0].to_dict()
    m["exact_duplicate_claims"] = {"claims": len(c), "flagged_dup_in_record": int(c.dup_in_record.sum()),
                                   "service_claims": len(sv), "service_claims_dup": int(sv.dup_in_record.sum())}
    own = g2[g2.n_own > 0]
    m["field_echo"] = {"pairs_with_own_claims": len(own), "own_claims_raw": int(own.n_own.sum()), "own_claims_distinct": int(own.n_own_distinct.sum()),
                       "pairs_2plus_fields": int((own.own_fields.str.count(r"\|") >= 1).sum()),
                       "pairs_2plus_fields_but_1_distinct_claim": int(((own.own_fields.str.count(r"\|") >= 1) & (own.n_own_distinct == 1)).sum())}
    sp = pd.read_parquet(f"{OUT}/specialties.parquet")
    m["specialties"] = {"raw_items": int(sp.n_raw.sum()), "distinct_normalised_per_record": len(sp), "distinct_values": int(sp.spec.nunique()),
                        "tag_only_pairs": g2[g2.grade == "tag_only"].groupby("service").size().to_dict()}
    m["attribution_all_claims"] = c.attribution.value_counts().to_dict()
    m["attribution_service_claims"] = sv.attribution.value_counts().to_dict()
    j = g2[["unique_id", "service", "grade"]].merge(g2n[["unique_id", "service", "grade"]], on=["unique_id", "service"], suffixes=("", "_noq"))
    ch = j[j.grade != j.grade_noq]
    m["quarantine_effect_v2"] = {"pairs": len(j), "pairs_changed": len(ch),
                                 "transitions": ch.groupby(["grade_noq", "grade"]).size().rename("n").reset_index().to_dict("records")}
    m["nonoffer"] = {"service_claims_nonoffer": int(sv.nonoffer.sum()),
                     "by_cue": {k[4:]: int(sv[k].sum()) for k in sv.columns if k.startswith("cue_")},
                     "pairs_counter_evidence": int((g2.grade == "counter_evidence").sum()), "pairs_with_counter_risk": int(g2.risk_counter.sum())}
    m["sentence_kinds_service_claims"] = sv.kind.value_counts().to_dict()
    m["quantities"] = {"service_claims_with_qty": int(sv.qty_unit.notna().sum()), "pairs_with_service_qty": int(g2.qty.notna().sum()),
                       "pairs_qty_by_service": g2[g2.qty.notna()].groupby("service").size().to_dict(),
                       "unit_beds_gt_capacity": int(g2.risk_unit_gt_capacity.sum())}
    m["truncated"] = {"records": int(g2.drop_duplicates("unique_id").truncated.sum()), "pairs": int(g2.truncated.sum())}
    risks = [k for k in g2.columns if k.startswith("risk_")]
    m["risk_flags_pairs_v2"] = {k: int(g2[k].sum()) for k in risks}
    m["scope_conflict_pairs"] = {"v1": int(g1.scope_conflict.sum()), "v2": int(g2.scope_conflict.sum())}
    m["grades_v1"] = g1.groupby("service").grade.value_counts().unstack(fill_value=0).to_dict(orient="index")
    m["grades_v2"] = g2.groupby("service").grade.value_counts().unstack(fill_value=0).to_dict(orient="index")
    m["rules_v2"] = g2.rule.value_counts().to_dict()
    # regex fixes: pairs with a text mention in the audit grader but none here, and why
    a = pd.read_parquet(f"{AUD}/grades.parquet").drop_duplicates(["unique_id", "service"])
    am = pd.read_parquet(f"{AUD}/mentions.parquet")
    a_text = set(zip(a[a.n_core > 0].unique_id, a[a.n_core > 0].service))
    mine = set(zip(g2[g2.n_mentions > 0].unique_id, g2[g2.n_mentions > 0].service))
    lost, gained = a_text - mine, mine - a_text
    why = {"mri": r"\bMri\w", "csection": r"emergency obstetric|EmON?C|obstetric emergenc|operative (vaginal )?deliver",
           "icu": r"p(a)?ediatric|PICU", "trauma": r"ambulance", "cardiac_surgery": r"glaucoma|trabeculectomy|neuro", "dialysis": r"facility|centre|center", "burns": r"post[- ]?burns?|burns? (scar|contracture|reconstruct)"}
    lost_df = am[[(u, s) in lost for u, s in zip(am.unique_id, am.service)]]
    expl = {}
    for svc, grp in lost_df.groupby("service"):
        per = grp.groupby("unique_id").sentence.apply(lambda ss: all(re.search(why.get(svc, "$^"), x, re.I) for x in ss))
        expl[svc] = {"pairs_lost": int(grp.unique_id.nunique()), "explained_by_fix_regex": int(per.sum())}
    m["regex_fix_effect_vs_audit"] = {"pairs_lost": len(lost), "pairs_gained": len(gained), "lost_by_service": expl,
                                      "gained_by_service": pd.Series([s for _, s in gained]).value_counts().to_dict() if gained else {}}
    # residual: strong grades in records that carry quarantined text about anything (merge record contamination)
    rs = pd.read_parquet(f"{MERGE}/record_scores.parquet", columns=["unique_id", "n_q"])
    s2 = g2[g2.grade == "strong"].merge(rs, on="unique_id", how="left")
    m["residual_strong_in_records_with_quarantined_text"] = {"strong_pairs": len(s2), "in_records_with_any_quarantined_sentence": int((s2.n_q > 0).sum())}
    st2 = g2[g2.grade == "strong"]
    m["strong_v2_corroboration"] = {"strong": len(st2), "tags_only": int(st2.corr_tags_only.sum()),
                                    "tags_only_by_service": st2[st2.corr_tags_only].groupby("service").size().to_dict(),
                                    "with_quantity": int(st2.corr_quantity.sum()), "self_anchored": int(st2.corr_self_anchored.sum())}
    rq = set(rs[rs.n_q > 0].unique_id)
    llm = sv[~sv.dup_in_record & (sv.attribution == "unanchored") & sv.unique_id.isin(rq)]
    m["llm_candidates"] = {"service_claims_ambiguous_or_other": int(sv[~sv.dup_in_record].attribution.isin(["ambiguous", "other_facility"]).sum()),
                           "unanchored_service_claims_in_records_with_quarantined_text": len(llm),
                           "records": int(llm.unique_id.nunique())}
    m["strong_v1_vs_v2"] = {"v1": int((g1.grade == "strong").sum()), "v2": int((g2.grade == "strong").sum())}
    geo = pd.read_parquet("/Users/karthikvattem/projects/datathon/audit/geo/facility_geo.parquet",
                          columns=["unique_id", "city_match_pin", "city_match_near"]).drop_duplicates("unique_id")
    sg = st2.merge(geo, on="unique_id", how="left")
    m["residual_strong_city_matches_neither_pin_nor_coords"] = {"strong": len(sg), "n": int(((sg.city_match_pin == False) & (sg.city_match_near == False)).sum())}
    ex = g2[g2.name.isin(["Aravind Eye Hospital", "Wockhardt Hospital Nagpur", "Government Medical College, Thiruvananthapuram"])
            & g2.service.isin(["dialysis", "burns", "nicu", "mri"])]
    m["organizer_examples"] = [dict(name=r.name, uid=r.unique_id[:8], service=r.service, grade=r.grade, rule=r.rule, risks=r.risks,
                                    evidence=[e["text"][:100] for e in json.loads(r.cite_evidence)][:2],
                                    elsewhere=[e["text"][:100] for e in json.loads(r.cite_elsewhere)]) for r in ex.itertuples()]
    json.dump(m, open(f"{OUT}/measure.json", "w"), indent=1, default=int)
    print(json.dumps(m, indent=1, default=int))


if __name__ == "__main__":
    main()
