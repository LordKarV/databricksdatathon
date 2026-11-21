"""Three worked examples of what the App shows for a query (strong, uncertain, contaminated). Writes worked_examples.txt.

Every number is read from the same rows the ranking uses (decide.py functions on fusion tables); text is templated,
no LLM. Two of the three queries are demo queries outside the benchmark (Panipat dialysis, Nagpur dialysis), chosen
because they contain the one Likely dialysis record and the known contaminated Wockhardt record.
Run: .venv/bin/python -B cards.py
"""
import json
import sys

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
from decide import (FUS, HERE, LABEL, PROFILE, ROOT, answer_u, distances, load, run_u_system,  # noqa: E402
                    system_table, why_first)
from resolve import Resolver  # noqa: E402

CASES = [("strong", dict(query_id="demo_panipat", service="dialysis", location_text="Panipat district, Haryana", urgency="scheduled"), None),
         ("uncertain", "q35", None),
         ("contaminated", dict(query_id="demo_nagpur", service="dialysis", location_text="Nagpur", urgency="scheduled"), "3ac5ae50")]
VOTE = {"v_coords": "map point", "v_pin": "PIN centre", "v_city": "stated city", "v_name": "place in the name", "v_state": "stated state"}
HEAD = {"Likely": "LIKELY offers", "Unverified": "Not verified: call to confirm", "Unlikely": "Little public evidence for"}


def card(r, svc, ctx, top=None):
    atoms, ff, br, fp, raw = ctx["atoms"], ctx["ff"], ctx["br"], ctx["fp"], ctx["raw"]
    u, f, p = r.unique_id, ff.loc[r.unique_id], fp.loc[(r.unique_id, svc)]
    L = [f"[1] {HEAD[r.band]} {LABEL[svc]} - {r['name']}, {r.address_city}        [band, name]",
         f"    About {r.d1:.0f} km by road ({r.d1 / 40 * 60:.0f} to {r.d1 / 25 * 60:.0f} min, rough estimate: straight line x 1.3)"]
    if np.isfinite(r.d2):
        L.append(f"    Or {r.d2:.0f} km if it is at its second recorded location (we put {1 - r.P_L:.0%} of the location belief there)")
    rec = br[(br.band == r.band) & (br.split == "test")].iloc[0]
    L.append(f"[2] How sure it offers the service: {r.P_S:.2f} (range {r.P_S_lo:.2f} to {r.P_S_hi:.2f}).")
    L.append(f"    Track record: of {rec.N} checked test facilities in this band, {rec.k_confirmed} were confirmed, "
             f"{rec.k_contradicted} were wrong, {rec.k_no_info} had no public information." if rec.N else
             "    Track record: no checked test facility fell in this band yet, so we cannot say how often it is right.")
    ids = [a for a in str(p.cited_atom_ids or "").split("|") if a]
    ids = ["|".join(ids[i:i + 2]) for i in range(0, len(ids), 2)]
    L.append("[3] Why we think it offers it (sentences from its own listing):")
    L += [f"    [{atoms.loc[a].field}] \"{atoms.loc[a].text}\"" for a in ids] or ["    (no sentence of its own names the service: the score rests on facility type and size)"]
    urls = json.loads(raw.loc[u].source_urls) if str(raw.loc[u].source_urls).startswith("[") else []
    L.append(f"    Sources: one of these pages: {', '.join(urls[:2])}{' ...' if len(urls) > 2 else ''} ({len(urls)} pages)")
    L.append(f"[4] Is it real: website {f.web_class.replace('_', ' ')}; phone {f.phone_class.replace('_', ' ')}. P_E = {r.P_E:.2f} "
             "(existence weights are expert settings, not learned).")
    agree = [VOTE[k] for k in VOTE if f[k] == 1]
    dis = [VOTE[k] for k in VOTE if f[k] == -1]
    L.append(f"[5] Where: P_L = {r.P_L:.2f} that it is at the point we use. Agree: {', '.join(agree) or 'none'}. "
             f"Point elsewhere: {', '.join(dis) or 'none'}.")
    if dis or r.P_L < 0.7:
        L.append(f"    Warning: {f.loc_note}")
    rej = [a for a in str(p.rejected_atom_ids or "").split("|") if a]
    rej = ["|".join(rej[i:i + 2]) for i in range(0, len(rej), 2)]
    L.append("[6] What we ignored:" + ("" if rej else " nothing (no sentence about another facility or place)"))
    for a in rej:
        x = atoms.loc[a]
        L.append(f"    \"{x.text}\" - {str(x.rejected_reason).replace('_', ' ')}: {x.named_entity}")
    if top is not None and top.unique_id != u and r.d1 < top.d1:
        L.append(f"[7] Why {top['name']} is listed above this one: {why_first(top, r, PROFILE[svc][0])[2]}")
    L.append(f"[8] Call first: {r.phone_display or 'no phone in our data'} ({ctx['pnote'](r)})")
    L.append(f"    Ranking arithmetic: U = P_E x P_S x G = {r.P_E:.3f} x {r.P_S:.3f} x {r.G:.4f} = {r.U:.4f}; "
             f"G = {r.P_L:.2f} exp(-{r.d1:.1f}/{PROFILE[svc][0]})" + (f" + {1 - r.P_L:.2f} exp(-{r.d2:.1f}/{PROFILE[svc][0]})" if np.isfinite(r.d2) else ""))
    L.append(f"    Counterfactual: without the quoted sentences P_S would be {ctx['ps'].loc[(u, svc)].p_s_without_cited:.2f}.")
    return L


