"""Q2: how the description field is phrased, whether it repeats name and city, and whether it
contradicts structured fields (state, city, beds, year established, doctors).
Outputs q2_results.json, q2_records.parquet, handcheck_q2_*.csv."""
import json
import re
import sys

import pandas as pd
from rapidfuzz import fuzz

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/provenance")
from common import CANON_STATES, OUT, STATE_ALIASES, facilities, norm_state  # noqa: E402
from proxies import _k, place_states  # noqa: E402
from q1_sources import state_conflict  # noqa: E402

STYLE_RULES = [  # first match wins
    ("non_english", None),
    ("label_only", None),
    ("scraped_truncated", re.compile(r"(\.\.\.\s*read more|\.\.\.$|…$)", re.I)),
    ("extractor_meta", re.compile(
        r"\b(listed (?:among|as|in|on|under)|is listed|the page|this page|webpage|web page|"
        r"listing|mentioned in|is mentioned|site mentions|provided content|the source|"
        r"appears (?:in|on)|featured on|profile on|directory)\b", re.I)),
    ("first_person_marketing", re.compile(r"\b(we|our|us|you|your)\b", re.I)),
]
BEDS = re.compile(r"(?<![\d,])(\d{1,2},\d{3}|\d{1,4})\+?\s*[- ]?\s*(?:bed(?:ded|s)?|beds?)\b"
                  r"(?!\s*(?:ICU|NICU|PICU|MICU|SICU|CCU|HDU|dialysis|isolation))", re.I)
YEAR = re.compile(r"\b(?:established|estd\.?|founded|since|started|set up|incepted|inaugurated)"
                  r"\D{0,25}?((?:18|19|20)\d{2})\b", re.I)
DOCS = re.compile(r"\b(\d{1,4})\+?\s*(?:doctors|consultants|specialists|physicians)\b", re.I)
LOCATED = re.compile(r"\b(?:located|situated|based)\s+(?:in|at)\s+(?:the\s+)?(?:heart of\s+)?"
                     r"(?:[A-Z][\w.]*\s+){0,3}?([A-Z][a-z]{3,})\b(?=[,.\s]|$)")
STATE_RX = re.compile(r"\b(" + "|".join(sorted(
    [re.escape(s.title()) for s in CANON_STATES if s != "THE DADRA AND NAGAR HAVELI AND DAMAN AND DIU"]
    + ["Orissa", "Pondicherry", "Tamilnadu", "Uttaranchal"], key=len, reverse=True)) + r")\b",
    re.I)


def style(desc):
    letters = re.findall(r"[^\W\d_]", desc)
    if letters and sum(not c.isascii() for c in letters) / len(letters) > 0.3:
        return "non_english"
    if len(desc.split()) <= 3:
        return "label_only"
    for name, rx in STYLE_RULES[2:]:
        if rx.search(desc):
            return name
    return "third_person_summary"


def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def name_core(name):
    # drop the address tail some names carry ("X Clinic - Pipeline Rd, ...")
    return re.split(r"\s[-|,(]\s?|,", name or "")[0].strip().lower()


