"""Claims-06, 08, 09, 10, 11 re-derivations with my own detectors (out/v_mentions.parquet) where possible.
Writes out/v_misc.json."""
import json, re
import pandas as pd
from v_common import load
df = load().drop_duplicates("unique_id"); vm = pd.read_parquet("out/v_mentions.parquet")
g = pd.read_parquet("../out/grades.parquet"); fm = pd.read_parquet("../out/mentions.parquet")
r = {}
norm = lambda s: re.sub(r"[^a-z]", "", s.lower())
tags = df.set_index("unique_id").specialties.map(lambda l: {norm(x) for x in l})
# 06: tag-only (my tag rules, my text detection; cardiac text widened with 'bypass surg')
CARD_T = lambda s: any(("cardiacsurg" in t) or ("cardiothoracic" in t) or ("cardiovascularsurg" in t) or ("ctvs" in t) for t in s)
card_text = set(vm[vm.service == "cardiac_surgery"].unique_id) | set(fm[(fm.service == "cardiac_surgery")].unique_id)
hit = set(tags[tags.map(CARD_T)].index)
r["cardiac_tag_hits"] = len(hit); r["cardiac_tag_only"] = len(hit - card_text)
BURN_T = lambda s: any("burn" in t for t in s)
hitb = set(tags[tags.map(BURN_T)].index); r["burn_tag_hits"] = len(hitb); r["burn_tag_only"] = len(hitb - set(vm[vm.service == "burns"].unique_id))
ICU_T = lambda s: any(t in {"criticalcaremedicine", "criticalcare", "intensivecareunit", "icuandcriticalcare"} for t in s)
hiti = set(tags[tags.map(ICU_T)].index); r["icu_tag_hits"] = len(hiti); r["icu_tag_only"] = len(hiti - set(vm[vm.service == "icu"].unique_id))
# 08: quantities from my own MRI / dialysis / NICU sentences
mri = vm[vm.service == "mri"]
T = mri.sentence.str.extract(r"(?i)(?<![\d.])(\d(?:\.\d)?)\s*-?\s*(?:t|tesla)\b")[0].astype(float)
ok = T.between(0.2, 7)
r["mri_tesla_facilities"] = int(mri[ok].unique_id.nunique()); r["mri_tesla_values"] = T[ok].value_counts().to_dict()
r["mri_facilities_mine"] = int(mri.unique_id.nunique())
dl = vm[vm.service == "dialysis"]
M = dl.sentence.str.extract(r"(?i)(?<![\d/x])(\d{1,3})\s+(?:[a-z-]+\s){0,3}?(?:machines|stations|chairs)\b|machines?\s*[:=-]\s*(\d{1,3})\b")
mach = M[0].fillna(M[1]).astype(float)
r["dialysis_machine_count_facilities"] = int(dl[mach.notna()].unique_id.nunique())
r["dialysis_machine_count_median"] = float(mach.dropna().groupby(dl[mach.notna()].unique_id).max().median())
# 09: inflation with my 8-service detector (emergency_any stands for trauma, csection_strict for C-section)
S8 = ["dialysis", "csection_strict", "nicu", "cardiac_surgery", "mri", "burns", "emergency_any", "icu"]
per = vm[vm.service.isin(S8)].groupby("unique_id").service.nunique()
d2 = df.set_index("unique_id").assign(n=per).fillna({"n": 0})
cap = pd.to_numeric(d2.capacity.where(~d2.capacity.isin(["null", "NULL"])), errors="coerce")
d2["size"] = pd.cut(cap, [-1, 0, 9, 49, 199, 1e9], labels=["0", "1-9", "10-49", "50-199", "200+"]).astype(object).where(cap.notna(), "unknown")
r["mean_claimed_by_type"] = {k: [round(v.mean(), 3), len(v)] for k, v in d2.groupby(d2.facilityTypeId.fillna("NA")).n if len(v) >= 20}
r["mean_claimed_by_size"] = {k: [round(v.mean(), 3), len(v)] for k, v in d2.groupby("size").n}
r["claim_6plus_by_type"] = d2[d2.n >= 6].facilityTypeId.value_counts().to_dict()
small = d2[(cap > 0) & (cap < 20)].index
r["small_lt20_n"] = len(small)
r["small_lt20_claims"] = {s: int(vm[(vm.service == s) & vm.unique_id.isin(small)].unique_id.nunique()) for s in ["cardiac_surgery", "mri", "nicu", "burns"]}
cl = set(d2[d2.facilityTypeId == "clinic"].index)
gm = g[(g.service == "mri") & (g.n_core > 0)].drop_duplicates("unique_id")
r["clinic_mri_finder"] = [int(gm.unique_id.isin(cl).sum()), int((gm.unique_id.isin(cl) & (gm.grade == "strong")).sum())]
# 10: trauma split with my detectors
r["trauma_explicit_fac_mine"] = int(vm[vm.service == "trauma_explicit"].unique_id.nunique())
r["emergency_any_fac_mine"] = int(vm[vm.service == "emergency_any"].unique_id.nunique())
r["finder_pre_ct_true"] = int(g[(g.service == "trauma") & (g.n_core > 0)].pre_ct.sum())
# 11: sentence-kind totals and flag precision samples
k = fm[["is_list", "staff", "directory"]]
r["kind_rows_any"] = int(k.any(axis=1).sum()); r["kind_rows_list"] = int(fm.is_list.sum()); r["kind_rows_staff"] = int(fm.staff.sum()); r["kind_rows_dir"] = int(fm.directory.sum())
r["kind_list_or_staff_or_dir_distinct_sentences"] = int(fm[k.any(axis=1)].drop_duplicates(["unique_id", "sentence"]).shape[0])
r["staff_sample"] = fm[fm.staff].drop_duplicates("sentence").sample(15, random_state=8).sentence.str[:120].tolist()
r["dir_sample"] = fm[fm.directory].drop_duplicates("sentence").sample(10, random_state=8).sentence.str[:120].tolist()
r["list_sample_short"] = fm[fm.is_list & (fm.sentence.str.len() < 90)].drop_duplicates("sentence").sample(10, random_state=8).sentence.tolist()
json.dump(r, open("out/v_misc.json", "w"), indent=1, default=str)
print(json.dumps(r, indent=1, default=str))
