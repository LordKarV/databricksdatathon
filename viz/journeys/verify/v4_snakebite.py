"""Independent check of story 4: anti-snake venom mentions by state, upper bounds, MDS sums, website mentions."""
import json
import re
from pathlib import Path

import pandas as pd
from statsmodels.stats.proportion import proportion_confint

R = Path("/Users/karthikvattem/projects/datathon")
cap = next(c for c in json.loads((R / "kb/pathways/capabilities.json").read_text())["capabilities"] if c["id"] == "anti_snake_venom")
print("evidence words:", cap["evidence_words"], cap["kb_status"])
c = pd.read_parquet(R / "derived/v1/claims.parquet", columns=["claim_id", "unique_id", "text", "attribution", "nonoffer"])
print("claims", len(c))
words = cap["evidence_words"]
pat = re.compile("|".join(r"\b" + re.escape(w) + r"\b" for w in words), re.I)
own = c[(c.attribution != "other_facility") & (c.nonoffer != True)]  # noqa: E712
hit = own[own.text.str.contains(pat, na=False)]
anyhit = c[c.text.str.contains(pat, na=False)]
print("facilities with own non-negated match:", hit.unique_id.nunique(), "| any claim match:", anyhit.unique_id.nunique())
print(hit[["unique_id", "text"]].to_string()[:3000])
loose = c[c.text.str.contains(r"snake|antivenom|anti-venom|anti venom|\bASV\b", case=False, na=False)]
print("loose snake/antivenom/ASV facilities in claims:", loose.unique_id.nunique())
f = pd.read_parquet(R / "derived/v1/facility_location.parquet", columns=["unique_id", "state_final"])
print("facility_location rows", len(f), f.unique_id.nunique())
print(f[f.unique_id.isin(hit.unique_id)].state_final.value_counts().to_dict())
for st in ["UTTAR PRADESH", "BIHAR"]:
    n = int((f.state_final == st).sum())
    k = int(f[f.state_final == st].unique_id.isin(hit.unique_id).sum())
    print(st, k, "of", n, "wilson upper", proportion_confint(k, n, method="wilson")[1], "exact upper",
          proportion_confint(k, n, method="beta")[1])
m = pd.read_csv(R / "viz/journeys/data/sources/mds_snakebite_table3.csv")
hb = m[m.burden_group == "higher"].est_deaths_2001_14_thousands.sum()
tot = m.est_deaths_2001_14_thousands.sum()
print("MDS higher", hb, "total", tot, "share", hb / tot, "per year higher", hb * 1000 / 14)
w = pd.read_parquet(R / "kb/web_evidence/out/web_service_summary.parquet")
print(w.columns.tolist())
ws = w[(w.service_id == "snakebite_antivenom") & (w.web_positive == True)]  # noqa: E712
print("web positive snakebite records", ws.unique_id.nunique())
print(f[f.unique_id.isin(ws.unique_id)].state_final.value_counts().head(10).to_dict())
