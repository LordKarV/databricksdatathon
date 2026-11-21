"""Decision layer prototype (spec 6): rank facilities for a (service, place) query and build the referral plan.

Inputs (read-only): fusion pair_scores, facility_scores, features_pairs, features_facility, variant_scores;
cleaning facility_groups (strong duplicate groups); record_trust (display phones); raw facilities (name, city, PIN);
ROOT/model/gold/queries.json. No parameter here is fitted, so no benchmark query is used for tuning.

Per query and system:
  d1 = 1.3 haversine(u, p1) + loc_radius_km; d2 the same for p2        road factor 1.3 is an assumption
  G  = P_L exp(-d1/D_s) + (1 - P_L) 1[p2] exp(-d2/D_s);  U = P_E P_S G
  P_succ = P_E P_S (P_L 1[d1 <= R] + (1 - P_L) 1[p2 and d2 <= R])
  R doubles from R_start until 3 non-Unlikely candidates (one per strong duplicate group) or R_max.
  Plan: top option + 2 more from distinct leakage groups; P(at least one works) = 1 - prod(1 - P_succ).
Baselines B0-B3 use the same query point, the same cleaned p1 and the same radius schedule; a baseline's own\neligible set (B0 any mention, B1 tagged sentence, B2 graded mention, B3 judged yes) drives its doubling.

Run: .venv/bin/python -B decide.py   (writes benchmark_answers.parquet/.json, b1_candidates.parquet, run_stats.json)
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
ROOT = Path("/Users/karthikvattem/projects/datathon")
HERE = ROOT / "model/proto/decision"
FUS = ROOT / "model/proto/fusion"
sys.path.insert(0, str(FUS))
from fit import LIKELY_PE, LIKELY_PL, bands  # noqa: E402  same band rule as fusion (spec 5.5)

ROAD, V_FAST, V_SLOW = 1.3, 40.0, 25.0  # assumptions, shown as knobs
T_L, T_U = 0.70, 0.20  # frozen with the fusion model (model.json)
PROFILE = {  # D_s km, R start km, R max km, default urgency (spec 6.4)
    "trauma_emergency": (30, 25, 150, "emergency"), "emergency_csection": (30, 25, 150, "emergency"),
    "burn_care": (100, 50, 300, "emergency"), "nicu": (50, 50, 200, "urgent"),
    "dialysis": (15, 25, 100, "scheduled"), "mri": (75, 50, 300, "elective"),
    "cardiac_surgery": (150, 100, 500, "elective")}
SHAPE = {"emergency": ("plan3", 3), "urgent": ("plan3", 3), "scheduled": ("list3", 3), "elective": ("list5", 5)}
LABEL = {"dialysis": "dialysis", "emergency_csection": "emergency C-section", "nicu": "a NICU (newborn intensive care)",
         "cardiac_surgery": "cardiac surgery", "mri": "MRI", "burn_care": "burn care", "trauma_emergency": "trauma and emergency care"}
GRADE_MAP = {"strong": 0.9, "moderate": 0.6, "weak": 0.3, "tag_only": 0.2}  # others 0.1 (spec 8, B2)
LOC_MAP = {"high": 0.9, "medium": 0.7, "low": 0.4, "disputed": 0.5}  # fallback P_L (spec 6.1, assumption)
OUTSIDE_SERVICES = {"dialysis", "emergency_csection"}  # essential at DH in IPHS 2022
N_SHOW = 5
U_SYSTEMS = ["WL", "B4_prior_only", "B5_M0", "abl_M2", "abl_noown", "abl_noecho", "abl_nobucket", "abl_nocontext",
             "abl_PL1", "WL_fallback", "WLpost_T2gate"]
# WLpost_T2gate: post-hoc sensitivity designed AFTER reading WL's benchmark output (a dental clinic ranked first for
# trauma on context terms alone). Candidates must have T >= 2 (one cited own unit). Not a fair comparison; reported
# only so that the end-to-end labels can settle it.
SCORE_SYSTEMS = ["B0_nearest_mention", "B1_keyword_count", "B2_rule_grade", "B3_llm_judge"]


def hav_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def load():
    ps = pd.read_parquet(FUS / "pair_scores.parquet")
    fs = pd.read_parquet(FUS / "facility_scores.parquet")
    fp = pd.read_parquet(FUS / "features_pairs.parquet", columns=["unique_id", "service", "n_tagged", "any_mention", "grade",
                                                                   "level", "cited_atom_ids", "rejected_atom_ids"])
    ff = pd.read_parquet(FUS / "features_facility.parquet", columns=["unique_id", "loc_conf", "phone_class", "leakage_group_id",
                                                                      "district", "state", "p1_src", "loc_note"])
    vs = pd.read_parquet(FUS / "variant_scores.parquet")
    grp = pd.read_parquet(ROOT / "cleaning/geo_identity/facility_groups.parquet", columns=["unique_id", "dup_group_id"])
    rt = pd.read_parquet(FUS / "inputs_snapshot/record_trust.parquet", columns=["unique_id", "display_phones"])
    raw = pd.read_parquet(ROOT / "data/raw/facilities.parquet", columns=["unique_id", "name", "address_city",
                          "address_stateOrRegion", "address_zipOrPostcode"]).drop_duplicates("unique_id")
    fac = (fs.merge(ff, on="unique_id", how="left").merge(grp, on="unique_id", how="left").merge(rt, on="unique_id", how="left")
           .merge(raw, on="unique_id", how="left"))
    fac["dup_key"] = fac.dup_group_id.fillna(fac.unique_id)
    fac["phone_display"] = fac.display_phones.map(lambda x: ", ".join(list(x)[:2]) if x is not None and len(x) else "")
    lvl = fp.drop_duplicates("unique_id").set_index("unique_id").level
    fac["level"] = fac.unique_id.map(lvl)
    pairs = ps.merge(fp.drop(columns=["level"]), on=["unique_id", "service"]).merge(
        vs, on=["unique_id", "service"]).merge(ff[["unique_id", "loc_conf"]], on="unique_id")
    assert len(fac) == 9959 and len(pairs) == 69713, (len(fac), len(pairs))
    return fac, pairs


def system_table(pairs, system):
    """(unique_id, service) -> P_E, P_S, P_S_lo, P_S_hi, P_L, band for one U-system; same index order as pairs."""
    pe, pl, T, C = pairs.p_e.to_numpy(), pairs.p_l.to_numpy(), pairs["T"].to_numpy(), pairs.C.to_numpy()
    lo = hi = np.full(len(pairs), np.nan)
    if system == "WL":
        p, lo, hi = pairs.p_s.to_numpy(), pairs.p_s_lo.to_numpy(), pairs.p_s_hi.to_numpy()
        return pd.DataFrame(dict(P_E=pe, P_S=p, P_S_lo=lo, P_S_hi=hi, P_L=pl, band=pairs.band.to_numpy(), T_own=T))
    col = {"B4_prior_only": "p_B4_prior_only", "B5_M0": "p_M0", "abl_M2": "p_M2", "abl_PL1": "p_s"}
    if system == "WLpost_T2gate":
        return system_table(pairs, "WL")
    if system in col:
        p = pairs[col[system]].to_numpy()
    elif system.startswith("abl_no"):
        k = system[4:]
        p, T, C = pairs[f"p_abl_{k}"].to_numpy(), pairs[f"T_abl_{k}"].to_numpy(), pairs[f"C_abl_{k}"].to_numpy()
    elif system == "WL_fallback":
        p = pairs.grade.map(GRADE_MAP).fillna(0.1).to_numpy()
        pe, pl = np.ones(len(pairs)), pairs.loc_conf.map(LOC_MAP).fillna(0.4).to_numpy()
    else:
        raise ValueError(system)
    if system == "abl_PL1":
        pl = np.ones(len(pairs))
    band, _ = bands(p, pl, pe, T, C, T_L, T_U)
    return pd.DataFrame(dict(P_E=pe, P_S=p, P_S_lo=lo, P_S_hi=hi, P_L=pl, band=band, T_own=T))


def distances(fac, lat, lon):
    d1 = ROAD * hav_km(lat, lon, fac.p1_lat.to_numpy(), fac.p1_lon.to_numpy()) + fac.loc_radius_km.to_numpy()
    d2 = ROAD * hav_km(lat, lon, fac.p2_lat.to_numpy(), fac.p2_lon.to_numpy()) + fac.loc_radius_km.to_numpy()
    return d1, d2  # d2 is nan when p2 is missing


def utility(t, D):
    has2 = np.isfinite(t.d2)
    G = t.P_L * np.exp(-t.d1 / D) + (1 - t.P_L) * np.where(has2, np.exp(-np.nan_to_num(t.d2, nan=1e9) / D), 0.0)
    return G, t.P_E * t.P_S * G


def in_r(t, R):
    return (t.d1 <= R) | (np.isfinite(t.d2) & (t.d2 <= R))


def collapse(t):
    """One card per strong duplicate group: keep the first row in the current order, list the others' names."""
    also = t.groupby("dup_key").name.agg(lambda s: list(s)[1:])
    t = t.drop_duplicates("dup_key").copy()
    t["also_listed_as"] = t.dup_key.map(also).map(lambda x: "; ".join(map(str, x)))
    return t


