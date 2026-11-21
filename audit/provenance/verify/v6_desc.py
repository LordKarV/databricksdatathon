"""PROV-10/11: description length, shared texts, boilerplate, label-only, meta-text, numeric agreement."""
import duckdb, json, re, pandas as pd
R = "/Users/karthikvattem/projects/datathon/data/raw"
f = duckdb.sql(f"""select distinct * from '{R}/facilities.parquet' where regexp_full_match(unique_id,'[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}') and source='kie'""").df()
d = f.description.fillna("")
w = d.str.split().str.len()
o = {"n": len(f), "desc_null_like": int(d.str.strip().str.lower().isin(["", "null"]).sum()),
     "median_words": float(w.median()), "le3_words": int((w <= 3).sum())}
vc = d.value_counts()
o["records_sharing_exact"] = int(d.duplicated(keep=False).sum()); o["distinct_shared"] = int((vc > 1).sum())
o["records_sharing_case_ws_norm"] = int(d.str.lower().str.replace(r"\W+", " ", regex=True).str.strip().duplicated(keep=False).sum())
cardiac = d.str.contains("exceptional cardiac care", case=False)
o["cardiac_exact_text"] = int((d == "Providing exceptional cardiac care to the community").sum())
o["cardiac_contains"] = int(cardiac.sum())
o["cardiac_variants"] = d[cardiac].value_counts().to_dict()
o["cardiac_names"] = f[cardiac].name.tolist()
o["top_shared"] = vc.head(6).to_dict()
meta = d.str.contains(r"\b(?:is listed|listed (?:on|in|among|as|under)|practo|justdial|this page|the page|webpage|directory|listing)\b", case=False, regex=True)
o["meta_like_any_words"] = int((meta & (w > 3)).sum())
# numeric: beds in description vs capacity field
num = lambda s: pd.to_numeric(s.where(~s.isin(["null", ""])), errors="coerce")
cap = num(f.capacity.fillna("")); ye = num(f.yearEstablished.fillna(""))
bm = d.str.extract(r"(\d{1,4})\s*-?\s*(?:bedded|beds?)\b", flags=re.I)[0].astype(float)
o["desc_beds"] = int(bm.notna().sum()); o["desc_beds_and_capacity"] = int((bm.notna() & cap.notna()).sum())
o["desc_beds_eq_capacity"] = int((bm.notna() & (bm == cap)).sum())
o["capacity_present_total"] = int(cap.notna().sum())
o["capacity_present_given_desc_beds_pct"] = round(100 * (bm.notna() & cap.notna()).sum() / bm.notna().sum(), 1)
o["capacity_present_given_no_desc_beds_pct"] = round(100 * (bm.isna() & cap.notna()).sum() / bm.isna().sum(), 1)
ym = d.str.extract(r"(?:established|founded|since|estd\.?|started)\D{0,20}?((?:19|20)\d{2})", flags=re.I)[0].astype(float)
o["desc_year"] = int(ym.notna().sum()); o["desc_year_and_field"] = int((ym.notna() & ye.notna()).sum()); o["desc_year_eq_field"] = int((ym == ye).sum())
o["year_present_given_desc_year_pct"] = round(100 * (ym.notna() & ye.notna()).sum() / ym.notna().sum(), 1)
o["year_present_overall_pct"] = round(100 * ye.notna().mean(), 1)
print(json.dumps(o, indent=1, default=str)); json.dump(o, open("v6_desc.json", "w"), indent=1, default=str)
