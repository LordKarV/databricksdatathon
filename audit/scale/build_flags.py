"""Per-record cleaned scale fields and plausibility flags -> scale_flags.parquet (one row per well-formed facility).

Cleaning rules (all measured in q1-q5):
- doctors/capacity/year: impossible values set to null (doctors 0 or >1000 except when text confirms,
  capacity 0 or >5000, year <1800 or >2026); originals kept.
- capacity_text: facility-level bed total read from the record's own text (max candidate), with the claim cited.
- flags: list of short codes the finder shows as uncertainty, never used to fabricate a value.
"""
import os
import re
import pandas as pd
from common import df, num, jlist
from beds_text import bed_mentions

d = df()
rows = []
for _, r in d.iterrows():
    nd, cap, yr = num(r.numberDoctors), num(r.capacity), num(r.yearEstablished)
    ms = [(n, s) for _, n, t, s in bed_mentions(r) if t and n > 0]
    txt_tot = max(ms)[0] if ms else None
    txt_claim = max(ms)[1] if ms else None
    spec = set(jlist(r.specialties))
    name = (r["name"] or "").lower()
    f = []
    if nd is not None and (nd == 0 or nd > 1000): f.append("doctors_implausible")
    if nd == 1 and (cap or 0) >= 100: f.append("doctors_1_large_facility")
    if cap is not None and (cap == 0 or cap > 5000): f.append("capacity_implausible")
    if yr is not None and (yr < 1800 or yr > 2026): f.append("year_implausible")
    # same rule as q2: disagree only when no text total is within 10% of the field
    if cap and ms and not any(abs(n - cap) <= max(2, 0.1 * cap) for n, _ in ms): f.append("capacity_text_disagree")
    if len({n for n, _ in ms}) >= 2 and max(ms)[0] > 1.5 * min(ms)[0]: f.append("text_bed_totals_conflict")
    if r.facilityTypeId == "clinic" and (cap or 0) >= 100: f.append("clinic_with_100plus_beds")
    if len(spec) >= 15 and ((nd is not None and nd <= 2) or (cap is not None and cap <= 30)) and not ((cap or 0) >= 200 or (nd or 0) >= 50):
        f.append("breadth_exceeds_size")
    if r.facilityTypeId == "clinic" and "nursing home" in name: f.append("type_clinic_but_nursing_home")
    if re.search(r"\b(?:pets?|veterinary|vet|animal)\b", name) and not re.search(r"\bpet[- ]?(?:ct|scan|mri)\b", name):
        f.append("veterinary_name")
    rows.append({
        "unique_id": r.unique_id,
        "doctors_clean": None if "doctors_implausible" in f else nd,
        "capacity_clean": None if "capacity_implausible" in f else cap,
        "year_clean": None if "year_implausible" in f else yr,
        "capacity_text": txt_tot, "capacity_text_claim": txt_claim,
        "n_specialties_distinct": len(spec),
        "facility_type_norm": {"farmacy": "pharmacy", "null": None, "nursing_home": "hospital"}.get(r.facilityTypeId, r.facilityTypeId),
        "operator_norm": {"government": "public", "null": None}.get(r.operatorTypeId, r.operatorTypeId),
        "scale_flags": f,
    })
out = pd.DataFrame(rows)
out.to_parquet(os.path.join(os.path.dirname(os.path.abspath(__file__)), "scale_flags.parquet"), index=False)
fc = pd.Series([x for f in out.scale_flags for x in f]).value_counts()
print("rows", len(out), "rows_with_any_flag", int((out.scale_flags.map(len) > 0).sum()))
print(fc.to_string())
print("capacity_clean null but capacity_text present:", int((out.capacity_clean.isna() & out.capacity_text.notna()).sum()))