def ranked(t, key):
    return t.sort_values(key, ascending=[False] * (len(key) - 1) + [True], kind="mergesort")


def why_first(a, b, D):
    """Exact identity U_A/U_B = evidence ratio x location-and-distance ratio (spec 6.7), for B nearer than A."""
    ev = (a.P_E * a.P_S) / (b.P_E * b.P_S)
    gr = a.G / b.G
    dd = a.d1 - b.d1
    return ev, gr, (f"{b['name']} is {dd:.0f} km nearer. Distance alone favours it by {math.exp(dd / D):.1f}x "
                    f"(exp({dd:.0f}/{D})). {a['name']}'s evidence is {ev:.1f}x stronger (P_E x P_S {a.P_E * a.P_S:.2f} vs "
                    f"{b.P_E * b.P_S:.2f}); location-and-distance ratio {gr:.2f}; {ev:.2f} x {gr:.2f} = {ev * gr:.2f} = "
                    f"U ratio {a.U:.4f} / {b.U:.4f}. So {a['name']} ranks first.")


def phone_note(r):
    c = r.phone_class
    if c == "shared_3plus_cities":
        return "may be a directory number (shared by listings in 3+ cities)"
    if c in ("none", "invalid") or not r.phone_display:
        return "no phone in our data"
    if c == "tollfree":
        return "toll-free number, may be a central helpline"
    return f"{c} number from the listing"


