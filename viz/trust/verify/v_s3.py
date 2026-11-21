"""Independent recomputation of story 3 (strong evidence that is only wording).

Left panel (first grader): rebuilt here instead of read from v_grades.json. Strong (uid, service) pairs come from
audit/claims/out/grades.parquet (the first grader's frozen output); the prerequisite and core-mention regexes come
from audit/claims/services.py (they ARE the grader's definition, so they are imported, not re-typed); the loop,
JSON parsing and sentence split are mine. A strong pair is 'circular' when some prerequisite is met neither by a
sentence that is not a core mention of the service nor by a specialty tag.
Right panel (grader v2): derived/v1/grades.parquet, grade == strong; thin = corr_tags_only or every cited evidence
sentence has <= 3 words.
"""
import json
import re
import sys
from collections import Counter

import pandas as pd
from statsmodels.stats.proportion import proportion_confint

R = "/Users/karthikvattem/projects/datathon/"
sys.path.insert(0, R + "audit/claims")
from services import ICU_STRIP, SERVICES, norm_spec  # noqa: E402

ci = lambda k, n: tuple(round(100 * x, 1) for x in proportion_confint(k, n, method="wilson"))


def jl(s):
    if not isinstance(s, str) or not s.strip().startswith("["):
        return []
    try:
        v = json.loads(s)
    except ValueError:
        return []
    return [x.strip() for x in v if isinstance(x, str) and x.strip()]


raw = pd.read_parquet(R + "data/raw/facilities.parquet")
raw = raw[raw.unique_id.str.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}") & (raw.source == "kie")]
raw = raw.drop_duplicates("unique_id").set_index("unique_id")
g1 = pd.read_parquet(R + "audit/claims/out/grades.parquet")
st = g1[g1.grade == "strong"].drop_duplicates(["unique_id", "service"])
tot_k = tot_n = 0
for svc, d in SERVICES.items():
    ids = st[st.service == svc].unique_id
    k = 0
    for uid in ids:
        r = raw.loc[uid]
        ss = [s for f in ("procedure", "equipment", "capability") for s in jl(r[f])]
        desc = r.description if isinstance(r.description, str) and r.description.lower() != "null" else ""
        ss += [x.strip() for x in re.split(r"(?<=[.!?])\s+", desc) if x.strip()]
        spec = {norm_spec(x) for x in jl(r.specialties)}
        core = {s for s in ss if d["core"].search(ICU_STRIP.sub(" ", s) if svc == "icu" else s)}
        circ = any(not (any(prx.search(s) for s in ss if s not in core) or (spec & pset))
                   for prx, pset in d["prereqs"].values())
        k += circ
    tot_k += k
    tot_n += len(ids)
    print("S3 first-grader", svc, k, len(ids), ci(k, len(ids)) if len(ids) else "")
print("S3 first-grader all", tot_k, tot_n, round(100 * tot_k / tot_n, 1), ci(tot_k, tot_n))

g = pd.read_parquet(R + "derived/v1/grades.parquet")
s = g[g.grade == "strong"].copy()
ev = s.cite_evidence.map(json.loads)
s["short"] = ev.map(lambda L: bool(L) and all(len(e["text"].split()) <= 3 for e in L))
s["thin"] = s.short | s.corr_tags_only
print("S3 v2 all", int(s.thin.sum()), len(s), ci(int(s.thin.sum()), len(s)), "tag", int(s.corr_tags_only.sum()),
      "short", int(s.short.sum()), "both", int((s.short & s.corr_tags_only).sum()))
for svc, x in s.groupby("service"):
    print("S3 v2", svc, int(x.thin.sum()), len(x), ci(int(x.thin.sum()), len(x)))
print("S3 top short", Counter(L[0]["text"] for L in ev[s.short]).most_common(3))
# what does a corr_tags_only strong grade cite? (is 'tag only' really tag only?)
t = ev[s.corr_tags_only]
print("S3 tag-only strong grades citing >=1 sentence:", int(t.map(len).gt(0).sum()), "of", len(t))
