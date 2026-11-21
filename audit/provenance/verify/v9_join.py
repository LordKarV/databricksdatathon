"""PROV-17: PIN district -> NFHS join, exact rate and facility-weighted reach using the finder's crosswalk (my own join code)."""
import duckdb, json, re, pandas as pd
R = "/Users/karthikvattem/projects/datathon/data/raw"
p = pd.read_parquet(f"{R}/india_post_pincode_directory.parquet"); n = pd.read_parquet(f"{R}/nfhs_5_district_health_indicators.parquet")
u = lambda s: re.sub(r"\s+", " ", str(s).replace("&", " AND ")).strip().upper()
SF = {"MAHARASTRA": "MAHARASHTRA", "NCT OF DELHI": "DELHI", "DADRA AND NAGAR HAVELI AND DAMAN AND DIU": "THE DADRA AND NAGAR HAVELI AND DAMAN AND DIU"}
nk = {(SF.get(u(s), u(s)), u(d)) for s, d in zip(n.state_ut, n.district_name)}
pairs = p[(p.district != "NA") & (p.statename != "NA")][["statename", "district"]].drop_duplicates()
o = {"pin_pairs": len(pairs), "exact": int(sum((u(s), u(d)) in nk for s, d in zip(pairs.statename, pairs.district)))}
cw = pd.read_csv("/Users/karthikvattem/projects/datathon/audit/provenance/nfhs_district_crosswalk.csv")
o["cw_rows"] = len(cw); o["cw_tiers"] = cw.tier.value_counts().to_dict()
# validate crosswalk targets exist in NFHS
tgt = cw.dropna(subset=["nfhs_district"])
o["cw_targets_exist"] = int(sum((SF.get(u(s), u(s)), u(d)) in nk for s, d in zip(tgt.nfhs_state, tgt.nfhs_district)))
o["cw_matched"] = len(tgt)
# cross-state mappings (should be 0)
o["cw_cross_state"] = int(sum(SF.get(u(a), u(a)) != u(b) for a, b in zip(tgt.nfhs_state, tgt.statename)))
f = duckdb.sql(f"""select distinct * from '{R}/facilities.parquet' where regexp_full_match(unique_id,'[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}') and source='kie'""").df()
z = f.address_zipOrPostcode.fillna("").str.replace(r"\s+", "", regex=True)
pin = pd.to_numeric(z.where(z.str.fullmatch(r"[1-9]\d{5}")), errors="coerce")
pd_ = p[p.district != "NA"][["pincode", "statename", "district"]].drop_duplicates().merge(cw, on=["statename", "district"], how="left")
reach = set(pd_[pd_.nfhs_district.notna()].pincode)
anyd = set(pd_.pincode)
o["fac_reach"] = int(pin.isin(reach).sum()); o["fac_pin_with_district"] = int(pin.isin(anyd).sum()); o["fac"] = len(f)
# exact-only facility reach (no crosswalk)
ex = p[p.district != "NA"][["pincode", "statename", "district"]].drop_duplicates()
ex = set(ex[[(u(s), u(d)) in nk for s, d in zip(ex.statename, ex.district)]].pincode)
o["fac_reach_exact_only"] = int(pin.isin(ex).sum())
# spot-check renames / splits
o["spot"] = cw[cw.district.isin(["GURUGRAM", "KOREA", "NTR", "PRAYAGRAJ", "HOWRAH", "SAITUAL", "MALERKOTLA"])].values.tolist()
o["unmatched"] = cw[cw.tier == "unmatched"].values.tolist()
print(json.dumps(o, indent=1, default=str)); json.dump(o, open("v9_join.json", "w"), indent=1, default=str)
