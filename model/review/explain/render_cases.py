"""Render the six reviewed recommendations with the prototype's own card() and dump the hidden score breakdown.

Reads only (decision/fusion prototype tables, raw parquet). Writes cases.txt and cases.json next to this file.
Run: /Users/karthikvattem/projects/datathon/.venv/bin/python -B render_cases.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
ROOT = Path("/Users/karthikvattem/projects/datathon")
HERE = ROOT / "model/review/explain"
sys.path.insert(0, str(ROOT / "model/proto/decision"))
from decide import FUS, PROFILE, answer_u, distances, load, run_u_system, system_table, phone_note  # noqa: E402
from cards import card  # noqa: E402
from resolve import Resolver  # noqa: E402

# (case id, kind, query, unique_id prefix)
CASES = [
    ("S1", "strong", dict(query_id="demo_panipat", service="dialysis", location_text="Panipat district, Haryana", urgency="scheduled"), "acde9be7"),
    ("S2", "strong", "q35", "a52cd60a"),
    ("U1", "uncertain", "q01", "830706f4"),
    ("U2", "uncertain", "q12", "05e535b3"),
    ("C1", "contaminated", dict(query_id="demo_nagpur", service="dialysis", location_text="Nagpur", urgency="scheduled"), "3ac5ae50"),
    ("C2", "contaminated", "q29", "7e420f3f"),
]


def main():
    fac, pairs = load()
    st_all = system_table(pairs, "WL")
    R = Resolver()
    queries = {q["query_id"]: q for q in json.load(open(ROOT / "model/gold/queries.json"))}
    ctx = dict(atoms=pd.read_parquet(FUS / "atoms.parquet").set_index("atom_id"),
               ff=pd.read_parquet(FUS / "features_facility.parquet").set_index("unique_id"),
               br=pd.read_parquet(FUS / "band_record.parquet"),
               fp=pd.read_parquet(FUS / "features_pairs.parquet").set_index(["unique_id", "service"]),
               ps=pd.read_parquet(FUS / "pair_scores.parquet").set_index(["unique_id", "service"]),
               raw=pd.read_parquet(ROOT / "data/raw/facilities.parquet", columns=["unique_id", "source_urls"]).drop_duplicates("unique_id").set_index("unique_id"),
               pnote=phone_note)
    pc = pd.read_parquet(FUS / "pair_contributions.parquet")
    out_txt, out_json = [], []
    for cid, kind, q, focus in CASES:
        q = dict(queries[q]) if isinstance(q, str) else dict(q)
        res = R.resolve_place(q["location_text"])
        if "lat" not in q:  # demo query: resolver point; benchmark query: its stored point (same as benchmark_answers)
            q.update(lat=res["lat"], lon=res["lon"])
        svc = q["service"]
        idx = np.flatnonzero(pairs.service.to_numpy() == svc)
        fs = fac.set_index("unique_id").loc[pairs.unique_id.iloc[idx]].reset_index()
        d1, d2 = distances(fs, q["lat"], q["lon"])
        st = st_all.iloc[idx].reset_index(drop=True)
        t, cand, Ru, likely_any = run_u_system(q, fs, st, d1, d2)
        rows, ex = answer_u(q, "WL", t, cand, Ru, likely_any, fs, res)
        uid = [u for u in cand.unique_id if u.startswith(focus)][0]
        rank = list(cand.unique_id).index(uid) + 1
        r = cand.set_index("unique_id", drop=False).loc[uid]
        lines = card(r, svc, ctx, cand.iloc[0])
        c = pc[(pc.unique_id == uid) & (pc.service == svc)]
        grp = c.groupby("group").contribution_logit.sum().to_dict()
        p_s = ctx["ps"].loc[(uid, svc)]
        rec = dict(case=cid, kind=kind, query_id=q["query_id"], service=svc, place=q["location_text"], unique_id=uid,
                   name=r["name"], rank=rank, n_candidates=len(cand), R_used=Ru, abstained=rows[0]["abstained"],
                   plan=[x["name"] for x in rows if x["in_plan"]], plan_p_any=rows[0]["plan_p_any"],
                   d1=float(r.d1), d2=None if not np.isfinite(r.d2) else float(r.d2), P_E=float(r.P_E), P_S=float(r.P_S),
                   P_L=float(r.P_L), G=float(r.G), U=float(r.U), P_succ=float(r.P_succ), band=r.band,
                   T=int(p_s["T"]), C=int(p_s.C), P=int(p_s.P), bucket=p_s.bucket,
                   p_s_without_cited=float(p_s.p_s_without_cited),
                   logit_by_group={k: round(v, 4) for k, v in grp.items()},
                   terms=c[c.contribution_logit.abs() > 1e-9][["term", "group", "x_value", "weight", "contribution_logit", "points"]]
                   .round(4).to_dict("records"))
        out_json.append(rec)
        out_txt += [f"########## {cid} ({kind}) {q['query_id']}: {svc} near {q['location_text']} -> {r['name']} "
                    f"(rank {rank} of {len(cand)}, R {Ru} km, abstained {rec['abstained']}, plan p_any {rec['plan_p_any']:.2f})",
                    "plan: " + " -> ".join(rec["plan"])] + lines + [
                    f"    hidden logit by group: {rec['logit_by_group']}  (T={rec['T']} C={rec['C']} P={rec['P']} bucket={rec['bucket']})", ""]
    (HERE / "cases.txt").write_text("\n".join(out_txt))
    (HERE / "cases.json").write_text(json.dumps(out_json, indent=1, default=str))
    print("\n".join(out_txt))


if __name__ == "__main__":
    main()
