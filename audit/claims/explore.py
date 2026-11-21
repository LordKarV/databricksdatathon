"""Ad hoc: print random matching sentences for a regex, to tune detectors. Usage: explore.py REGEX [N] [seed]"""
import sys, re, random
from common import *
df = load()
rx = re.compile(sys.argv[1], re.I)
n = int(sys.argv[2]) if len(sys.argv) > 2 else 40
random.seed(int(sys.argv[3]) if len(sys.argv) > 3 else 0)
hits = []
for r in df.itertuples():
    for f in TEXT_FIELDS:
        for s in getattr(r, f + "_l"):
            if rx.search(s):
                hits.append((r.unique_id[:8], f[:4], s))
    if rx.search(r.description_s):
        hits.append((r.unique_id[:8], "desc", r.description_s[:300]))
print("sentences", len(hits), "facilities", len({h[0] for h in hits}))
for h in random.sample(hits, min(n, len(hits))):
    print(" | ".join(h))
