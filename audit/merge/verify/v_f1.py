"""F1 independent re-derivation: a deliberately simpler foreign-facility-name detector, then agreement with
the finder's flags. Foreign = a capitalised facility-name phrase none of whose distinctive tokens matches a
distinctive token of the record's own name (exact, or rapidfuzz ratio >= 85)."""
import os, re
import pandas as pd
from rapidfuzz import fuzz
D = os.path.dirname(os.path.abspath(__file__))
s = pd.read_parquet(f"{D}/out/sent.parquet")
rec = pd.read_parquet(f"{D}/out/rec.parquet").set_index("unique_id")
print("exact duplicate sentences within a record:", int(s.duplicated(["unique_id", "text"]).sum()), "of", len(s))
KW = r"(?:Hospitals?|Clinics?|Nursing Home|Medical College|Medical Cent(?:re|er)|Institute|Health Cent(?:re|er)|Healthcare|Polyclinic|Dispensary|AIIMS)"
W = r"[A-Z][A-Za-z.'&-]*"
MENT = re.compile(rf"((?:{W}\s+(?:of\s+|and\s+|&\s+)?){{1,5}}{KW})")
GEN = set("""hospital hospitals clinic clinics nursing home medical college centre center institute health healthcare
polyclinic dispensary multi multispeciality multispecialty super speciality specialty superspeciality care the of and
government govt district general civil community primary sub divisional maternity eye dental heart cancer kidney
children women research sciences science trust charitable memorial mission city new dr pvt ltd private limited
sri shri shree st saint hi tech advanced diagnostic diagnostics ent ortho orthopaedic orthopedic neuro cardiac
surgical skin ivf fertility day referral railway esi esic national state rural urban teaching tertiary
the a an at in this our its with""".split())
def toks(x):
    return [t for t in re.split(r"[^a-z0-9]+", (x or "").lower()) if t]
def dist(x):
    return [t for t in toks(x) if t not in GEN and len(t) > 2 and not t.isdigit()]
own = {u: dist(n) for u, n in rec.name.items()}
def is_foreign(m, u):
    md = dist(m)
    if not md:
        return False
    od = own[u]
    for t in md:
        for o in od:
            if t == o or (len(t) > 3 and len(o) > 3 and fuzz.ratio(t, o) >= 85):
                return False
    # whole-string fallback, catches 'Sk' vs 'S K'
    if od and fuzz.ratio("".join(md), "".join(od)) >= 85:
        return False
    return True
fm, hits = [], []
cand = s[s.text.str.contains(KW, regex=True)]
for u, t in zip(cand.unique_id, cand.text):
    ms = [m.group(1) for m in MENT.finditer(t)]
    f = [m for m in ms if is_foreign(m, u)]
    fm.append("; ".join(f))
cand = cand.assign(v_foreign=fm)
v = cand[cand.v_foreign != ""]
n, ns = rec.shape[0], len(s)
print(f"V detector: sentences {len(v)}/{ns} ({100*len(v)/ns:.2f}%), records {v.unique_id.nunique()}/{n} ({100*v.unique_id.nunique()/n:.1f}%)")
print("by field", v.field.value_counts().to_dict())
fin = pd.read_parquet("/Users/karthikvattem/projects/datathon/audit/merge/out/sentences_flagged.parquet")
ff = fin[fin.has_foreign]
A, B = set(v.unique_id), set(ff.unique_id)
print("records: finder", len(B), "mine", len(A), "both", len(A & B), "finder only", len(B - A), "mine only", len(A - B))
key = lambda d: set(zip(d.unique_id, d.field, d.idx))
ka, kb = key(v), key(ff)
print("sentences: finder", len(kb), "mine", len(ka), "both", len(ka & kb), "finder only", len(kb - ka), "mine only", len(ka - kb))
v.to_parquet(f"{D}/out/v_f1_hits.parquet")
fo = ff[[k not in ka for k in zip(ff.unique_id, ff.field, ff.idx)]]
mo = v[[k not in kb for k in zip(v.unique_id, v.field, v.idx)]]
pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 140)
print("\n-- finder-only sample (20)")
x = fo.sample(20, random_state=11)
print(x.assign(rn=x.unique_id.map(rec.name))[["rn", "foreign_names", "context", "text"]].to_string())
print("\n-- mine-only sample (20)")
x = mo.sample(20, random_state=11)
print(x.assign(rn=x.unique_id.map(rec.name))[["rn", "v_foreign", "text"]].to_string())
