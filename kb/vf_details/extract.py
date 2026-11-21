"""Extract operational details from the VF dataset into quote-backed facts.

Inputs (read-only): data/raw/facilities.parquet, cleaning/claims/out/claims.parquet (claim ids, attribution,
kind, dup flag), cleaning/claims/out/specialties.parquet, audit/scale/scale_flags.parquet (cleaned capacity,
doctors, facility type, operator). Optional: out/llm_hours.parquet from llm_hours.py.

Writes out/facts.parquet (one row per fact), out/facility_details.parquet (one row per facility x attribute),
out/hour_candidates.parquet (ambiguous hour sentences for llm_hours.py), out/stats.json.
Run: /Users/karthikvattem/projects/datathon/.venv/bin/python extract.py
"""
from __future__ import annotations

import json
import os
import re

import pandas as pd

import patterns as P

ROOT = "/Users/karthikvattem/projects/datathon"
D = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(D, "out")
RAW = f"{ROOT}/data/raw/facilities.parquet"
CLAIMS = f"{ROOT}/cleaning/claims/out/claims.parquet"
SPECS = f"{ROOT}/cleaning/claims/out/specialties.parquet"
SCALE = f"{ROOT}/audit/scale/scale_flags.parquet"

PREFILTER = re.compile(r"\d|round|around|clock|twenty|nabh|nabl|jci|joint commission|nqas|laqshya|kayakalp|ayushman|jay\b|cghs|echs|\besi|capf|insur|cashless|\btpa"
                       r"|mediclaim|scheme|yojana|arogya|aarogya|sathi|swasthya|chiranjeevi|free|government|ambulance|blood|shift|visiting|on[- ]call|weekly"
                       r"|once a|days? only|bupa|lombard|ergo|star health|paramount|medi ?assist|relhs|railway|kasp|medisep|bsky|cmchis|jeevandayee|phule|ysr|rghs|bhamashah", re.I)
DIR2 = re.compile(r"\blisted (among|on|in|as|under)\b|\branked\b|\btop \d+\b|\bdirector(y|ies)\b|justdial|practo|hexahealth|lybrate|\breviews?\b|\brated \d|\bnear (me|you)\b", re.I)
DATED = re.compile(r"\b(?:as of|in|during|since)\s+(?:19|20)\d\d\b|covid", re.I)
COUNT_TYPES = {"unit_beds", "equipment_count", "staffing", "ambulance", "hours_dialysis_shifts"}
NO_STAFF_BIO = {"accreditation", "empanelment", "free_or_government", "blood_centre", "unit_beds", "equipment_count", "ambulance", "hours_24x7"}
CAPS = {("unit_beds", "total"): 5000, "unit_beds": 1000, ("equipment_count", "dialysis_machines"): 200, ("equipment_count", "ventilators"): 1000,
        ("equipment_count", "cath_labs"): 20, ("equipment_count", "operation_theatres"): 100, "staffing": 5000, "ambulance": 200,
        "hours_dialysis_shifts": 6}
EXCLUDING = {"attr_other_facility", "kind_template", "kind_research", "staff_bio", "cue_negation", "cue_past", "cue_future", "zero_count",
             "implausible_value", "exceeds_total_beds", "dated_event", "close_before_open", "odd_open_time", "no_meridiem"}
NEGATIVE_TEXT = {"non", "not_accepted"}
NEUTRAL_TEXT = {"in_process", "norms_only", "mentioned", "outside_or_linked"}


def load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    c = pd.read_parquet(CLAIMS, columns=["claim_id", "unique_id", "field", "idx", "text", "attribution", "context", "kind", "dup_in_record"])
    raw = pd.read_parquet(RAW, columns=["unique_id", "name", "capacity", "numberDoctors", "operatorTypeId"])
    raw = raw[raw.unique_id.isin(set(c.unique_id))].drop_duplicates("unique_id")
    sc = pd.read_parquet(SCALE, columns=["unique_id", "doctors_clean", "capacity_clean", "facility_type_norm", "operator_norm"]).drop_duplicates("unique_id")
    fac = raw.merge(sc, on="unique_id", how="left")
    return c, fac, pd.read_parquet(SPECS)


