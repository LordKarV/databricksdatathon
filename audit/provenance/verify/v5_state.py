"""PROV-08: stated state vs PIN-directory state, independent normaliser (fuzzy to canonical names)."""
import duckdb, json, re, pandas as pd
from rapidfuzz import process, fuzz
R = "/Users/karthikvattem/projects/datathon/data/raw"
f = duckdb.sql(f"""select distinct * from '{R}/facilities.parquet' where regexp_full_match(unique_id,'[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}') and source='kie'""").df()
p = pd.read_parquet(f"{R}/india_post_pincode_directory.parquet"); p = p[p.statename != "NA"]
canon = sorted(p.statename.unique())
AL = {"ORISSA": "ODISHA", "PONDICHERRY": "PUDUCHERRY", "UP": "UTTAR PRADESH", "MP": "MADHYA PRADESH", "NCT OF DELHI": "DELHI",
      "NEW DELHI": "DELHI", "UTTARANCHAL": "UTTARAKHAND", "J&K": "JAMMU AND KASHMIR", "JAMMU & KASHMIR": "JAMMU AND KASHMIR"}
def ns(s):
    if not isinstance(s, str) or s.strip().lower() in ("", "null"): return None
    t = re.sub(r"\s+", " ", s.upper().replace(" STATE", "")).strip()
    t = t.split(",")[-1].strip()
    if t in AL: return AL[t]
    b = process.extractOne(t, canon, scorer=fuzz.ratio)
    return b[0] if b and b[1] >= 88 else None
f["st"] = f.address_stateOrRegion.map(ns)
z = f.address_zipOrPostcode.fillna("").str.replace(r"\s+", "", regex=True)
f["pin"] = pd.to_numeric(z.where(z.str.fullmatch(r"[1-9]\d{5}")), errors="coerce")
ps = p.groupby("pincode").statename.agg(set)
f["ps"] = f.pin.map(ps)
ok = f.st.notna() & f.ps.notna()
f["conf"] = [s not in q if k else None for s, q, k in zip(f.st, f.ps, ok)]
BEN = [{"ANDHRA PRADESH", "TELANGANA"}, {"CHANDIGARH", "PUNJAB", "HARYANA"}, {"DELHI", "UTTAR PRADESH", "HARYANA"}]
f["conf_real"] = [c and not any(s in g and (q & g) for g in BEN) if c is not None else None for c, s, q in zip(f.conf, f.st, f.ps)]
o = {"state_resolved": int(f.st.notna().sum()), "comparable": int(ok.sum()), "conflict_raw": int(f.conf.fillna(False).sum()),
     "conflict_after_benign": int(f.conf_real.fillna(False).sum())}
print(json.dumps(o, indent=1))
pd.set_option("display.width", 250)
print(f[f.conf_real.fillna(False).astype(bool)][["unique_id", "name", "address_city", "address_stateOrRegion", "pin", "ps"]].to_string())
json.dump(o, open("v5_state.json", "w"), indent=1)
