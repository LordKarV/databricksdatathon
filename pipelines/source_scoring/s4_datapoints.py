"""Step 4: one row per data point with its evidence-only truth estimate (before any source information).

Data point types (dp_type) and their original value:
  location          raw coordinates + address city/state/PIN of the record
  existence         the record names a real, operating facility (name + city)
  service_claim     facility x service pair from the canonical v2 grade table (cleaning/claims/out/grades.parquet)
  claim_attribution each claim sentence (cleaning/claims/out/claims.parquet) is about this facility
  phone             raw officialPhone
  email             raw email field
Evidence rules (EVIDENCE below): every rule has a Beta(a0, b0) prior taken from a hand check (counts of
true / false data points it measured, each +1), updated with the gold DEV split where gold covers that
rule. q_ev = posterior mean = P(data point true | this evidence). Gold TEST pairs never enter q_ev.
strength = weight of the data point when fitting source reliability (s5_fit.py).
Writes derived/v1/_work/datapoints.parquet and _work/evidence_rules.parquet.
"""
from __future__ import annotations

import json

import pandas as pd

from ss_common import RAW, ROOT, WORK, facilities

CL = ROOT / "cleaning/claims/out"
GI = ROOT / "cleaning/geo_identity"
# rule -> (dp_type, hand-check true count, hand-check false count, citation). (0, 0) = no hand check.
EVIDENCE = {
    "LOC_CITY_ELSEWHERE": ("location", 0, 12, "cleaning/geo_identity/handcheck_location.csv: city_points_elsewhere 12 of 12 real conflicts"),
    "LOC_COORDS_FAR": ("location", 14, 20, "audit/geo/hand_check_verdicts.csv: coords right 14, wrong 20 of 34 decided (coords > 50 km from PIN)"),
    "LOC_DISPUTED_OR_LOW": ("location", 0, 0, "cleaning/geo_identity/s2_facility_location.py loc_conf low/disputed; gold dev only"),
    "LOC_MEDIUM": ("location", 0, 0, "loc_conf medium; gold dev only"),
    "LOC_HIGH": ("location", 0, 0, "loc_conf high; gold dev only"),
    "EXISTS_DEFAULT": ("existence", 0, 0, "no audit rule contradicts existence; gold dev only"),
    "G_no": ("service_claim", 1, 14, "cleaning/claims/out/handcheck.json D_nonoffer: 14 correct non-offer reads of 15"),
    "G_else": ("service_claim", 6, 17, "cleaning/claims/out/handcheck.json A_other_facility: TP 17, FP 6"),
    "G_scope": ("service_claim", 67, 44, "REPORT.md F4 (audit/merge/q3_name_content.py): about 44 true merges of 111 candidates"),
    "G_strong": ("service_claim", 0, 0, "grade strong; gold dev only"),
    "G_mod": ("service_claim", 0, 0, "grade moderate; gold dev only"),
    "G_weak": ("service_claim", 0, 0, "grade weak (G_nonspec, G_amb); gold dev only"),
    "G_tag": ("service_claim", 0, 0, "specialty tag only; gold dev only"),
    "ATTR_OTHER_FACILITY": ("claim_attribution", 6, 17, "cleaning/claims/out/handcheck.json A_other_facility: TP 17, FP 6"),
    "ATTR_AMBIGUOUS": ("claim_attribution", 4, 7, "cleaning/claims/out/handcheck.json B_ambiguous: other 7, own 4"),
    "ATTR_UNFLAGGED": ("claim_attribution", 18, 0, "cleaning/claims/out/handcheck.json C_unanchored: plausible own 18 of 18 decided"),
    "PHONE_DIRECTORY": ("phone", 12, 33, "cleaning/geo_identity/s5_trust.py (ID5): 33 of the 45 most shared numbers are directories"),
    "PHONE_UNCHECKED": ("phone", 0, 0, "no check on numbers held by one record"),
    "EMAIL_PLACEHOLDER": ("email", 0, 0, "deterministic: Cloudflare '[email protected]' placeholder is not an address (ID7)"),
    "EMAIL_UNCHECKED": ("email", 0, 0, "no check"),
}
# fitting weight per data point (design constants, see README). claim_attribution weights are split per record.
STRENGTH = {"location": 0.3, "service_claim": 0.3, "claim_attribution": 1.0, "phone": 0.3, "email": 0.3, "existence": 0.0}
GOLD_STRENGTH = 1.0
GOLD_TRUE, GOLD_FALSE = 0.97, 0.03  # assumed web-label accuracy 0.97 (labels are single-annotator web checks)
DETERMINISTIC_FALSE = 0.01


