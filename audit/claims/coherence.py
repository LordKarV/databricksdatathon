"""Name/type coherence: single-specialty facility names (eye, dental, IVF, skin, ENT, physio, homoeo/ayurveda)
or clinic/dentist types that carry tertiary service claims. Such claims are the commonest sign of a merged record.
Writes out/coherence.json and out/coherence_examples.tsv."""
import json, re
import pandas as pd
g = pd.read_parquet("out/grades.parquet")
g = g[g.n_core > 0]
CATS = {
    "eye": r"\beye\b|netra|nethra|nayan|ophthal|vision|lasik|retina",
    "dental": r"dental|\bdent|teeth|tooth|smile|orthodont|implant",
    "ivf_fertility": r"\bivf\b|fertility|test tube",
    "skin_hair": r"\bskin\b|derma|hair|cosmetic|aesthetic",
    "ent": r"\bent\b|ear,? nose",
    "physio_rehab": r"physio|rehab",
    "ayush": r"homoeo|homeo|ayurved|unani|siddha|naturopath",
}
TERTIARY = ["dialysis", "cardiac_surgery", "nicu", "burns", "trauma", "icu", "mri", "csection"]
from common import load
names = load()[["unique_id", "name", "facilityTypeId"]]
out = {}
ex = []
for cat, p in CATS.items():
    ids = set(names[names.name.fillna("").str.contains(p, flags=re.I, regex=True)].unique_id)
    sub = g[g.unique_id.isin(ids)]
    out[cat] = dict(facilities_named=len(ids),
                    claiming_any_of_8=int(sub.unique_id.nunique()),
                    by_service={s: int((sub.service == s).sum()) for s in TERTIARY},
                    by_service_strong={s: int(((sub.service == s) & (sub.grade == "strong")).sum()) for s in TERTIARY})
    for r in sub[sub.service.isin(["dialysis", "cardiac_surgery", "burns", "nicu", "csection"])].itertuples():
        ex.append((cat, r.unique_id, r.name, r.service, r.grade))
for t in ["clinic", "dentist"]:
    ids = set(names[names.facilityTypeId == t].unique_id)
    sub = g[g.unique_id.isin(ids)]
    out["type_" + t] = dict(facilities=len(ids), claiming_any_of_8=int(sub.unique_id.nunique()),
                            by_service={s: int((sub.service == s).sum()) for s in TERTIARY},
                            by_service_strong={s: int(((sub.service == s) & (sub.grade == "strong")).sum()) for s in TERTIARY})
json.dump(out, open("out/coherence.json", "w"), indent=1)
pd.DataFrame(ex, columns=["cat", "unique_id", "name", "service", "grade"]).to_csv("out/coherence_examples.tsv", sep="\t", index=False)
print(json.dumps(out, indent=0))
