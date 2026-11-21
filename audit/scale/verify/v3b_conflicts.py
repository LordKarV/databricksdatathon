"""V3b: how many of the finder's 166 'conflicting text totals' carry time/future/unit leak words."""
import json, re, random
L = [json.loads(l) for l in open("/Users/karthikvattem/projects/datathon/audit/scale/q2_bed_multi_totals.jsonl")]
LEAK = re.compile(r"\b(soon|expand\w*|established|since|now|currently|grown|grew|inception|i\.c\.u|n\.i\.c\.u|future|upgrad\w*|ward|icu|went|became|year|in (?:19|20)\d\d)\b", re.I)
leak = [r for r in L if any(LEAK.search(c) for c in r["claims"])]
print(f"conflict rows: {len(L)}; with a time/future/unit word in a cited claim: {len(leak)}")
branch = [r for r in L if any(re.search(r"\b(branch|unit of|campus|another|sister|located in)\b", c, re.I) for c in r["claims"])]
print("with branch/campus wording:", len(branch))
random.seed(3)
for r in random.sample([x for x in L if x not in leak], 10):
    print(r["unique_id"][:8], r["cap"], r["text_totals"], [c[:100] for c in r["claims"][:4]])
