"""F6 re-derivation of quarantine totals and dialysis evidence tiers from the finder's sentence decisions (my own
aggregation code), then a split of tier C by what the 'merge evidence' actually is."""
import os, re
import pandas as pd
D = os.path.dirname(os.path.abspath(__file__))
M = "/Users/karthikvattem/projects/datathon/audit/merge/out"
s = pd.read_parquet(f"{M}/sentences_flagged.parquet").merge(pd.read_parquet(f"{M}/sentence_decisions.parquet"), on=["unique_id", "field", "idx"])
print("sentences", len(s), "quarantined", int(s.quarantine.sum()), "tagged", int(s.tag_only.sum()),
      "records with >=1 quarantined", s[s.quarantine].unique_id.nunique())
share = s.groupby("unique_id").quarantine.mean()
print("records with >=25% quarantined", int((share >= 0.25).sum()))
CRED = re.compile(r"\b(MBBS|MD|MS|DNB|BDS|MDS|DM|MCh|FRCS|degree|trained|fellowship|residency|graduat\w*|alumn\w*|studied|completed|worked|formerly|former|experience|qualified|consultant|professor)\b", re.I)
svc = {"dialysis": r"\b(?:dialysis|haemodialysis|hemodialysis)\b", "nicu": r"\b(?:nicu|neonatal intensive)\b",
       "cardiac_surgery": r"\b(?:cardiac surgery|heart surgery|bypass|cabg|open heart|cardiothoracic|ctvs)\b",
       "c_section": r"\b(?:c-section|caesarean|cesarean|lscs)\b", "mri": r"\bmri\b"}
g = s.groupby("unique_id")
has_q = g.quarantine.any()
has_t = g.tag_only.any()
# tag-only sentences whose text is a doctor credential (mine), or a relation/chain without a location claim
s["cred"] = s.tag_only & s.text.map(lambda t: bool(CRED.search(t)))
has_cred_only = g.apply(lambda x: x.tag_only.any() and not x.quarantine.any() and x[x.tag_only].cred.all())
for k, rx in svc.items():
    m = s[s.text.str.contains(rx, case=False, regex=True)]
    tier = {}
    for u, x in m.groupby("unique_id"):
        if ((x.self_names != "") & ~x.quarantine).any():
            tier[u] = "A"
        elif x.quarantine.all():
            tier[u] = "Q"
        elif has_q[u] or has_t[u]:
            tier[u] = "C"
        else:
            tier[u] = "B"
    t = pd.Series(tier)
    c = t[t == "C"].index
    cq = int(has_q[c].sum()); ct = len(c) - cq; cc = int(has_cred_only[c].sum())
    print(f"{k}: records {len(t)} tiers {t.value_counts().reindex(list('ABCQ')).fillna(0).astype(int).to_dict()} | "
          f"tier C with >=1 quarantined sentence {cq}, tag-only evidence {ct} (credential-only {cc})")