def location_rule(conf: str, flags: list[str]) -> str:
    if "city_points_elsewhere" in flags:
        return "LOC_CITY_ELSEWHERE"
    if "coords_pin_conflict_gt50km" in flags:
        return "LOC_COORDS_FAR"
    return {"high": "LOC_HIGH", "medium": "LOC_MEDIUM"}.get(conf, "LOC_DISPUTED_OR_LOW")


def service_rule(rule: str) -> str:
    return "G_weak" if rule in ("G_nonspec", "G_amb") else rule


def attribution_rule(a: str) -> str:
    return {"other_facility": "ATTR_OTHER_FACILITY", "ambiguous": "ATTR_AMBIGUOUS"}.get(a, "ATTR_UNFLAGGED")


def gold_by_record(gold: pd.DataFrame, col: str, yes: str, no: str) -> pd.DataFrame:
    """Per record: the informative verdict for col; records whose pairs disagree are dropped."""
    g = gold[gold[col].isin([yes, no])]
    agg = g.groupby("unique_id").agg(v=(col, lambda s: s.iloc[0] if s.nunique() == 1 else "conflict"),
                                     split=("split", lambda s: "test" if (s == "test").any() else "dev"),
                                     files=("label_files", "first"), urls=("evidence_urls", "first"))
    agg = agg[agg.v != "conflict"]
    return agg.assign(gold_true=agg.v == yes)


def build() -> pd.DataFrame:
    f = facilities()
    loc = pd.read_parquet(GI / "facility_location.parquet")
    tr = pd.read_parquet(GI / "record_trust.parquet").set_index("unique_id")
    gr = pd.read_parquet(CL / "grades.parquet")
    cl = pd.read_parquet(CL / "claims.parquet", columns=["claim_id", "unique_id", "field", "text", "attribution", "services", "dup_in_record"])
    parts = []
    # location
    lv = loc.raw_lat.round(5).astype(str) + "," + loc.raw_lon.round(5).astype(str) + " | " + loc.address_city.fillna("") + ", " \
        + loc.address_stateOrRegion.fillna("") + " " + loc.pin.map(lambda p: "" if pd.isna(p) else str(int(p)))
    parts.append(pd.DataFrame(dict(dp_id="loc:" + loc.unique_id, dp_type="location", unique_id=loc.unique_id, original_value=lv,
                                   rule=[location_rule(c, list(fl)) for c, fl in zip(loc.loc_conf, loc.loc_flags)])))
    # existence
    parts.append(pd.DataFrame(dict(dp_id="exist:" + f.unique_id, dp_type="existence", unique_id=f.unique_id,
                                   original_value=f["name"].fillna("") + " | " + f.address_city.fillna(""), rule="EXISTS_DEFAULT")))
    # service claims
    parts.append(pd.DataFrame(dict(dp_id="svc:" + gr.unique_id + ":" + gr.service, dp_type="service_claim", unique_id=gr.unique_id,
                                   service=gr.service, original_value=gr.cite_evidence.map(lambda s: " || ".join(x["text"] for x in json.loads(s))),
                                   rule=gr.rule.map(service_rule), grade=gr.grade, cited_claim_ids=gr.cite_evidence.map(
                                       lambda s: "|".join(x["claim_id"] for x in json.loads(s))))))
    # claim sentences
    n_rec = cl.groupby("unique_id").claim_id.transform("size")
    parts.append(pd.DataFrame(dict(dp_id="sent:" + cl.claim_id, dp_type="claim_attribution", unique_id=cl.unique_id, claim_id=cl.claim_id,
                                   field=cl.field, original_value=cl.text, rule=cl.attribution.map(attribution_rule),
                                   attribution=cl.attribution, service=cl.services.replace("", None), per_record_n=n_rec)))
    # phone and email (raw values; flags from record_trust)
    ph = f[f.officialPhone.notna() & ~f.officialPhone.isin(["", "null"])]
    parts.append(pd.DataFrame(dict(dp_id="phone:" + ph.unique_id, dp_type="phone", unique_id=ph.unique_id, original_value=ph.officialPhone,
                                   rule=["PHONE_DIRECTORY" if "official_phone_is_directory" in tr.trust_flags.get(u, []) else "PHONE_UNCHECKED"
                                         for u in ph.unique_id])))
    em = f[f.email.notna() & ~f.email.isin(["", "null", "[]"])]
    parts.append(pd.DataFrame(dict(dp_id="email:" + em.unique_id, dp_type="email", unique_id=em.unique_id, original_value=em.email,
                                   rule=["EMAIL_PLACEHOLDER" if tr.email_issue.get(u) == "email_placeholder" else "EMAIL_UNCHECKED"
                                         for u in em.unique_id])))
    return pd.concat(parts, ignore_index=True)


