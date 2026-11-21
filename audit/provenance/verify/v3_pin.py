"""Independent PIN-directory quality checks (PROV-12, 13, 14) and coord-vs-PIN distance (PROV-06)."""
import duckdb, json, numpy as np, pandas as pd, re
R = "/Users/karthikvattem/projects/datathon/data/raw"
p = pd.read_parquet(f"{R}/india_post_pincode_directory.parquet")
o = {"rows": len(p), "pins": int(p.pincode.nunique())}
la = pd.to_numeric(p.latitude, errors="coerce"); lo = pd.to_numeric(p.longitude, errors="coerce")
o["lat_NA"] = int((p.latitude.str.strip() == "NA").sum())
o["lat_nonnum_nonNA"] = int((la.isna() & (p.latitude.str.strip() != "NA")).sum())
o["nonnum_examples"] = p.latitude[la.isna() & (p.latitude.str.strip() != "NA")].head(6).tolist()
num = la.notna() & lo.notna()
inb = num & la.between(6, 37.6) & lo.between(68, 97.5)
sw = num & ~inb & lo.between(6, 37.6) & la.between(68, 97.5)
o["in_box"] = int(inb.sum()); o["swapped"] = int(sw.sum()); o["outside_not_swapped"] = int((num & ~inb & ~sw).sum())
o["zero"] = int((num & ((la == 0) | (lo == 0))).sum())
# admin
o["district_NA"] = int((p.district == "NA").sum()); o["state_NA"] = int((p.statename == "NA").sum())
nn = p[(p.district != "NA") & (p.statename != "NA")]
o["pins_only_NA"] = int(p.pincode.nunique() - nn.pincode.nunique())
g = nn.groupby("pincode")
o["pins_multi_district"] = int((g.district.nunique() > 1).sum()); o["pins_multi_state"] = int((g.statename.nunique() > 1).sum())
# circle vs state, my own mapping of circles to plausible states
circ = nn.circlename.str.upper().str.replace(" CIRCLE", "", regex=False).str.strip()
ALLOW = {"NORTH EASTERN": {"ARUNACHAL PRADESH","MANIPUR","MEGHALAYA","MIZORAM","NAGALAND","TRIPURA"},
         "WEST BENGAL": {"WEST BENGAL","SIKKIM","ANDAMAN AND NICOBAR ISLANDS"}, "KERALA": {"KERALA","LAKSHADWEEP","PUDUCHERRY"},
         "TAMILNADU": {"TAMIL NADU","PUDUCHERRY"}, "ANDHRA PRADESH": {"ANDHRA PRADESH","PUDUCHERRY"},
         "MAHARASHTRA": {"MAHARASHTRA","GOA"}, "GUJARAT": {"GUJARAT","THE DADRA AND NAGAR HAVELI AND DAMAN AND DIU"},
         "PUNJAB": {"PUNJAB","CHANDIGARH"}, "JAMMU KASHMIR": {"JAMMU AND KASHMIR","LADAKH"}, "ASSAM": {"ASSAM"},
         "CHATTISGARH": {"CHHATTISGARH"}, "APS": set()}
print(sorted(circ.unique()))
mis = nn[[s not in ALLOW.get(c, {c}) for c, s in zip(circ, nn.statename)]]
o["circle_mismatch_rows"] = len(mis); o["circle_mismatch_pins"] = int(mis.pincode.nunique())
o["circle_mismatch_pairs"] = {f"{a} -> {b}": int(n) for (a, b), n in mis.assign(c=circ[mis.index]).groupby(["c","statename"]).size().items()}
o["pin_799001"] = p[p.pincode == 799001][["officename","district","statename","circlename"]].values.tolist()
o["pin_504346"] = p[p.pincode == 504346][["officename","district","statename","circlename"]].values.tolist()
# centroid: my method = median of in-box (swap-fixed) offices, then drop offices > 50 km and re-median
flat = np.where(sw, lo, np.where(inb, la, np.nan)); flon = np.where(sw, la, np.where(inb, lo, np.nan))
c = p.assign(a=flat, b=flon).dropna(subset=["a"])
def hav(a1, b1, a2, b2):
    r = np.pi/180; h = np.sin((a2-a1)*r/2)**2 + np.cos(a1*r)*np.cos(a2*r)*np.sin((b2-b1)*r/2)**2
    return 12742*np.arcsin(np.sqrt(h))
m1 = c.groupby("pincode")[["a","b"]].median()
c = c.join(m1, on="pincode", suffixes=("", "_m")); c["d"] = hav(c.a, c.b, c.a_m, c.b_m)
o["pins_with_coord"] = int(c.pincode.nunique()); o["pins_no_coord"] = o["pins"] - o["pins_with_coord"]
o["office_rows_gt200"] = int((c.d > 200).sum()); o["pins_any_office_gt50"] = int((c.groupby("pincode").d.max() > 50).sum())
cen = c[c.d <= 50].groupby("pincode")[["a","b"]].median()
# facilities
F = f"{R}/facilities.parquet"
f = duckdb.sql(f"""select distinct * from '{F}' where regexp_full_match(unique_id,'[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}') and source='kie'""").df()
z = f.address_zipOrPostcode.fillna("").str.replace(r"\s+", "", regex=True)
valid = z.str.fullmatch(r"[1-9]\d{5}")
o["fac"] = len(f); o["fac_valid_pin"] = int(valid.sum())
o["fac_pin_space_fixed"] = int((valid & f.address_zipOrPostcode.str.contains(r"\s", na=False)).sum())
pin = pd.to_numeric(z.where(valid), errors="coerce")
known = set(p.pincode)
o["fac_pin_in_dir"] = int(pin.isin(known).sum()); o["fac_pin_not_in_dir"] = int((pin.notna() & ~pin.isin(known)).sum())
o["fac_raw_invalid_values_top"] = f.address_zipOrPostcode[~valid].value_counts().head(8).to_dict()
o["fac_distinct_pins"] = int(pin.nunique())
fc = f.assign(pin=pin).dropna(subset=["pin","latitude"]).join(cen, on="pin", how="inner")
fc["d"] = hav(fc.latitude, fc.longitude, fc.a, fc.b)
o["fac_compared"] = len(fc); o["fac_gt50"] = int((fc.d > 50).sum()); o["fac_gt200"] = int((fc.d > 200).sum())
o["fac_d_quant"] = fc.d.quantile([.5,.9]).round(1).to_dict()
fc[["unique_id","name","address_city","address_stateOrRegion","pin","latitude","longitude","a","b","d"]].to_parquet("v3_fac_pin_km.parquet")
print(json.dumps(o, indent=1, default=str)); json.dump(o, open("v3_pin.json","w"), indent=1, default=str)
