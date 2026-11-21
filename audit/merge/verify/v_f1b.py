"""F1 second pass: same simple detector with an explicit label/verb filter, for a fairer count; then a fresh
seeded sample of the finder's foreign-flagged sentences for my own precision labels (handcheck/v_f1_prec.tsv)."""
import os, re
import pandas as pd
D = os.path.dirname(os.path.abspath(__file__))
v = pd.read_parquet(f"{D}/out/v_f1_hits.parquet")
rec = pd.read_parquet(f"{D}/out/rec.parquet").set_index("unique_id")
LAB = re.compile(r"^(?:Top|Best|Listed|Offers?|Performs?|Provides?|Facilities|Includes?|Has|Features?|Specialized|Specialised|Dedicated|"
                 r"Appears|Operates|Runs|Available|Also|Well|Awarded|Certified|Accredited|Empanelled|Registered|Located|Our|This|The)\b")
def keep(ms):
    out = [m for m in ms.split("; ") if not LAB.match(m) and not re.search(r"\b(Top|Best|Practo|Justdial|Network|Cashless)\b", m)]
    return "; ".join(out)
v["v2"] = v.v_foreign.map(keep)
v2 = v[v.v2 != ""]
n, ns = len(rec), 469498
print(f"V2 detector: sentences {len(v2)}/{ns} ({100*len(v2)/ns:.2f}%), records {v2.unique_id.nunique()}/{n} ({100*v2.unique_id.nunique()/n:.1f}%)")
fin = pd.read_parquet("/Users/karthikvattem/projects/datathon/audit/merge/out/sentences_flagged.parquet")
ff = fin[fin.has_foreign]
A, B = set(v2.unique_id), set(ff.unique_id)
print("records: finder", len(B), "mine", len(A), "both", len(A & B), "finder only", len(B - A), "mine only", len(A - B))
os.makedirs(f"{D}/handcheck", exist_ok=True)
smp = ff.sample(30, random_state=424242)
smp.assign(rec_name=smp.unique_id.map(rec.name), rec_city=smp.unique_id.map(rec.address_city))[
    ["unique_id", "rec_name", "rec_city", "foreign_names", "context", "field", "text"]].to_csv(f"{D}/handcheck/v_f1_prec.tsv", sep="\t", index=False)
mo = v2[~v2.unique_id.isin(B)].drop_duplicates("unique_id").sample(15, random_state=5)
pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 150)
print("-- mine-only records sample")
print(mo.assign(rn=mo.unique_id.map(rec.name))[["rn", "v2", "text"]].to_string())