def text_facts(c: pd.DataFrame, names: dict[str, str]) -> pd.DataFrame:
    rows = []
    sub = c[c.text.str.contains(PREFILTER)]
    for r in sub.itertuples(index=False):
        for h in P.all_hits(r.text, names.get(r.unique_id, "")):
            q = P.clause_quote(r.text, h.start, h.end)
            assert q in r.text and r.text[h.start:h.end] in q, (r.claim_id, q)
            rows.append({"unique_id": r.unique_id, "claim_id": r.claim_id, "field": r.field, "fact_type": h.fact_type, "attribute": h.attribute,
                         "value_num": h.value_num, "value_text": h.value_text, "quote": q, "match": r.text[h.start:h.end], "source_text": r.text,
                         "attribution": r.attribution, "context": r.context, "kind": r.kind, "dup_in_record": r.dup_in_record, "method": "regex"})
    return pd.DataFrame(rows)


def structured_facts(fac: pd.DataFrame, specs: pd.DataFrame) -> pd.DataFrame:
    """Facts read from typed fields. The quote is the raw field value, the claim id is empty."""
    rows = []
    base = {"claim_id": None, "attribution": "structured", "context": "", "kind": "structured", "dup_in_record": False, "method": "structured"}
    for r in fac.itertuples(index=False):
        if pd.notna(r.capacity_clean):
            rows.append({**base, "unique_id": r.unique_id, "field": "capacity", "fact_type": "unit_beds", "attribute": "total",
                         "value_num": float(r.capacity_clean), "value_text": None, "quote": str(r.capacity), "match": str(r.capacity), "source_text": str(r.capacity)})
        if pd.notna(r.doctors_clean):
            # audit S2: numberDoctors counts doctors named in the sources, not the staff roster
            rows.append({**base, "unique_id": r.unique_id, "field": "numberDoctors", "fact_type": "staffing", "attribute": "doctors_named",
                         "value_num": float(r.doctors_clean), "value_text": None, "quote": str(r.numberDoctors), "match": str(r.numberDoctors), "source_text": str(r.numberDoctors)})
        if r.operator_norm in ("public", "government"):
            rows.append({**base, "unique_id": r.unique_id, "field": "operatorTypeId", "fact_type": "free_or_government", "attribute": "public_operator",
                         "value_num": None, "value_text": r.operator_norm, "quote": str(r.operatorTypeId), "match": str(r.operatorTypeId), "source_text": str(r.operatorTypeId)})
    tag = specs[specs.spec.isin(["bloodbank", "transfusionmedicine"])]
    for r in tag.itertuples(index=False):
        rows.append({**base, "unique_id": r.unique_id, "field": "specialties", "fact_type": "blood_centre", "attribute": "blood_bank", "value_num": None,
                     "value_text": "specialty_tag", "quote": r.spec, "match": r.spec, "source_text": r.spec, "kind": "specialty_tag"})
    return pd.DataFrame(rows)


def cue_flags(f: pd.DataFrame) -> pd.Series:
    """Per fact: list of flags from attribution, sentence kind and cue words."""
    out = []
    for r in f.itertuples(index=False):
        fl = []
        s = r.source_text
        if r.attribution == "other_facility":
            fl.append("attr_other_facility")
        elif r.attribution == "ambiguous":
            fl.append("attr_ambiguous")
        if r.kind in ("template", "research", "list", "specialty_tag"):
            fl.append("kind_" + r.kind)
        if r.kind == "staff":
            fl.append("staff_bio" if r.fact_type in NO_STAFF_BIO else "kind_staff")
        if r.dup_in_record:
            fl.append("dup_in_record")
        if r.method != "structured":
            for k in ("negation", "past", "future", "referral", "camp", "hedge", "third_party"):
                if P.L.CUES[k].search(s) and not (k == "referral" and r.fact_type == "ambulance") and not (k == "camp" and r.attribute == "free_camp"):
                    fl.append("cue_" + k)
            if P.L.CUES["parttime"].search(s) and r.attribute != "visiting_or_on_call":
                fl.append("cue_parttime")
            if DIR2.search(s):
                fl.append("listing")
            if r.fact_type in COUNT_TYPES:
                if P.BT.SCOPE_RX.search(s):
                    fl.append("aggregate_or_future_scope")
                if P.BT.HIST_RX.search(s):
                    fl.append("historical")
                if DATED.search(s):
                    fl.append("dated")
        out.append(fl)
    return pd.Series(out, index=f.index)