def pareto(t):
    """Options not dominated on (P_succ higher, d1 lower)."""
    o = t.sort_values(["d1", "P_succ"], ascending=[True, False])
    keep, best = [], -1.0
    for uid, ps in zip(o.unique_id, o.P_succ):
        if ps > best:
            keep.append(uid)
            best = ps
    return keep


def plan_members(rk, n_plan=3):
    seen, members = set(), []
    for r in rk.itertuples():
        if r.leakage_group_id not in seen:
            members.append(r.unique_id)
            seen.add(r.leakage_group_id)
        if len(members) == n_plan:
            break
    return members


def run_u_system(q, fac, st, d1, d2, gate=False):
    svc = q["service"]
    D, R0, RMAX, _ = PROFILE[svc]
    t = fac.assign(d1=d1, d2=d2).join(st)
    t["G"], t["U"] = utility(t, D)
    ok = t.band.ne("Unlikely") & ((t.T_own >= 2) if gate else True)
    order = ["U", "P_S", "d1"]
    R = R0
    while True:
        cand = collapse(ranked(t[ok & in_r(t, R)], order))
        if len(cand) >= 3 or R >= RMAX:
            break
        R = min(2 * R, RMAX)
    cand = cand.copy()
    near1 = cand.d1 <= R
    near2 = np.isfinite(cand.d2) & (cand.d2 <= R)
    cand["P_succ"] = cand.P_E * cand.P_S * (cand.P_L * near1 + (1 - cand.P_L) * near2)
    likely_any = bool((t.band.eq("Likely") & in_r(t, RMAX)).any())
    # ponytail: a Likely option beyond R_used but inside R_max is not pulled into the plan; only 2 Likely pairs exist
    return t, cand, R, likely_any


