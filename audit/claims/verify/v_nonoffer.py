"""Claims-03 re-derivation with my own non-offer and hedge cue lists. Writes out/v_nonoffer.json."""
import json, re
import pandas as pd
from v_common import load
m = pd.read_parquet("../out/mentions.parquet"); g = pd.read_parquet("../out/grades.parquet")
MY = re.compile(r"\bnot (available|offered|provided|done|performed|present)|unavailable|\bdoes(n't| not) (have|offer|provide|perform)"
                r"|\bno [a-z]+ (facility|facilities|services?)\b|\brefer(red|s)? (out )?to\b|\breferrals? to\b|\btransferr?(ed)? to\b"
                r"|under construction|coming soon|upcoming|\bwill be\b|\bto be (started|installed|commissioned|set up|launched|opened)|\bplanned\b|\bproposed\b"
                r"|outsourc|third[- ]party|(through|via) (a )?partner|discontinued|no longer|(closed|shut) down|\bcamps?\b"
                r"|if applicable|implied|not specified|not confirmed|reportedly|presumabl|inferred", re.I)
m["mine"] = m.sentence.map(lambda s: bool(MY.search(s)))
r = dict(mention_rows=len(m), finder_nonoffer_rows=int(m.nonoffer.sum()), my_nonoffer_rows=int(m.mine.sum()),
         both=int((m.mine & m.nonoffer).sum()))
r["finder_by_service"] = m[m.nonoffer].service.value_counts().to_dict()
r["finder_mri_cues"] = {k: int(m[(m.service == "mri") & m.nonoffer][k].sum()) for k in ["negation", "referral", "future", "partner", "camp", "past", "hedge"]}
r["finder_mri_outsourc_word"] = int(m[(m.service == "mri") & m.nonoffer].sentence.str.contains("outsourc", case=False).sum())
r["non_offer_only_pairs"] = g[g.grade == "non_offer_only"].service.value_counts().to_dict()
r["my_only_sample"] = m[m.mine & ~m.nonoffer].drop_duplicates("sentence").head(15)[["unique_id", "service", "sentence"]].assign(unique_id=lambda d: d.unique_id.str[:8]).values.tolist()
r["finder_only_sample"] = m[~m.mine & m.nonoffer].drop_duplicates("sentence").head(10)[["unique_id", "service", "sentence"]].assign(unique_id=lambda d: d.unique_id.str[:8]).values.tolist()
r["finder_nonoffer_sample_seed5"] = m[m.nonoffer].drop_duplicates("sentence").sample(10, random_state=5)[["unique_id", "service", "sentence"]].assign(unique_id=lambda d: d.unique_id.str[:8]).values.tolist()
# hedges over all items, my own regex
df = load()
H = re.compile(r"if applicable|\(if any\)|implied|not specified|not confirmed|reportedly|as reported|presumabl|inferred|\bassumed\b|\bunclear\b|\bpossibly\b|\blikely\b|\bappears to\b", re.I)
tot = hits = 0; fac = set()
for x in df.drop_duplicates("unique_id").itertuples():
    for f in ["procedure", "equipment", "capability"]:
        for s in getattr(x, f):
            tot += 1
            if H.search(s): hits += 1; fac.add(x.unique_id)
r["hedge_items"] = hits; r["hedge_items_denominator"] = tot; r["hedge_facilities"] = len(fac)
r["hedge_in_mentions_finder"] = int(m.hedge.sum())
json.dump(r, open("out/v_nonoffer.json", "w"), indent=1)
print(json.dumps(r, indent=1))