def plausibility(f: pd.DataFrame, fac: pd.DataFrame) -> pd.Series:
    """Per fact: plausibility flags against hard caps, capacity, numberDoctors and facility type."""
    fac = fac.set_index("unique_id")
    tot = f[(f.attribute == "total") & (f.method != "structured") & ~f["flags"].map(lambda x: bool(set(x) & EXCLUDING))]
    text_total = tot.groupby("unique_id").value_num.max()
    ref_total = pd.concat([text_total, fac.capacity_clean]).groupby(level=0).max()
    beds_ok = ref_total.to_dict()
    out = []
    for r in f.itertuples(index=False):
        fl = []
        v = r.value_num
        if v is not None and pd.notna(v) and r.method != "structured":
            cap = CAPS.get((r.fact_type, r.attribute), CAPS.get(r.fact_type))
            if v == 0:
                fl.append("zero_count")
            elif cap is not None and v > cap:
                fl.append("implausible_value")
            if r.attribute == "ct_slices" and v > 1000:  # vendors market 500, 640, 768-slice equivalents
                fl.append("implausible_value")
            if r.attribute == "mri_tesla" and not 0.2 <= v <= 7:
                fl.append("implausible_value")
            ft = fac.facility_type_norm.get(r.unique_id)
            if r.fact_type == "unit_beds" and r.attribute != "total":
                ref = beds_ok.get(r.unique_id)
                if ref is not None and pd.notna(ref) and v > ref:
                    fl.append("exceeds_total_beds")
                if ft in ("clinic", "dentist") and r.attribute in ("icu", "nicu", "picu", "ccu", "hdu"):
                    fl.append("type_scale_mismatch")
            if r.fact_type == "unit_beds" and r.attribute == "total":
                cp = fac.capacity_clean.get(r.unique_id)
                if cp is not None and pd.notna(cp) and abs(v - cp) > 0.25 * max(v, cp):
                    fl.append("disagrees_capacity")
                if ft in ("clinic", "dentist") and v >= 100:
                    fl.append("type_scale_mismatch")
            if r.fact_type == "staffing" and r.attribute == "doctors":
                nd = fac.doctors_clean.get(r.unique_id)
                if nd is not None and pd.notna(nd) and abs(v - nd) > 0.5 * max(v, nd):
                    fl.append("disagrees_numberDoctors")
                ref = beds_ok.get(r.unique_id)
                if ref is not None and pd.notna(ref) and ref >= 10 and v > 2 * ref:
                    fl.append("doctors_exceed_beds")
        out.append(fl)
    return pd.Series(out, index=f.index)


def hour_candidates(c: pd.DataFrame) -> pd.DataFrame:
    """Sentences with clock times that the deterministic parser could not read cleanly."""
    sub = c[(c.attribution != "other_facility") & c.text.str.contains(P.TIME_ANY) & c.text.str.contains(P.HOURS_WORD)]
    rows = []
    bad = {"no_meridiem", "close_before_open", "odd_open_time", "days_unparsed", "meridiem_guessed"}
    for r in sub.itertuples(index=False):
        p = P.parse_schedule(r.text)
        if p is not None and "dated_event" in p["problems"]:
            continue
        reason = "no_parse" if p is None else ",".join(sorted(bad & set(p["problems"])))
        if reason:
            rows.append({"claim_id": r.claim_id, "unique_id": r.unique_id, "text": r.text, "reason": reason})
    return pd.DataFrame(rows)