def score_candidates(system, q, t, ps, b3):
    """Eligible rows and scores for one baseline over facilities t (aligned with pair rows ps)."""
    D = PROFILE[q["service"]][0]
    decay = np.exp(-t.d1.to_numpy() / D)
    if system == "B0_nearest_mention":
        elig = ps.any_mention.to_numpy()
        score = np.ones(len(t))
    elif system == "B1_keyword_count":
        elig = ps.n_tagged.to_numpy() > 0
        score = ps.n_tagged.to_numpy() * decay
    elif system == "B2_rule_grade":
        elig = ps.grade.isin(list(GRADE_MAP)).to_numpy()  # counts toward the radius rule; every facility is ranked
        score = ps.grade.map(GRADE_MAP).fillna(0.1).to_numpy() * decay
    else:  # B3: judged B1 candidates, confidence if the judge said yes
        j = (b3 or {}).get(q["query_id"], {})
        conf = np.array([j[u][1] if u in j and j[u][0] == "yes" and j[u][1] is not None else 0.0 for u in t.unique_id])
        elig = conf > 0
        score = conf * decay
    return elig, score


def run_score_system(system, q, fac, pairs_svc, d1, d2, b3=None):
    """Same query point, same cleaned p1, same radius schedule (R_start doubling to R_max until 3 eligible)."""
    _, R0, RMAX, _ = PROFILE[q["service"]]
    t = fac.assign(d1=d1, d2=d2)
    ps = pairs_svc.loc[t.unique_id]
    elig, score = score_candidates(system, q, t, ps, b3)
    t = t.assign(score=score, elig=elig)
    if system == "B3_llm_judge":  # B3 only sees B1's candidates, so it inherits B1's radius
        R = q["_R_b1"]
    else:
        R = R0
        while (t.elig & in_r(t, R)).sum() < 3 and R < RMAX:
            R = min(2 * R, RMAX)
    t = t[in_r(t, R) & (t.elig | (system == "B2_rule_grade"))]
    if system == "B0_nearest_mention":
        return ranked(t.assign(neg=-t.d1), ["neg", "score", "d1"]).drop(columns="neg"), R
    return ranked(t[t.score > 0], ["score", "d1"]), R


def load_b3():
    p = HERE / "llm_b3_pairs.parquet"
    if not p.exists():
        return None
    d = pd.read_parquet(p)
    out = {}
    for r in d.itertuples():
        out.setdefault(r.query_id, {})[r.unique_id] = (r.offers, None if pd.isna(r.confidence) else float(r.confidence))
    return out


def resolution_notes(queries):
    from resolve import Resolver  # 20 s gazetteer build; only needed here
    R = Resolver()
    out = {}
    for q in queries:
        r = R.resolve_place(q["location_text"])
        dist = float(hav_km(q["lat"], q["lon"], r["lat"], r["lon"])) if r["status"] == "ok" else None
        out[q["query_id"]] = dict(status=r["status"], note=r["note"], matches=r["matches"], resolver_lat=r.get("lat"),
                                  resolver_lon=r.get("lon"), km_from_benchmark_point=dist)
    return out


COLS = ["query_id", "system", "service", "query_lat", "query_lon", "resolution_note", "urgency", "D_s", "R_used", "rank",
        "unique_id", "name", "city", "pin", "d1_km", "d2_km", "minutes_lo", "minutes_hi", "P_E", "P_S", "P_S_lo", "P_S_hi",
        "P_L", "G", "U", "P_succ", "score", "band", "plan_role", "in_plan", "plan_p_any", "leakage_group_id", "also_listed_as",
        "pareto", "abstained", "abstain_text", "outside_option_uid", "outside_option_km", "why_first_text",
        "tradeoff_text", "phone", "phone_note", "wl_band", "wl_p_s"]


