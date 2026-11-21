"""F4 independent re-derivation: single-specialty names (my own regexes) carrying acute-service claims.
Prints counts, overlap with the finder's q3 hits, and a seeded RECORD-level sample (handcheck/v_f4_records.tsv);
the finder's hand check sampled sentences, which over-weights records with many hit sentences."""
import os, re
import pandas as pd
D = os.path.dirname(os.path.abspath(__file__))
s = pd.read_parquet(f"{D}/out/sent.parquet")
rec = pd.read_parquet(f"{D}/out/rec.parquet").set_index("unique_id")
nm = rec.name.fillna("").str.lower()
CLS = [("eye", r"\b(?:eye|netra|nethra|netralaya|nethralaya|ophthalm\w*|retina|lasik|vision|drishti)\b"),
       ("dental", r"\b(?:dental|dentist\w*|teeth|tooth|orthodont\w*|smile)\b"),
       ("ivf", r"\b(?:ivf|fertility|test tube)\b"),
       ("lab", r"\b(?:lab|labs|laborator\w*|diagnostics?|pathology|imaging|scans?)\b"),
       ("skin", r"\b(?:skin|derma\w*|hair|cosmetic|aesthetics?)\b"),
       ("ent", r"\b(?:ent|ear|hearing)\b"),
       ("physio", r"\b(?:physio\w*|rehab\w*)\b")]
MULTI = r"\b(?:multi\w*|super\w*|general|medical college|nursing home|maternity|hospital and|and hospital|& hospital|hospitals?\s*&|medicity|institute of medical)\b"
cls = pd.Series(index=rec.index, dtype=object)
for c, rx in CLS:
    m = nm.str.contains(rx) & ~nm.str.contains(MULTI) & cls.isna()
    cls[m] = c
cls = cls.dropna()
print("single-specialty-named records", len(cls), cls.value_counts().to_dict())
SV = {"dialysis": r"\b(?:dialysis|haemodialysis|hemodialysis)\b", "cardiac_surgery": r"\b(?:cabg|bypass graft|open heart|cardiac surgery|heart surgery|valve replacement|cardiothoracic)\b",
      "nicu": r"\b(?:nicu|neonatal intensive)\b", "trauma": r"\b(?:polytrauma|trauma (?:care|centre|center|unit|surgery|services))\b",
      "c_section": r"\b(?:c-section|caesarean|cesarean|lscs)\b", "burn": r"\bburns? (?:care|unit|ward|centre|center|treatment|management)\b"}
ORG = re.compile(r"\b(?:ocular|eye|orbit\w*|cornea\w*|dental|tooth|teeth|maxillofacial|facial|jaw|oral)\b", re.I)
x = s[s.unique_id.isin(cls.index)].copy()
x["cls"] = x.unique_id.map(cls)
hit = pd.Series(False, index=x.index); svc = pd.Series("", index=x.index)
for k, rx in SV.items():
    m = x.text.str.contains(rx, case=False) & ~x.text.map(lambda t: bool(ORG.search(t)))
    if k == "c_section":
        m &= x.cls != "ivf"
    hit |= m; svc[m] = svc[m] + k + ","
h = x[hit].assign(svc=svc[hit])
print("records with acute claim", h.unique_id.nunique(), "of", len(cls), "; sentences", len(h))
print("by class", h.groupby("cls").unique_id.nunique().to_dict())
fh = pd.read_parquet("/Users/karthikvattem/projects/datathon/audit/merge/out/q3_hits.parquet")
A, B = set(h.unique_id), set(fh.unique_id)
print("finder records", len(B), "mine", len(A), "both", len(A & B))
k = fh.groupby("unique_id").size()
print("finder hit sentences per record: max", int(k.max()), "; top-5 records hold", int(k.nlargest(5).sum()), "of", int(k.sum()))
ids = pd.Series(sorted(B)).sample(20, random_state=77)
rows = []
for u in ids:
    g = fh[fh.unique_id == u]
    rows.append({"unique_id": u, "name": rec.name[u], "city": rec.address_city[u], "type": rec.facilityTypeId[u], "n": len(g),
                 "services": ",".join(sorted(set(",".join(g.services).split(",")))), "ex": " || ".join(g.text.head(2))[:240]})
pd.DataFrame(rows).to_csv(f"{D}/handcheck/v_f4_records.tsv", sep="\t", index=False)