def add_llm(f: pd.DataFrame, c: pd.DataFrame) -> pd.DataFrame:
    """Replace regex hour facts by llm facts for sentences the LLM read with a string-matched quote."""
    path = os.path.join(OUT, "llm_hours.parquet")
    if not os.path.exists(path):
        return f
    lh = pd.read_parquet(path)
    lh = lh[lh.keep]
    meta = c.set_index("claim_id")[["unique_id", "field", "text", "attribution", "context", "kind", "dup_in_record"]]
    rows = []
    for r in lh.itertuples(index=False):
        m = meta.loc[r.claim_id]
        rows.append({"unique_id": m.unique_id, "claim_id": r.claim_id, "field": m.field, "fact_type": "opd_hours", "attribute": r.scope,
                     "value_num": None, "value_text": r.schedule_text, "quote": r.quote, "match": r.quote, "source_text": m.text,
                     "attribution": m.attribution, "context": m.context, "kind": m.kind, "dup_in_record": m.dup_in_record, "method": "llm"})
    keep = ~((f.fact_type == "opd_hours") & f.claim_id.isin(set(lh.claim_id)))
    return pd.concat([f[keep], pd.DataFrame(rows)], ignore_index=True)


def finalize(f: pd.DataFrame) -> pd.DataFrame:
    sched_problems = []
    for r in f.itertuples(index=False):
        if r.fact_type == "opd_hours" and r.method == "regex":
            sched_problems.append([x for x in P.parse_schedule(r.source_text)["problems"] if x != "dated_event"])
        else:
            sched_problems.append(["llm_extracted"] if r.method == "llm" else [])
    f["flags"] = [sorted(set(a + b + c)) for a, b, c in zip(f["flags"], f["plaus"], sched_problems)]
    f["polarity"] = ["negative" if (t in NEGATIVE_TEXT or "cue_negation" in fl) else ("neutral" if t in NEUTRAL_TEXT else "positive")
                     for t, fl in zip(f.value_text, f["flags"])]
    f["status"] = ["excluded" if set(fl) & EXCLUDING else ("ok" if not fl or set(fl) <= {"dup_in_record"} else "flagged")
                   for fl in f["flags"]]
    f["flags"] = f["flags"].map(lambda x: "|".join(x))
    # stable across reruns: claim id (or facility + field for typed fields) + type + attribute + occurrence
    key = [f"{c}:{t}:{a}" if isinstance(c, str) else f"{u[:8]}:{fd}:{t}:{a}" for c, u, fd, t, a in zip(f.claim_id, f.unique_id, f.field, f.fact_type, f.attribute)]
    f["fact_id"] = [f"{k}:{n}" for k, n in zip(key, pd.Series(key).groupby(key).cumcount())]
    assert f.fact_id.is_unique
    cols = ["fact_id", "unique_id", "claim_id", "field", "fact_type", "attribute", "value_num", "value_text", "polarity", "status", "flags",
            "quote", "match", "source_text", "attribution", "context", "kind", "dup_in_record", "method"]
    return f.drop(columns=["plaus"])[cols]


