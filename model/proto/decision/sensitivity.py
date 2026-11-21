"""How much the WL top-1 depends on the policy knobs (assumptions, not fitted): D_s x0.5 / x2, road factor 1.0 / 1.6,
and the post-hoc T >= 2 candidate gate. Writes sensitivity.json: per setting, the number of the 40 queries whose top-1
changes vs the default and the top-1s with T < 2. Run: .venv/bin/python -B sensitivity.py
"""
import json
import sys

import numpy as np

sys.dont_write_bytecode = True
import decide  # noqa: E402


def top1s(fac, pairs, st_all, queries, dscale=1.0, road=1.3, gate=False):
    base = dict(decide.PROFILE)
    decide.PROFILE.update({k: (v[0] * dscale, *v[1:]) for k, v in base.items()})
    decide.ROAD = road
    out = {}
    try:
        for q in queries:
            idx = np.flatnonzero(pairs.service.to_numpy() == q["service"])
            fs = fac.set_index("unique_id").loc[pairs.unique_id.iloc[idx]].reset_index()
            d1, d2 = decide.distances(fs, q["lat"], q["lon"])
            _, cand, _, _ = decide.run_u_system(q, fs, st_all.iloc[idx].reset_index(drop=True), d1, d2, gate=gate)
            out[q["query_id"]] = (cand.unique_id.iloc[0], int(cand.T_own.iloc[0])) if len(cand) else (None, None)
    finally:
        decide.PROFILE.clear()
        decide.PROFILE.update(base)
        decide.ROAD = 1.3
    return out


def main():
    queries = json.load(open(decide.ROOT / "model/gold/queries.json"))
    fac, pairs = decide.load()
    st = decide.system_table(pairs, "WL")
    ref = top1s(fac, pairs, st, queries)
    res = {}
    for name, kw in [("default", {}), ("D_s_x0.5", dict(dscale=0.5)), ("D_s_x2", dict(dscale=2.0)),
                     ("road_1.0", dict(road=1.0)), ("road_1.6", dict(road=1.6)), ("post_hoc_T2_gate", dict(gate=True))]:
        t = top1s(fac, pairs, st, queries, **kw)
        res[name] = dict(top1_changed=sum(t[q][0] != ref[q][0] for q in ref),
                         top1_T_lt_2=sum(1 for q in t if t[q][1] is not None and t[q][1] < 2), n=len(ref))
    (decide.HERE / "sensitivity.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res))


if __name__ == "__main__":
    main()
