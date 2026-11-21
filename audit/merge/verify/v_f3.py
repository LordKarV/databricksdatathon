"""F3 independent re-derivation: places named in claims vs the record's own location.
Own location = union of {state field, PIN-directory state of the record PIN} and {city field, PIN-directory district}.
Place lexicon = PIN-directory district and state names only (title-case occurrences, length >= 5), plus a few
renamed cities. other_state = a state name, or a district that exists only in states outside the own set."""
import os, re
from collections import defaultdict
import pandas as pd
D = os.path.dirname(os.path.abspath(__file__))
s = pd.read_parquet(f"{D}/out/sent.parquet")
rec = pd.read_parquet(f"{D}/out/rec.parquet").set_index("unique_id")
pin = pd.read_parquet("/Users/karthikvattem/projects/datathon/data/raw/india_post_pincode_directory.parquet", columns=["pincode", "district", "statename"])
n_ = lambda x: re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", str(x or "").lower().replace("&", " and "))).strip()
SA = {"orissa": "odisha", "pondicherry": "puducherry", "uttaranchal": "uttarakhand", "chattisgarh": "chhattisgarh",
      "jammu kashmir": "jammu and kashmir", "nct of delhi": "delhi", "new delhi": "delhi", "tamilnadu": "tamil nadu"}
ns = lambda x: SA.get(n_(x), n_(x))
pin["d"], pin["s"] = pin.district.map(n_), pin.statename.map(ns)
pin = pin[pin.s != "na"]
d2s = defaultdict(set)
for d, st in pin[["d", "s"]].drop_duplicates().itertuples(index=False):
    d2s[d].add(st)
    if d.endswith(" urban") or d.endswith(" rural"):
        d2s[d.rsplit(" ", 1)[0]].add(st)
for old, new in {"bangalore": "bengaluru", "bombay": "mumbai", "madras": "chennai", "calcutta": "kolkata", "gurgaon": "gurugram",
                 "trivandrum": "thiruvananthapuram", "noida": "gautam buddha nagar", "mysore": "mysuru", "poona": "pune"}.items():
    if new in d2s:
        d2s[old] |= d2s[new]
states = set(pin.s)
AMB = {"gandhi", "krishna", "anand", "sagar", "salem", "central", "north", "south", "east", "west", "nagar", "kalyan", "khanna",
       "hassan", "korea", "narmada", "ganga", "mahe", "raja", "dhar", "puri", "banka", "rohini", "kalyani", "shree", "aravalli"}
lex = {k: v for k, v in d2s.items() if len(k) >= 5 and k not in AMB}
for st in states:
    lex.setdefault(st, set()).add(st)
pm = pin.groupby("pincode").agg(d=("d", "first"), s=("s", "first"))
zp = pd.to_numeric(rec.address_zipOrPostcode.astype(str).str.extract(r"(\d{6})")[0], errors="coerce")
own_s = {}; own_d = {}
for u, z, st, city in zip(rec.index, zp, rec.address_stateOrRegion, rec.address_city):
    S, Dd = {ns(st)} & states, {n_(city)}
    if z == z and z in pm.index:
        S.add(pm.s[z]); Dd.add(pm.d[z])
    own_s[u], own_d[u] = S, Dd
pat = re.compile(r"\b(" + "|".join(sorted((r"\s+".join(w.capitalize() for w in k.split()) for k in lex), key=len, reverse=True)) + r")\b")
cand = s[s.text.str.contains(pat, regex=True)]
os_, od_ = [], []
for u, t in zip(cand.unique_id, cand.text):
    S, Dd = own_s[u], own_d[u]
    o1, o2 = [], []
    for m in pat.finditer(t):
        p = n_(m.group(1))
        if p in Dd or not S:
            continue
        sts = lex[p]
        if not (sts & S):
            o1.append(p)
        elif p not in states:
            o2.append(p)
    os_.append("; ".join(o1)); od_.append("; ".join(o2))
cand = cand.assign(v_os=os_, v_od=od_)
N, NS = len(rec), len(s)
for c in ("v_os", "v_od"):
    g = cand[cand[c] != ""]
    print(f"{c}: sentences {len(g)}/{NS} ({100*len(g)/NS:.2f}%), records {g.unique_id.nunique()}/{N} ({100*g.unique_id.nunique()/N:.1f}%)")
print("records with no usable own state (excluded from flags):", sum(1 for v in own_s.values() if not v))
fin = pd.read_parquet("/Users/karthikvattem/projects/datathon/audit/merge/out/sentences_flagged.parquet")
for mine, theirs in (("v_os", "has_other_state"), ("v_od", "has_other_district")):
    A = set(cand[cand[mine] != ""].unique_id); B = set(fin[fin[theirs]].unique_id)
    print(f"{theirs}: finder {len(B)} mine {len(A)} both {len(A & B)}")
cand.to_parquet(f"{D}/out/v_f3_hits.parquet")
# PIN-vs-state-field conflict: how often the record's own two location sources disagree
conf = sum(1 for u, z, st in zip(rec.index, zp, rec.address_stateOrRegion) if z == z and z in pm.index and ns(st) in states and pm.s[z] != ns(st))
print("records whose PIN-directory state differs from their state field:", conf, "of", N)