def main():
    from decide import phone_note
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
    out = []
    for kind, q, focus in CASES:
        q = dict(queries[q]) if isinstance(q, str) else dict(q)
        res = R.resolve_place(q["location_text"])
        q.update(lat=res["lat"], lon=res["lon"])
        svc = q["service"]
        idx = np.flatnonzero(pairs.service.to_numpy() == svc)
        uids = pairs.unique_id.iloc[idx]
        fs = fac.set_index("unique_id").loc[uids].reset_index()
        d1, d2 = distances(fs, q["lat"], q["lon"])
        st = st_all.iloc[idx].reset_index(drop=True)
        t, cand, Ru, likely_any = run_u_system(q, fs, st, d1, d2)
        rows, ex = answer_u(q, "WL", t, cand, Ru, likely_any, fs, res)
        D, R0, RMAX, _ = PROFILE[svc]
        L = [f"=================== Example: {kind} ({q['query_id']}: {LABEL[svc]} near {q['location_text']}) ===================",
             f"{res['note']}. Urgency: {q['urgency']}. Search radius used: {Ru} km (starts at {R0}, doubles until 3 options, max {RMAX}).",
             f"Distance scale D_s = {D} km for {LABEL[svc]} (assumption, a slider in the App)."]
        r0 = rows[0]
        if r0["abstained"]:
            L.append("ABSTAIN: " + r0["abstain_text"])
        plan = [r for r in rows if r["in_plan"]]
        L.append(f"Plan: {' -> '.join(f'{x['name']} ({x['d1_km']:.0f} km, P_succ {x['P_succ']:.2f})' for x in plan)}")
        L.append(f"P(at least one of these works) = {r0['plan_p_any']:.2f}, assuming the options fail independently "
                 "(options from one copied-content group are never paired).")
        if r0["tradeoff_text"]:
            L.append("Trade-off: " + r0["tradeoff_text"])
        if svc in ("dialysis", "emergency_csection") and not r0["outside_option_uid"]:
            L.append(f"Also: no district hospital record within {RMAX} km whose location we trust (P_L >= 0.7).")
        if r0["outside_option_uid"]:
            o = fs.set_index("unique_id").loc[r0["outside_option_uid"]]
            L.append(f"Also: district hospital {o['name']} ({r0['outside_option_km']:.0f} km): the public standard (IPHS 2022) says this "
                     "level should offer it; not verified in our data.")
        cidx = cand.set_index("unique_id", drop=False)
        top = cand.iloc[0]
        show = [x["unique_id"] for x in plan]
        if focus:
            hit = [u for u in cidx.index if u.startswith(focus)]
            if hit and hit[0] not in show:
                show.append(hit[0])
            fr = (list(cand.unique_id).index(hit[0]) + 1) if hit else None
            L.append(f"Focus record {focus}: " + (f"rank {fr} of {len(cand)} candidates." if fr else "not a candidate (outside radius or Unlikely)."))
        for i, u in enumerate(show, 1):
            L.append(f"--- card {i} ---")
            L += card(cidx.loc[u], svc, ctx, top)
        out += L + [""]
    (HERE / "worked_examples.txt").write_text("\n".join(out))
    print("\n".join(out))


if __name__ == "__main__":
    main()
