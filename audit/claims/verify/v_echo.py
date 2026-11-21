"""Claims-05: cross-field echo re-derived with all cross-field pairs, and with a stricter similarity
(token_sort_ratio) because token_set_ratio scores 100 whenever one item's tokens are a subset of the other's
('Dialysis' vs 'Dialysis unit with 8 beds'). Writes out/v_echo.json."""
import json
import pandas as pd
from rapidfuzz import fuzz, utils
m = pd.read_parquet("../out/mentions.parquet")
m = m[~m.nonoffer & ~m.foreign]
r = {}
for svc, ms in m.groupby("service"):
    tot = set_all = set_first = sort85 = subset_only = 0
    for uid, grp in ms.groupby("unique_id"):
        fs = grp.field.unique()
        if len(fs) < 2: continue
        tot += 1
        pairs = [(a, b) for i, f1 in enumerate(fs) for f2 in fs[i + 1:]
                 for a in grp[grp.field == f1].sentence for b in grp[grp.field == f2].sentence]
        ts = max(fuzz.token_set_ratio(a, b, processor=utils.default_process) for a, b in pairs)
        so = max(fuzz.token_sort_ratio(a, b, processor=utils.default_process) for a, b in pairs)
        a0 = grp[grp.field == fs[0]].sentence; b0 = grp[grp.field != fs[0]].sentence
        set_first += max(fuzz.token_set_ratio(a, b) for a in a0 for b in b0) >= 85
        set_all += ts >= 85; sort85 += so >= 85
        subset_only += ts >= 85 and so < 85
    r[svc] = dict(fac_2plus_fields=tot, finder_method_token_set_first_vs_rest=int(set_first), token_set_all_pairs=int(set_all),
                  token_sort_ratio85=int(sort85), token_set_hit_but_not_sort=int(subset_only))
json.dump(r, open("out/v_echo.json", "w"), indent=1)
print(json.dumps(r, indent=1))
