"""Draw the fixed hand-check samples (seeded) into handcheck/*.tsv for manual labelling."""
import os, sys
import pandas as pd
D = os.path.dirname(os.path.abspath(__file__))
s = pd.read_parquet(f"{D}/out/sentences_flagged.parquet")
r = pd.read_parquet(f"{D}/out/records_flagged.parquet").set_index("unique_id")
os.makedirs(f"{D}/handcheck", exist_ok=True)
def ctx(df):
    return df.assign(rec_name=df.unique_id.map(r.name), rec_city=df.unique_id.map(r.address_city),
                     rec_state=df.unique_id.map(r.address_stateOrRegion))
which = sys.argv[1]
if which == "q1_holdout":
    out = ctx(s[s.has_foreign].sample(30, random_state=7777))[["unique_id", "field", "idx", "rec_name", "rec_city", "foreign_names", "context", "text"]]
elif which == "q1_precision":
    out = ctx(s[s.has_foreign].sample(30, random_state=2026))[["unique_id", "field", "idx", "rec_name", "rec_city", "foreign_names", "context", "text"]]
elif which == "q2_holdout":
    out = ctx(s[s.has_other_state].sample(30, random_state=7777))[["unique_id", "field", "idx", "rec_name", "rec_city", "rec_state", "places_other_state", "text"]]
elif which == "q2_precision":
    out = ctx(s[s.has_other_state].sample(30, random_state=2026))[["unique_id", "field", "idx", "rec_name", "rec_city", "rec_state", "places_other_state", "text"]]
elif which == "q2d_precision":
    out = ctx(s[s.has_other_district].sample(30, random_state=2026))[["unique_id", "field", "idx", "rec_name", "rec_city", "rec_state", "places_other_district", "text"]]
elif which == "recall_records":
    ids = r.sample(30, random_state=2026).index
    out = ctx(s[s.unique_id.isin(ids)])[["unique_id", "field", "idx", "rec_name", "rec_city", "has_foreign", "has_sibling", "has_other_state", "text"]]
if which not in ("q1_recall_strata", "q5"):
    out.to_csv(f"{D}/handcheck/{which}.tsv", sep="\t", index=False)
    print(len(out))

if which == "q1_recall_strata":
    # Unflagged sentences, split by how likely they are to hide a facility name
    un = s[~s.has_foreign & ~s.has_sibling]
    has_m = (un.self_names != "") | (un.other_mentions != "")
    cap_after_prep = un.text.str.contains(r"\b(?:at|from|with|of|to|by|under)\s+(?:the\s+)?[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z.]+)+")
    u1, u2 = un[has_m], un[~has_m & cap_after_prep]
    print("unflagged", len(un), "U1 with self/generic mention", len(u1), "U2 cap phrase after preposition", len(u2), "U3 rest", len(un) - len(u1) - len(u2))
    ctx(u1.sample(30, random_state=2026))[["unique_id", "rec_name", "rec_city", "self_names", "other_mentions", "text"]].to_csv(f"{D}/handcheck/q1_recall_U1.tsv", sep="\t", index=False)
    ctx(u2.sample(30, random_state=2026))[["unique_id", "rec_name", "rec_city", "text"]].to_csv(f"{D}/handcheck/q1_recall_U2.tsv", sep="\t", index=False)
if which == "q5":
    dec = pd.read_parquet(f"{D}/out/sentence_decisions.parquet")
    x = s.merge(dec, on=["unique_id", "field", "idx"])
    hard = x[x.unique_id.isin(x[x.quarantine].unique_id)]
    a = hard[hard.quarantine].sample(10, random_state=2026).assign(decision="quarantine")
    b = hard[~hard.quarantine].sample(10, random_state=2026).assign(decision="keep" )
    out = ctx(pd.concat([a, b]))[["unique_id", "rec_name", "rec_city", "decision", "tag_only", "foreign_names", "places_other_state", "places_other_district", "text"]]
    out.to_csv(f"{D}/handcheck/q5_decisions.tsv", sep="\t", index=False)