def answer_u(q, system, t, cand, R, likely_any, fac, res):
    svc, D = q["service"], PROFILE[q["service"]][0]
    urg = q["urgency"]
    shape, n_show = SHAPE[urg]
    members = plan_members(cand)
    rk = cand[(np.arange(len(cand)) < max(N_SHOW, n_show)) | cand.unique_id.isin(members)]
    p_any = 1 - float(np.prod([1 - cand.set_index("unique_id").P_succ[u] for u in members])) if members else 0.0
    abst = not likely_any
    RMAX = PROFILE[svc][2]
    abst_txt = (f"No facility within {RMAX} km has enough public evidence that it offers {LABEL[svc]}. "
                "The options below are not verified: call to confirm.") if abst else ""
    elective = urg == "elective" or PROFILE[svc][3] == "elective"
    par = set(pareto(cand)) if elective else set()
    out_uid = out_km = None
    if svc in OUTSIDE_SERVICES:
        dh = t[t.level.eq("dh")]
        if len(dh):
            r = dh.loc[dh.d1.idxmin()]
            out_uid, out_km = r.unique_id, float(r.d1)
    top = rk.iloc[0] if len(rk) else None
    nonunl = cand.sort_values("d1")
    tradeoff = ""
    if top is not None and nonunl.iloc[0].unique_id != top.unique_id:
        b = nonunl.iloc[0]
        tradeoff = (f"Nearest option: {b['name']} at {b.d1:.0f} km (U {b.U:.4f}, {b.band}). Top option: {top['name']} at "
                    f"{top.d1:.0f} km (U {top.U:.4f}, {top.band}).")
    rows = []
    for i, r in enumerate(rk.itertuples(), 1):
        role = "not_in_plan_same_group"
        if r.unique_id in members:
            k = members.index(r.unique_id)
            role = ["primary", "backup1", "backup2"][k] if shape == "plan3" else "list"
        elif shape == "list5":
            role = "list"
        wf = why_first(top, rk.iloc[i - 1], D)[2] if i > 1 and r.d1 < top.d1 else ""
        rows.append(dict(query_id=q["query_id"], system=system, service=svc, query_lat=q["lat"], query_lon=q["lon"],
                         resolution_note=res["note"], urgency=urg, D_s=D, R_used=R, rank=i, unique_id=r.unique_id,
                         name=r.name, city=r.address_city, pin=r.address_zipOrPostcode, d1_km=r.d1,
                         d2_km=r.d2 if np.isfinite(r.d2) else None, minutes_lo=r.d1 / V_FAST * 60, minutes_hi=r.d1 / V_SLOW * 60,
                         P_E=r.P_E, P_S=r.P_S, P_S_lo=r.P_S_lo, P_S_hi=r.P_S_hi, P_L=r.P_L, G=r.G, U=r.U, P_succ=r.P_succ,
                         score=r.U, band=r.band, plan_role=role, in_plan=r.unique_id in members, plan_p_any=p_any, leakage_group_id=r.leakage_group_id,
                         also_listed_as=r.also_listed_as, pareto=r.unique_id in par, abstained=abst, abstain_text=abst_txt,
                         outside_option_uid=out_uid, outside_option_km=out_km, why_first_text=wf,
                         tradeoff_text=tradeoff if i == 1 else "", phone=r.phone_display,
                         phone_note=phone_note(r), wl_band=None, wl_p_s=None))
    return rows, dict(pareto=sorted(par), members=members)


def answer_score(q, system, rk, R, res):
    D = PROFILE[q["service"]][0]
    rows = []
    for i, r in enumerate(rk.head(N_SHOW).itertuples(), 1):
        rows.append(dict(query_id=q["query_id"], system=system, service=q["service"], query_lat=q["lat"], query_lon=q["lon"],
                         resolution_note=res["note"], urgency=q["urgency"], D_s=D, R_used=R, rank=i, unique_id=r.unique_id,
                         name=r.name, city=r.address_city, pin=r.address_zipOrPostcode, d1_km=r.d1,
                         d2_km=r.d2 if np.isfinite(r.d2) else None, minutes_lo=r.d1 / V_FAST * 60,
                         minutes_hi=r.d1 / V_SLOW * 60, score=r.score, plan_role="list", abstained=False,
                         leakage_group_id=r.leakage_group_id, phone=r.phone_display, phone_note=phone_note(r)))
    if not rows:
        rows.append(dict(query_id=q["query_id"], system=system, service=q["service"], query_lat=q["lat"], query_lon=q["lon"],
                         resolution_note=res["note"], urgency=q["urgency"], D_s=D, R_used=R, rank=0, abstained=True,
                         abstain_text="no candidate within the radius"))
    return rows


