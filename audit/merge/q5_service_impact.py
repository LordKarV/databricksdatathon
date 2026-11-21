"""Product impact of quarantine: for each challenge service, records that match it on any claim
sentence vs records whose ONLY matching sentences are quarantined (they would be false matches)."""
import pandas as pd
D = "/Users/karthikvattem/projects/datathon/audit/merge/out"
s = pd.read_parquet(f"{D}/sentences_flagged.parquet").merge(pd.read_parquet(f"{D}/sentence_decisions.parquet"), on=["unique_id", "field", "idx"])
SVC = {"dialysis": r"\b(?:dialysis|haemodialysis|hemodialysis)\b", "c_section": r"\b(?:c-section|caesarean|cesarean|lscs)\b",
       "nicu": r"\b(?:nicu|neonatal intensive)\b", "cardiac_surgery": r"\b(?:cardiac surgery|heart surgery|bypass|cabg|open heart|cardiothoracic|ctvs)\b",
       "mri": r"\bmri\b", "burn": r"\bburns? (?:care|unit|ward|treatment|centre|center)\b", "trauma": r"\b(?:trauma|polytrauma)\b",
       "emergency": r"\b(?:emergency|casualty)\b", "icu": r"\b(?:icu|intensive care)\b"}
rows = []
for k, rx in SVC.items():
    m = s[s.text.str.contains(rx, case=False, regex=True)]
    g = m.groupby("unique_id").quarantine.agg(["size", "sum"])
    rows.append((k, len(g), int((g["sum"] > 0).sum()), int((g["sum"] == g["size"]).sum()), len(m), int(m.quarantine.sum())))
t = pd.DataFrame(rows, columns=["service", "records_matching", "records_with_quarantined_match", "records_matching_ONLY_via_quarantined",
                                "sentences_matching", "sentences_quarantined"])
print(t.to_string(index=False))

# Evidence tiers for a service match (per record, best tier wins):
#   A = a matching sentence names this facility itself (self-anchored, not quarantined)
#   B = unanchored matching sentence, record has no merge evidence (no quarantined / tagged sentence)
#   C = unanchored matching sentence, record carries merge evidence elsewhere
#   Q = only quarantined matching sentences
rec_flag = s.groupby("unique_id").agg(q=("quarantine", "any"), t=("tag_only", "any"))
merged = rec_flag.q | rec_flag.t
print("\nself-anchored sentences (name the record's own facility):", int((s.self_names != "").sum()), "of", len(s))
print("records with merge evidence (>=1 quarantined or tagged sentence):", int(merged.sum()), "of", len(rec_flag))
rows = []
for k, rx in SVC.items():
    m = s[s.text.str.contains(rx, case=False, regex=True)].copy()
    m["tier"] = "C"
    m.loc[~m.unique_id.map(merged), "tier"] = "B"
    m.loc[(m.self_names != "") & ~m.quarantine, "tier"] = "A"
    m.loc[m.quarantine, "tier"] = "Q"
    best = m.groupby("unique_id").tier.min()  # 'A' < 'B' < 'C' < 'Q'
    vc = best.value_counts()
    rows.append((k, len(best)) + tuple(int(vc.get(x, 0)) for x in "ABCQ"))
print(pd.DataFrame(rows, columns=["service", "records", "tier_A_self_anchored", "tier_B_clean_record", "tier_C_merged_record", "tier_Q_only_quarantined"]).to_string(index=False))
