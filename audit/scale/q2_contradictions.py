"""Q2: clinics with many beds, 1-doctor hospitals with many specialties, text bed counts vs capacity."""
import json
import pandas as pd
from common import df, num, jlist
from beds_text import bed_mentions

d = df()
d["nd"] = d["numberDoctors"].map(num)
d["cap"] = d["capacity"].map(num)
d["n_spec"] = d["specialties"].map(lambda v: len(set(jlist(v))))
out = {"denominator_rows": len(d)}
ex = lambda m, cols: d.loc[m, ["unique_id", "name"] + cols].head(12).values.tolist()

clinic = d["facilityTypeId"] == "clinic"
for thr in (50, 100, 200):
    m = clinic & (d["cap"] >= thr)
    out[f"clinic_capacity_ge_{thr}"] = {"count": int(m.sum()), "denominator_clinics_with_capacity": int((clinic & d["cap"].notna()).sum())}
out["clinic_capacity_ge_100_examples"] = ex(clinic & (d["cap"] >= 100), ["cap", "nd"])

hosp = d["facilityTypeId"] == "hospital"
for thr in (15, 20, 30):
    m = hosp & (d["nd"] == 1) & (d["n_spec"] >= thr)
    out[f"hospital_1_doctor_ge_{thr}_specialties"] = {"count": int(m.sum()), "denominator_hospitals_with_1_doctor": int((hosp & (d["nd"] == 1)).sum())}
out["hospital_1_doctor_ge_20_spec_examples"] = ex(hosp & (d["nd"] == 1) & (d["n_spec"] >= 20), ["n_spec", "cap"])
m = (d["nd"] <= 2) & (d["cap"] >= 200)
out["doctors_le_2_capacity_ge_200"] = {"count": int(m.sum()), "denominator_both_present": int((d["nd"].notna() & d["cap"].notna()).sum()), "examples": ex(m, ["nd", "cap"])}
m = d["nd"].notna() & d["cap"].notna() & (d["cap"] > 0) & (d["nd"] > 3 * d["cap"]) & (d["nd"] >= 50)
out["doctors_gt_3x_beds_and_ge_50"] = {"count": int(m.sum()), "examples": ex(m, ["nd", "cap"])}

# text vs field
rows = []
for _, r in d.iterrows():
    ms = bed_mentions(r)
    tot = sorted({n for _, n, t, _ in ms if t and n > 0})
    rows.append({"unique_id": r.unique_id, "cap": r.cap, "text_totals": tot, "any_bed_mention": bool(ms),
                 "claims": [s for _, n, t, s in ms if t][:4]})
t = pd.DataFrame(rows)
near = lambda cap, xs: any(abs(x - cap) <= max(2, 0.1 * cap) for x in xs)
has_t = t["text_totals"].map(len) > 0
has_c = t["cap"].notna()
both = has_t & has_c
agree = both & t.apply(lambda r: near(r.cap, r.text_totals) if r.cap == r.cap else False, axis=1)
disagree = both & ~agree
multi = t["text_totals"].map(lambda xs: len(xs) >= 2 and max(xs) > 1.5 * min(xs))
out["text_beds"] = {
    "records_any_bed_mention": int(t["any_bed_mention"].sum()),
    "records_with_text_total_candidate": int(has_t.sum()),
    "capacity_present": int(has_c.sum()),
    "both_present": int(both.sum()),
    "agree_within_10pct": int(agree.sum()),
    "disagree": int(disagree.sum()),
    "capacity_null_text_has_total": int((has_t & ~has_c).sum()),
    "capacity_present_no_text_total": int((~has_t & has_c).sum()),
    "records_with_conflicting_text_totals_gt_1p5x": int(multi.sum()),
}
t.loc[disagree].to_json("/Users/karthikvattem/projects/datathon/audit/scale/q2_bed_disagreements.jsonl", orient="records", lines=True)
t.loc[has_t & ~has_c].to_json("/Users/karthikvattem/projects/datathon/audit/scale/q2_bed_fillable.jsonl", orient="records", lines=True)
t.loc[multi].to_json("/Users/karthikvattem/projects/datathon/audit/scale/q2_bed_multi_totals.jsonl", orient="records", lines=True)
json.dump(out, open("/Users/karthikvattem/projects/datathon/audit/scale/q2_contradictions.json", "w"), indent=1, default=str)
print(json.dumps(out, indent=1, default=str))

# doctor counts stated in text vs numberDoctors
import re
DOC_RX = re.compile(r"(\d[\d,]*)\s*\+?\s*(?:(?:full[- ]time|qualified|experienced|expert|senior|visiting|resident)\s+)*"
                    r"(?:doctors?|physicians?|consultants?|specialists?|surgeons?)\b", re.I)
agree = dis = 0
dis_ex = []
for _, r in d.iterrows():
    if r.nd != r.nd:
        continue
    txt = " ".join([r.description or ""] + jlist(r.capability))
    ns = {int(m.group(1).replace(",", "")) for m in DOC_RX.finditer(txt)}
    if not ns:
        continue
    if r.nd in ns:
        agree += 1
    else:
        dis += 1
        dis_ex.append([r.unique_id, r.nd, sorted(ns)])
out["text_doctors"] = {"records_with_field_and_text_count": agree + dis, "field_in_text_numbers": agree, "field_not_in_text_numbers": dis, "examples": dis_ex[:12]}
json.dump(out, open("/Users/karthikvattem/projects/datathon/audit/scale/q2_contradictions.json", "w"), indent=1, default=str)
print(json.dumps(out["text_doctors"], default=str))