def main():
    queries = json.load(open(ROOT / "model/gold/queries.json"))
    fac, pairs = load()
    res = resolution_notes(queries)
    tables = {s: system_table(pairs, s) for s in U_SYSTEMS}
    b3 = load_b3()
    rows, extra, b1c = [], {}, []
    for q in queries:
        svc = q["service"]
        idx = np.flatnonzero(pairs.service.to_numpy() == svc)
        psvc = pairs.iloc[idx].set_index("unique_id")
        fac_s = fac.set_index("unique_id").loc[psvc.index].reset_index()  # same row order as psvc
        d1, d2 = distances(fac_s, q["lat"], q["lon"])
        wl_band, wl_ps = psvc.band, psvc.p_s
        for s in U_SYSTEMS:
            st = tables[s].iloc[idx].reset_index(drop=True)
            t, cand, R, likely_any = run_u_system(q, fac_s, st, d1, d2, gate=s == "WLpost_T2gate")
            r, ex = answer_u(q, s, t, cand, R, likely_any, fac_s, res[q["query_id"]])
            rows += r
            extra[(q["query_id"], s)] = ex
        for s in SCORE_SYSTEMS:
            if s == "B3_llm_judge" and b3 is None:
                continue
            rk, R = run_score_system(s, q, fac_s, psvc, d1, d2, b3)
            if s == "B1_keyword_count":
                q["_R_b1"] = R
                b1c += [dict(query_id=q["query_id"], unique_id=u, service=svc, rank=i, R_b1=R)
                        for i, u in enumerate(rk.unique_id.head(10), 1)]
            rows += answer_score(q, s, rk, R, res[q["query_id"]])
        for r in rows:
            if r["query_id"] == q["query_id"] and r.get("unique_id"):
                r["wl_band"], r["wl_p_s"] = wl_band.get(r["unique_id"]), float(wl_ps.get(r["unique_id"]))
    df = pd.DataFrame(rows).reindex(columns=COLS)
    df.to_parquet(HERE / "benchmark_answers.parquet", index=False)
    pd.DataFrame(b1c).to_parquet(HERE / "b1_candidates.parquet", index=False)
    write_json(df, queries, res, extra)
    stats = dict(rows=len(df), systems=sorted(df.system.unique()), b3_included=b3 is not None,
                 queries=len(queries), resolution={k: v["status"] for k, v in res.items()})
    (HERE / "run_stats.json").write_text(json.dumps(stats, indent=1))
    print(json.dumps(stats)[:600])


def write_json(df, queries, res, extra):
    out = []
    clean = df.astype(object).where(df.notna(), None)
    for q in queries:
        qd = dict(query={k: v for k, v in q.items() if not k.startswith("_")}, resolution=res[q["query_id"]], profile=dict(zip(["D_s", "R_start", "R_max", "default_urgency"],
                  PROFILE[q["service"]])), assumptions=dict(road_factor=ROAD, speeds_kmh=[V_SLOW, V_FAST],
                  independence="P(at least one works) assumes the options fail independently"), systems={})
        for s, g in clean[clean.query_id == q["query_id"]].groupby("system", sort=False):
            qd["systems"][s] = dict(R_used=g.R_used.iloc[0], abstained=g.abstained.iloc[0], abstain_text=g.abstain_text.iloc[0],
                                    plan_p_any=g.plan_p_any.iloc[0], **extra.get((q["query_id"], s), {}),
                                    options=g.drop(columns=["query_id", "system", "service", "query_lat", "query_lon",
                                                            "resolution_note"]).to_dict("records"))
        out.append(qd)
    (HERE / "benchmark_answers.json").write_text(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