def main():
    f = facilities()
    places = place_states()
    # unambiguous, distinctive place names (>= 5 letters, one state) for city contradictions
    uniq = {k: next(iter(v)) for k, v in places.items() if len(v) == 1 and len(k) >= 5}
    rows = []
    for r in f.itertuples(index=False):
        d = r.description or ""
        dl = d.lower()
        stated = norm_state(r.address_stateOrRegion)
        nc = name_core(r.name)
        city = (r.address_city or "").strip().lower()
        ms = {norm_state(m.group(1)) for m in STATE_RX.finditer(d)} - {None}
        other_states = sorted(s for s in ms if stated and state_conflict(stated, {s}))
        # location contradiction: the place named right after "located in/at" (or "in X,")
        # resolves to a single state that conflicts with the stated state
        other_places = sorted({w for w in LOCATED.findall(d)
                               if _k(w) in uniq and stated and _k(w) != _k(city)
                               and state_conflict(stated, {uniq[_k(w)]})})
        beds = [int(x.replace(',', '')) for x in BEDS.findall(d)]
        cap = num(r.capacity)
        yrs = [int(x) for x in YEAR.findall(d)]
        ye = num(r.yearEstablished)
        docs = [int(x) for x in DOCS.findall(d)]
        nd = num(r.numberDoctors)
        rows.append({
            "unique_id": r.unique_id, "name": r.name, "city": r.address_city, "state": stated,
            "description": d, "n_chars": len(d), "n_words": len(d.split()), "style": style(d),
            "repeats_name": len(nc) >= 4 and fuzz.partial_ratio(nc, dl) >= 90,
            "repeats_city": len(city) >= 3 and city in dl,
            "desc_other_state": "|".join(other_states) or None,
            "desc_other_place": "|".join(other_places) or None,
            "beds_desc": beds[0] if beds else None, "capacity": cap,
            "beds_conflict": bool(beds and cap and all(abs(b - cap) > max(5, 0.2 * cap) for b in beds)),
            "year_desc": yrs[0] if yrs else None, "year_field": ye,
            "year_conflict": bool(yrs and ye and all(abs(y - ye) > 1 for y in yrs)),
            "docs_desc": docs[0] if docs else None, "doctors_field": nd,
            "docs_conflict": bool(docs and nd and all(abs(x - nd) > max(2, 0.2 * nd) for x in docs)),
        })
    q = pd.DataFrame(rows)
    q.to_parquet(f"{OUT}/q2_records.parquet", index=False)
    n = len(q)
    res = {
        "records": n,
        "chars_quantiles": q.n_chars.quantile([.05, .25, .5, .75, .95, .99]).to_dict(),
        "words_quantiles": q.n_words.quantile([.05, .25, .5, .75, .95]).to_dict(),
        "style_counts": q["style"].value_counts().to_dict(),
        "exact_duplicate_descriptions": {
            "records_sharing_text": int(q.description.duplicated(keep=False).sum()),
            "distinct_shared_texts": int(q.description[q.description.duplicated(keep=False)].nunique()),
            "top": q.description.value_counts().head(8).to_dict()},
        "repeats_name": int(q.repeats_name.sum()), "repeats_city": int(q.repeats_city.sum()),
        "repeats_both": int((q.repeats_name & q.repeats_city).sum()),
        "state_known": int(q.state.notna().sum()),
        "desc_mentions_other_state": int(q.desc_other_state.notna().sum()),
        # ponytail: 'located in <Place>' check kept for the record; hand-check precision was
        # about 2/30 (street and locality names collide with place names in other states)
        "desc_located_in_other_state_place_LOW_PRECISION": int(q.desc_other_place.notna().sum()),
        "beds": {"desc_has_beds": int(q.beds_desc.notna().sum()),
                 "both_present": int((q.beds_desc.notna() & q.capacity.notna()).sum()),
                 "conflict": int(q.beds_conflict.sum()),
                 "desc_only_capacity_missing": int((q.beds_desc.notna() & q.capacity.isna()).sum())},
        "year": {"desc_has_year": int(q.year_desc.notna().sum()),
                 "both_present": int((q.year_desc.notna() & q.year_field.notna()).sum()),
                 "conflict": int(q.year_conflict.sum()),
                 "desc_only_field_missing": int((q.year_desc.notna() & q.year_field.isna()).sum())},
        "doctors": {"desc_has_doctors": int(q.docs_desc.notna().sum()),
                    "both_present": int((q.docs_desc.notna() & q.doctors_field.notna()).sum()),
                    "conflict": int(q.docs_conflict.sum())},
    }
    # does description contradiction line up with the q1 proxies?
    rec = pd.read_parquet(f"{OUT}/q1_records.parquet")[["unique_id", "any_proxy", "p4_coord_far_from_pin"]]
    m = q.merge(rec, on="unique_id")
    c = m.desc_other_state.notna() | m.desc_other_place.notna()
    res["desc_location_conflict_vs_q1_any_proxy"] = {
        "conflict_records": int(c.sum()), "of_which_any_proxy": int(m.loc[c, "any_proxy"].sum()),
        "base_any_proxy_rate_pct": round(100 * m.any_proxy.mean(), 2)}
    with open(f"{OUT}/q2_results.json", "w") as fh:
        json.dump(res, fh, indent=1, default=str)
    for col, fn in (("desc_other_state", "state"), ("desc_other_place", "place")):
        s = q[q[col].notna()]
        s.sample(min(30, len(s)), random_state=5)[
            ["unique_id", "name", "city", "state", col, "description"]].to_csv(
            f"{OUT}/handcheck_q2_{fn}.csv", index=False)
    s = q[q.beds_conflict | q.year_conflict]
    s.sample(min(30, len(s)), random_state=5)[
        ["unique_id", "name", "beds_desc", "capacity", "year_desc", "year_field", "description"]].to_csv(
        f"{OUT}/handcheck_q2_numeric.csv", index=False)
    for st in q["style"].unique():
        q[q["style"] == st].sample(min(8, (q["style"] == st).sum()), random_state=5)[
            ["unique_id", "style", "description"]].to_csv(
            f"{OUT}/handcheck_q2_style.csv", mode="a", index=False,
            header=not pd.io.common.file_exists(f"{OUT}/handcheck_q2_style.csv"))
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
