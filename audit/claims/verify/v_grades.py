"""Re-check the finder's grade counts and stress-test the grader's logic.
1. Grade counts from grades.parquet, by row and by distinct unique_id.
2. Re-apply the stated rule to the aggregate columns.
3. Circularity: is each prerequisite met by a sentence OTHER than a core mention of the same service?
4. Quantity cue false positives ('24x7 dialysis' read as a count).
Uses the finder's regex specs only to audit the finder's own logic. Writes out/v_grades.json."""
import json, re, sys
import pandas as pd
sys.path.insert(0, "..")
from services import SERVICES, ICU_STRIP, norm_spec
from v_common import load

g = pd.read_parquet("../out/grades.parquet"); fm = pd.read_parquet("../out/mentions.parquet")
res = {}
for svc in SERVICES:
    s = g[(g.service == svc) & (g.n_core > 0)]
    res.setdefault("grades_rows", {})[svc] = s.grade.value_counts().to_dict()
    res.setdefault("grades_distinct_uid", {})[svc] = s.drop_duplicates("unique_id").grade.value_counts().to_dict()
    res.setdefault("all_prereqs_rows", {})[svc] = int((s.prereq_frac == 1).sum())


def rule(r):
    if r.n_clean == 0 and r.n_core > 0: return "non_offer_only"
    if r.n_core == 0: return "enum_only"
    if r.n_own == 0: return "other_facility_only"
    full = r.prereq_frac == 1.0; corr = r.n_fields_own >= 2 or r.has_qty
    if r.n_specific >= 1 and full and corr: return "strong"
    if r.n_specific >= 1 and (r.prereq_frac >= .5 or r.n_fields_own >= 2): return "medium"
    return "weak"


g["re"] = [rule(r) for r in g.itertuples()]
g["re_capped"] = ["weak" if sc and x in ("strong", "medium") else x for sc, x in zip(g.scope_conflict, g.re)]
res["rule_reapplied_mismatches"] = int((g.re_capped != g.grade).sum())

# 3. circularity of prerequisites
df = load()
recs = {r["unique_id"]: r for r in df.drop_duplicates("unique_id").to_dict("records")}
def sents(r):
    for f in ["procedure", "equipment", "capability"]:
        for s in r[f]: yield s
    for s in re.split(r"(?<=[.!?])\s+", r["description"]):
        if s.strip(): yield s.strip()
circ = {}
strong = g[(g.grade == "strong")].drop_duplicates(["unique_id", "service"])
for svc, d in SERVICES.items():
    sub = g[(g.service == svc) & (g.n_core > 0) & (g.prereq_frac == 1)].drop_duplicates("unique_id")
    n_any_circ = n_strong_circ = 0; by_pre = {k: 0 for k in d["prereqs"]}
    st_ids = set(strong[strong.service == svc].unique_id)
    for uid in sub.unique_id:
        r = recs[uid]; spec = {norm_spec(x) for x in r["specialties"]}
        ss = list(sents(r))
        core = {s for s in ss if d["core"].search(ICU_STRIP.sub(" ", s) if svc == "icu" else s)}
        circular = False
        for name, (prx, pset) in d["prereqs"].items():
            indep = any(prx.search(s) for s in ss if s not in core) or bool(spec & pset)
            if not indep:
                by_pre[name] += 1; circular = True
        n_any_circ += circular; n_strong_circ += circular and uid in st_ids
    circ[svc] = dict(all_prereqs=len(sub), some_prereq_only_from_core_sentence=n_any_circ, by_prereq=by_pre,
                     strong=len(st_ids), strong_with_circular_prereq=n_strong_circ)
res["prereq_circularity"] = circ

# 3b. MRI scanner prereq satisfied only by a vendor name in a sentence that does not mention MRI
VENDOR = re.compile(r"siemens|philips|\bGE\b|signa|ingenia|achieva|magnetom", re.I)
SCAN = SERVICES["mri"]["prereqs"]["mri_scanner"][0]
MRI = re.compile(r"\bMRI\b|magnetic resonance", re.I)
v_only = v_only_strong = 0; ex = []
for uid in g[(g.service == "mri") & (g.pre_mri_scanner == True)].drop_duplicates("unique_id").unique_id:
    ss = list(sents(recs[uid])); hits = [s for s in ss if SCAN.search(s)]
    if hits and all(VENDOR.search(s) and not MRI.search(s) for s in hits):
        v_only += 1; ex.append((uid[:8], hits[0][:110]))
        v_only_strong += uid in set(strong[strong.service == "mri"].unique_id)
res["mri_scanner_prereq_only_from_vendor_in_nonmri_sentence"] = dict(facilities=v_only, of_them_strong=v_only_strong, examples=ex[:8])

# 4. qty cue that is really '24x7' / '24/7' / '24 hours'
T247 = re.compile(r"24\s*(x|/|×|\*|-|hours?|hrs?)\s*7?\s*", re.I)
q = {}
for svc, d in SERVICES.items():
    ms = fm[(fm.service == svc) & fm.qty & ~fm.nonoffer]
    fake = ms[ms.sentence.map(lambda s: not d["qty"].search(T247.sub(" ", s)))]
    st = g[(g.service == svc) & (g.grade == "strong") & (g.n_fields_own < 2)].drop_duplicates("unique_id")
    # strong grades resting on qty alone, where every qty sentence is a fake (24x7) quantity
    real_q = set(ms[~ms.index.isin(fake.index)].unique_id)
    q[svc] = dict(qty_sentences=len(ms), qty_only_from_24x7=len(fake), strong_single_field=len(st),
                  strong_single_field_qty_is_only_24x7=int((~st.unique_id.isin(real_q)).sum()),
                  examples=fake.sentence.str[:90].head(3).tolist())
res["qty_24x7_false_positive"] = q
json.dump(res, open("out/v_grades.json", "w"), indent=1, default=int)
print(json.dumps(res, indent=1, default=int))
