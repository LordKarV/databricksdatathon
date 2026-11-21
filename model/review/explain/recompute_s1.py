"""End-to-end recompute of case S1 (Civil Hospital, Panipat; dialysis near Panipat district) without the prototype's
scoring code: hand-built indicator row x model.json weights -> Platt -> P_S; location and existence heads the same way;
haversine from the resolved query point -> d1, G, U, P_succ; why-first ratio vs the nearer option; quotes vs raw parquet.
Also checks every quote on the six reviewed cards (cases.json) against the raw array item.
Read-only. Run: /Users/karthikvattem/projects/datathon/.venv/bin/python -B recompute_s1.py
"""
import json
import math
import sys
from pathlib import Path

import pandas as pd

sys.dont_write_bytecode = True
ROOT = Path("/Users/karthikvattem/projects/datathon")
FUS = ROOT / "model/proto/fusion"
HERE = ROOT / "model/review/explain"
UID = "acde9be7-1859-4c30-a5aa-71f18a4f590e"
NEAR = "Ravindra Hospital, Panipat"
PTS = 20 / math.log(2)


def sig(z: float) -> float:
    return 1 / (1 + math.exp(-z))


def hav(a1: float, o1: float, a2: float, o2: float) -> float:
    a1, o1, a2, o2 = map(math.radians, (a1, o1, a2, o2))
    h = math.sin((a2 - a1) / 2) ** 2 + math.cos(a1) * math.cos(a2) * math.sin((o2 - o1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def main() -> None:
    m = json.load(open(FUS / "model.json"))
    beta = dict(zip([t["name"] for t in m["terms"]], m["beta"]))
    a, c = m["platt"]
    fp = pd.read_parquet(FUS / "features_pairs.parquet").set_index(["unique_id", "service"]).loc[(UID, "dialysis")]
    ff = pd.read_parquet(FUS / "features_facility.parquet").set_index("unique_id").loc[UID]
    # indicator row written out by hand from the family values (spec 5.2), not via design.service_X
    T, P = int(fp["T"]), int(fp.P)
    x = {"b_dialysis": 1, **{f"t{v}": int(T >= v) for v in range(1, 6)},
         "tb_mid": int(T >= 2 and fp.bucket == "mid"), "g_mid": int(fp.bucket == "mid"), "c1": int(fp.C >= 1),
         "n1": int(fp.N >= 1), "s1": int(fp.S >= 1), "p1": int(P >= 1), "p2": int(P >= 2), "public": int(bool(fp.public)),
         "level_dh": int(fp.level == "dh"), "iphs_essential": int(fp.iphs_essential == 1),
         "beds_100p": int(fp.beds_bin == "100p"), "doctors_20p": int(fp.doctors_bin == "20p"),
         "breadth_20p": int(fp.breadth_bin == "20p"), "t2@dialysis": int(T >= 2), "t4@dialysis": int(T >= 4),
         "p1@dialysis": int(P >= 1)}
    contrib = {k: a * beta[k] * v for k, v in x.items() if v}
    z = sum(contrib.values()) + c
    ps = pd.read_parquet(FUS / "pair_scores.parquet").set_index(["unique_id", "service"]).loc[(UID, "dialysis")]
    evid = sum(v for k, v in contrib.items() if k[0] in "tcnsp" and k not in ("public",))
    ctx = sum(v for k, v in contrib.items() if k in ("g_mid", "public", "level_dh", "iphs_essential", "beds_100p", "doctors_20p", "breadth_20p"))
    quotes_only = a * (beta["t1"] + beta["t2"] + beta["t2@dialysis"] + beta["t3"] + beta["t4"] + beta["t4@dialysis"])
    # location head (no Platt: platt.json location use = false)
    lb = dict(zip([t["name"] for t in m["location"]["terms"]], m["location"]["beta"]))
    zl = lb["b_loc"] + sum(lb[v] * ff[v] for v in ["v_coords", "v_pin", "v_city", "v_name", "v_state"]) + \
        lb["src_pin"] * (ff.p1_src == "postcode_centre") + lb["src_city"] * (ff.p1_src == "address_city_centre")
    eb = dict(zip([t["name"] for t in m["existence"]["terms"]], m["existence"]["beta"]))
    ze = eb["b_ex"] + sum(eb[k] * float(ff[k]) for k in eb if k.startswith("e_") and k in ff.index and k != "e_coord_shared3")
    fs = pd.read_parquet(FUS / "facility_scores.parquet").set_index("unique_id").loc[UID]
    # query point exactly as cards.py resolves it
    sys.path.insert(0, str(ROOT / "model/proto/decision"))
    from resolve import Resolver
    q = Resolver().resolve_place("Panipat district, Haryana")
    d1 = 1.3 * hav(q["lat"], q["lon"], ff.p1_lat, ff.p1_lon) + ff.loc_radius_km
    P_L, P_E, P_S = sig(zl), sig(ze), sig(z)
    G = P_L * math.exp(-d1 / 15)
    U = P_E * P_S * G
    P_succ = P_E * P_S * P_L * (d1 <= 25)
    # why-first vs the nearer option, from the stored ranking row of that option
    near = pd.read_parquet(FUS / "features_facility.parquet").query("name == @NEAR").iloc[0]
    nps = pd.read_parquet(FUS / "pair_scores.parquet").query("unique_id == @near.unique_id and service == 'dialysis'").iloc[0]
    dn = 1.3 * hav(q["lat"], q["lon"], near.p1_lat, near.p1_lon) + near.loc_radius_km
    Gn = nps.p_l * math.exp(-dn / 15)
    Un = nps.p_e * nps.p_s * Gn
    out = dict(
        query_point=q["note"], platt_a=a, platt_c=c,
        z_recomputed=z, z_stored=float(ps.z_cal), P_S_recomputed=P_S, P_S_stored=float(ps.p_s),
        logit_evidence=evid, logit_context=ctx, logit_base=a * beta["b_dialysis"] + c,
        logit_from_quoted_text_steps=quotes_only, points_from_quoted_text=quotes_only * PTS,
        points_from_prereq_p1=a * (beta["p1"] + beta["p1@dialysis"]) * PTS,
        points_context=ctx * PTS, P_S_if_context_removed=sig(z - ctx),
        P_S_without_text_steps=sig(z - quotes_only), P_S_without_cited_stored=float(ps.p_s_without_cited),
        margin_over_tL=P_S - m["t_L"],
        P_L_recomputed=P_L, P_L_stored=float(fs.p_l), P_E_recomputed=P_E, P_E_stored=float(fs.p_e),
        existence_terms_fired={k: eb[k] for k in eb if k.startswith("e_") and k in ff.index and float(ff[k])},
        d1_km=d1, G=G, U=U, P_succ=P_succ,
        nearer=dict(name=NEAR, d1_km=dn, P_E=float(nps.p_e), P_S=float(nps.p_s), P_L=float(nps.p_l), G=Gn, U=Un),
        U_ratio=U / Un, evidence_ratio=(P_E * P_S) / (nps.p_e * nps.p_s), G_ratio=G / Gn,
        contributions_points={k: round(v * PTS, 2) for k, v in contrib.items()})
    # quote faithfulness on all six cards
    raw = pd.read_parquet(ROOT / "data/raw/facilities.parquet").drop_duplicates("unique_id").set_index("unique_id")
    atoms = pd.read_parquet(FUS / "atoms.parquet").set_index("atom_id")
    fpa = pd.read_parquet(FUS / "features_pairs.parquet").set_index(["unique_id", "service"])
    checks = []
    for case in json.load(open(HERE / "cases.json")):
        r = fpa.loc[(case["unique_id"], case["service"])]
        ids = [i for i in str(r.cited_atom_ids or "").split("|") if i] + [i for i in str(r.rejected_atom_ids or "").split("|") if i]
        for aid in ["|".join(ids[i:i + 2]) for i in range(0, len(ids), 2)]:
            at = atoms.loc[aid]
            arr = json.loads(raw.loc[at.unique_id, at.field])
            checks.append(dict(case=case["case"], atom=aid, equal=arr[int(at.idx)] == at.text))
    out["quote_checks"] = dict(n=len(checks), n_equal=sum(x["equal"] for x in checks), rows=checks)
    (HERE / "recompute_s1.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps({k: v for k, v in out.items() if k != "quote_checks"}, indent=1, default=float))
    print("quotes equal raw:", out["quote_checks"]["n_equal"], "/", out["quote_checks"]["n"])
    assert abs(z - ps.z_cal) < 1e-9 and abs(P_L - fs.p_l) < 1e-9 and abs(P_E - fs.p_e) < 1e-9


if __name__ == "__main__":
    main()