def attach_gold(dp: pd.DataFrame, gold: pd.DataFrame) -> pd.DataFrame:
    dp = dp.assign(gold_true=pd.NA, gold_split=None, gold_ref=None)
    sv = gold[gold.service_verdict.isin(["confirmed", "contradicted"])].drop_duplicates(["unique_id", "service"])
    keyed = {"svc:" + u + ":" + s: (v == "confirmed", sp, fl + " " + urls)
             for u, s, v, sp, fl, urls in zip(sv.unique_id, sv.service, sv.service_verdict, sv.split, sv.label_files, sv.evidence_urls)}
    for col, yes, no, pre in (("location_ok", "yes", "no", "loc:"), ("exists", "yes", "no", "exist:")):
        g = gold_by_record(gold, col, yes, no)
        keyed.update({pre + u: (bool(r.gold_true), r.split, r.files + " " + r.urls) for u, r in g.iterrows()})
    m = dp.dp_id.isin(keyed)
    vals = dp.loc[m, "dp_id"].map(keyed)
    dp.loc[m, "gold_true"] = vals.str[0].values
    dp.loc[m, "gold_split"] = vals.str[1].values
    dp.loc[m, "gold_ref"] = vals.str[2].values
    return dp


def rule_table(dp: pd.DataFrame) -> pd.DataFrame:
    """Beta posterior per rule: hand-check prior (+1 each) updated with gold DEV labels of that rule."""
    dev = dp[(dp.gold_split == "dev") & dp.gold_true.notna()]
    rows = []
    for rule, (typ, t0, f0, cite) in EVIDENCE.items():
        g = dev[dev.rule == rule]
        k, n = int(g.gold_true.astype(bool).sum()), len(g)
        a, b = t0 + 1 + k, f0 + 1 + (n - k)
        rows.append(dict(rule=rule, dp_type=typ, handcheck_true=t0, handcheck_false=f0, dev_true=k, dev_false=n - k,
                         a=a, b=b, q_ev=a / (a + b), citation=cite, n_points=int((dp.rule == rule).sum())))
    rt = pd.DataFrame(rows)
    rt.loc[rt.rule == "EMAIL_PLACEHOLDER", "q_ev"] = DETERMINISTIC_FALSE
    return rt


def main() -> None:
    gold = pd.read_parquet(WORK / "gold_pairs.parquet")
    dp = attach_gold(build(), gold)
    rt = rule_table(dp)
    dp = dp.merge(rt[["rule", "a", "b", "q_ev"]], on="rule", how="left")
    dp["strength"] = dp.dp_type.map(STRENGTH)
    s = dp.dp_type == "claim_attribution"
    dp.loc[s, "strength"] = 1.0 / dp.loc[s, "per_record_n"]  # each record's sentences share one unit of weight
    dp.loc[dp.rule.isin(["PHONE_UNCHECKED", "EMAIL_UNCHECKED"]), "strength"] = 0.0  # no information
    assert dp.dp_id.is_unique and dp.q_ev.notna().all()
    dp.drop(columns=["per_record_n"]).to_parquet(WORK / "datapoints.parquet", index=False)
    rt.to_parquet(WORK / "evidence_rules.parquet", index=False)
    print(rt[["rule", "handcheck_true", "handcheck_false", "dev_true", "dev_false", "q_ev", "n_points"]].to_string())
    print(dp.dp_type.value_counts().to_string())
    print(dp[dp.gold_true.notna()].groupby(["dp_type", "gold_split", "gold_true"]).size().to_string())


if __name__ == "__main__":
    assert location_rule("high", ["coords_pin_conflict_gt50km", "city_points_elsewhere"]) == "LOC_CITY_ELSEWHERE"
    assert service_rule("G_nonspec") == "G_weak" and attribution_rule("unanchored") == "ATTR_UNFLAGGED"
    main()