def facility_table(f: pd.DataFrame) -> pd.DataFrame:
    """One row per facility x (fact_type, attribute): usable support, the value most often stated, and the best quote."""
    f = f.assign(usable=f.status.isin(["ok", "flagged"]) & (f.polarity == "positive"))
    rank = {"own_anchored": 0, "unanchored": 1, "structured": 2, "ambiguous": 3, "other_facility": 4}
    rows = []
    for (u, t, a), g in f.groupby(["unique_id", "fact_type", "attribute"], sort=False):
        us = g[g.usable]
        best = (us if len(us) else g).assign(r=lambda x: x.attribution.map(rank) + (x.status != "ok") * 10).sort_values("r").iloc[0]
        vals = us.value_num.dropna()
        vt = us.value_text.dropna()
        rows.append({"unique_id": u, "fact_type": t, "attribute": a,
                     "n_ok": int((g.status == "ok").sum()), "n_flagged": int((g.status == "flagged").sum()), "n_excluded": int((g.status == "excluded").sum()),
                     "n_usable": len(us), "n_negative": int((g.polarity == "negative").sum()), "n_neutral": int((g.polarity == "neutral").sum()),
                     "value_num": float(vals.mode().max()) if len(vals) else None, "n_distinct_values": int(vals.nunique()),
                     "value_text": vt.mode().iloc[0] if len(vt) else None,
                     "fields": "|".join(sorted(us.field.unique())), "methods": "|".join(sorted(us.method.unique())),
                     "claim_ids": "|".join(us.claim_id.dropna().unique()[:20]),
                     "best_quote": best.quote, "best_claim_id": best.claim_id, "best_fact_id": best.fact_id, "best_status": best.status})
    return pd.DataFrame(rows)


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    c, fac, specs = load()
    names = dict(zip(fac.unique_id, fac.name.fillna("")))
    hc = hour_candidates(c)
    hc.to_parquet(os.path.join(OUT, "hour_candidates.parquet"), index=False)
    f = pd.concat([text_facts(c, names), structured_facts(fac, specs)], ignore_index=True)
    f = add_llm(f, c)
    f["flags"] = cue_flags(f)
    f["plaus"] = plausibility(f, fac)
    f = finalize(f)
    assert f.apply(lambda r: r.quote in r.source_text, axis=1).all()
    f.to_parquet(os.path.join(OUT, "facts.parquet"), index=False)
    ft = facility_table(f)
    ft.to_parquet(os.path.join(OUT, "facility_details.parquet"), index=False)

    n_fac = len(fac)
    st = {"facilities": n_fac, "claims_scanned": len(c), "facts": len(f), "hour_candidates": len(hc),
          "hour_candidate_unique_texts": int(hc.text.nunique()) if len(hc) else 0,
          "facts_by_method": f.method.value_counts().to_dict(), "facts_by_status": f.status.value_counts().to_dict(),
          "facts_by_polarity": f.polarity.value_counts().to_dict(), "coverage": {}}
    for (t, a), g in f.groupby(["fact_type", "attribute"]):
        us = g[g.status.isin(["ok", "flagged"]) & (g.polarity == "positive")]
        st["coverage"][f"{t}.{a}"] = {"facts": len(g), "ok": int((g.status == "ok").sum()), "flagged": int((g.status == "flagged").sum()),
                                      "excluded": int((g.status == "excluded").sum()), "facilities_any": int(g.unique_id.nunique()),
                                      "facilities_usable": int(us.unique_id.nunique()), "facilities_ok": int(us[us.status == "ok"].unique_id.nunique())}
    st["coverage_by_type"] = {}
    for t, g in f.groupby("fact_type"):
        us = g[g.status.isin(["ok", "flagged"]) & (g.polarity == "positive")]
        st["coverage_by_type"][t] = {"facts": len(g), "facilities_any": int(g.unique_id.nunique()), "facilities_usable": int(us.unique_id.nunique()),
                                     "facilities_ok": int(us[us.status == "ok"].unique_id.nunique()),
                                     "share_usable": round(us.unique_id.nunique() / n_fac, 4)}
    fl = f["flags"].str.split("|").explode()
    st["flag_counts"] = fl[fl != ""].value_counts().to_dict()
    st["facilities_with_any_usable_fact"] = int(ft[ft.n_usable > 0].unique_id.nunique())
    st["facility_attribute_rows"] = len(ft)
    st["conflicting_values_rows"] = int((ft.n_distinct_values > 1).sum())
    with open(os.path.join(OUT, "stats.json"), "w") as fh:
        json.dump(st, fh, indent=1, default=str)
    print(json.dumps({k: v for k, v in st.items() if k not in ("coverage",)}, indent=1, default=str))


if __name__ == "__main__":
    main()
