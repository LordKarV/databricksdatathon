"""Export the selected model (A_platt: candidate A prior scorecard + one Platt step fitted on all decided DEV pairs).

Writes derived/v2/facility_service_scores.parquet and derived/v2/model_card.json. Every shipped P_S satisfies
logit(p) = base + sum(points) / (20 / ln 2) to 1e-9 (asserted after a JSON round trip), and every evidence id resolves
to derived/v2/witnesses.parquet or claim_atoms.parquet (asserted).
Run after selection.py: python export.py
"""
import datetime as dt
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
OUT = HERE / "out"
ROOT = Path("/Users/karthikvattem/projects/datathon")
D2 = ROOT / "derived/v2"
V2 = HERE.parent
sys.path.insert(0, str(V2 / "fit_prior"))
sys.path.insert(0, str(ROOT))
import prior_a  # noqa: E402
from common.eligibility import eligible_facilities  # noqa: E402

PTS = 20.0 / math.log(2.0)
TOL = 1e-9
BINS = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0 + 1e-12]
GATE = 0.7  # LIKELY needs P_L and P_E at or above it; P_L below it sets PLACE_UNCLEAR
LOHI = ("lo/hi = Wilson 95% interval of the observed confirmed rate among decided DEV pairs whose OOF P_S falls in "
        "the same score bin (width 0.2, see calibration_by_score_bin) as this row's p. It is the bin's track record, "
        "not an interval around p: every row of a bin carries the same lo/hi, and p need not lie inside it.")
VOTES = ["vote_coords", "vote_pin", "vote_city", "vote_name_place", "vote_state", "vote_text_pin", "vote_map_link"]
CODE = [V2 / "fit_prior/prior_a.py", V2 / "fit_prior/evaluate.py", V2 / "fit_scorecard/metrics.py",
        HERE / "prep_labels.py", HERE / "run_a.py", HERE / "selection.py", HERE / "export.py"]
WIT_FAMILY = {"T": "T", "D": "D", "C": "C", "N": "N", "S": "S", "P": "P", "X": "X", "W": "W", "O": "O", "K": "K", "R": "R"}
SVC_24 = {"dialysis": "is_24x7_dialysis", "emergency_csection": "is_24x7_labour_room",
          "institutional_delivery": "is_24x7_labour_room", "icu": "is_24x7_icu", "picu": "is_24x7_icu",
          "blood_bank": "is_24x7_blood_bank", "mri": "is_24x7_lab_imaging", "ct_scan": "is_24x7_lab_imaging",
          "ultrasound": "is_24x7_lab_imaging"}
EMERG = {"emergency_24x7", "trauma_care", "burn_care", "orthopaedic_trauma_surgery", "snakebite_antivenom",
         "stemi_thrombolysis", "stroke_care", "eye_emergency", "anti_rabies"}
T_PHRASE = {1: "the listing mentions it, at least in a specialty tag or list", 2: "the listing describes it as its own unit",
            3: "two or more own units in one field", 4: "own units in two or more fields",
            5: "own units in several fields plus a unit or quantity"}


def sigmoid(z):
    return 0.5 * (1.0 + np.tanh(0.5 * np.asarray(z, float)))


def phrase(name: str) -> str:
    """Plain-language card phrase for one term."""
    if name[:1] == "t" and name[1:].isdigit():
        return T_PHRASE[int(name[1:])]
    if name.startswith("x_"):
        lst, _, role = name[2:].partition(":")
        return {"x_erk_prereq": "a blood centre on site (e-RaktKosh), a prerequisite"}.get(
            name, f"on the {lst.upper()} public list ({role.replace('_', ' ')})")
    if name.startswith("w_cell_"):
        return f"the facility's own website mentions it (website check class {name[-1]})"
    if name.startswith("w_24x7@"):
        return "the facility's own website states 24x7 emergency"
    fixed = {"trunc0": "not mentioned, but the listing's service list was cut off",
             "d_unit": "a dataset detail (equipment, unit beds or a 24x7 unit) for this service",
             "tb_mid": "record built from many web pages (some text may be another facility's)",
             "tb_high": "record built from 30+ web pages (some text may be another facility's)",
             "tp_public": "public facility: listing text is less often its own", "tw_none": "no website",
             "c1": "some text names another facility", "c2": "text names another facility and no own unit",
             "n1": "text has a non-offer cue (referral, camp, future plan or negation)",
             "s1": "facility focus (eye, dental, IVF or lab) does not fit this service",
             "p1": "a prerequisite (ICU, operating theatre, blood bank) is mentioned",
             "p2": "a second prerequisite is mentioned",
             "w_overlap": "website and listing share pages, so the shared part is counted once",
             "w_silent": "the website is reachable but does not mention this service",
             "o_speciality": "OpenStreetMap lists this speciality", "o_emergency": "OpenStreetMap marks emergency=yes",
             "k_iphs": "the public standard (IPHS) says this level should offer it",
             "scale_contradiction": "stated size contradicts the claimed service", "r_reader": "reader model (not used)"}
    if name in fixed:
        return fixed[name]
    ctx = {"type": "facility type", "level": "public facility level", "beds": "bed count", "breadth": "number of specialties"}
    head = name.split("_")[0]
    return f"{ctx.get(head, head)}: {name.split('_', 1)[1].replace('_', ' ')}" if head in ctx else name


def design() -> tuple[pd.DataFrame, np.ndarray, list, np.ndarray]:
    """Recompute candidate A's design on all pairs with prior_a's own functions and its saved weights."""
    params = json.load(open(OUT / "A/params_A.json"))
    terms = params["service"]
    ff = pd.read_parquet(D2 / "facility_features.parquet")
    at = pd.read_parquet(D2 / "facility_attributes.parquet")
    ag = prior_a.pair_aggregates(ff)
    w = {t["name"]: t["weight"] for t in terms}
    X = prior_a.service_design(ff, ag, at, terms, w)
    beta = np.array([t["weight"] for t in terms])
    sc = pd.read_parquet(OUT / "A/scores_A.parquet")
    assert (sc.unique_id.to_numpy() == ff.unique_id.to_numpy()).all()
    assert np.max(np.abs(X @ beta - sc.z_S.to_numpy())) < TOL, "A design does not reproduce scores_A"
    return ff, X * beta, terms, sc.z_S.to_numpy()


def evidence_index() -> tuple[dict, dict, set]:
    w = pd.read_parquet(D2 / "witnesses.parquet", columns=["unique_id", "service", "family", "source_key", "role",
                                                            "observability", "evidence_id", "fetched_date"])
    w = w[(w.observability == "present") & w.evidence_id.notna() & (w.service != "*")]
    w = w.assign(lst=w.source_key.str.split(":").str[0])
    ev = {k: list(dict.fromkeys(v)) for k, v in w.groupby(["unique_id", "service", "family"]).evidence_id}
    xl = w[w.family == "X"]
    evx = {k: list(dict.fromkeys(v)) for k, v in xl.groupby(["unique_id", "service", "lst"]).evidence_id}
    known = set(pd.read_parquet(D2 / "witnesses.parquet", columns=["evidence_id"]).evidence_id.dropna())
    known |= set(pd.read_parquet(D2 / "claim_atoms.parquet", columns=["atom_id"]).atom_id.dropna())
    return ev, evx, known


def public_lists() -> dict:
    w = pd.read_parquet(D2 / "witnesses.parquet", columns=["unique_id", "service", "family", "source_key", "role",
                                                            "observability", "fetched_date"])
    w = w[(w.family == "X") & (w.observability == "present") & (w.role != "prerequisite") & (w.service != "*")]
    w = w.assign(lst=w.source_key.str.split(":").str[0], d=w.fetched_date.astype(str))
    return {k: sorted({f"ON_A_PUBLIC_LIST:{a}:{b}" for a, b in zip(v.lst, v.d)})
            for k, v in w.groupby(["unique_id", "service"])}


def main() -> None:
    sel = json.load(open(OUT / "select.json"))
    assert sel["cc"]["selection"]["selected"] == "A_platt" and sel["location_head"] == "A_prior"
    a, c = sel["platt_full"]["a"], sel["platt_full"]["c"]
    th = sel["thresholds"]
    ff, C, terms, z = design()
    names = [t["name"] for t in terms]
    fam = [t["family"] for t in terms]
    is_base = np.array([f == "base" for f in fam])
    zs = a * z + c
    base = a * C[:, is_base].sum(1) + c
    Cs = a * C[:, ~is_base]
    assert np.max(np.abs(base + Cs.sum(1) - zs)) < TOL
    p = sigmoid(zs)
    nb_names = [n for n, b in zip(names, is_base) if not b]
    nb_fam = [f for f, b in zip(fam, is_base) if not b]

    fac = pd.read_parquet(OUT / "A/facility_contrib_A.parquet", columns=["unique_id", "P_L", "P_E"])
    pl = ff.unique_id.map(fac.set_index("unique_id").P_L).to_numpy()
    pe = ff.unique_id.map(fac.set_index("unique_id").P_E).to_numpy()
    T = ff.a_T.to_numpy()
    likely = (p >= th["t_L"]) & (pl >= GATE) & (pe >= GATE) & (T >= 2)
    unlikely = (p <= th["t_U"]) | ((ff.a_contamination.to_numpy() >= 2) & (T <= 1))
    assert not (likely & unlikely).any()
    band = np.where(likely, "LIKELY", np.where(unlikely, "UNLIKELY", np.where(T >= 2, "CALL_FIRST", "NO_SERVICE_TEXT")))
    place_unclear = ((pl < GATE) | (ff[VOTES].to_numpy() == -1).any(1) | ff.city_resolve_status.ne("ok").to_numpy()
                     | ff.pin_in_india_post.eq(0).to_numpy())

    # lo / hi: Wilson 95% of the confirmed share among decided DEV pairs in the same OOF score bin (empirical record)
    oof = pd.read_parquet(OUT / "oof_selected.parquet")
    ob = np.digitize(oof.p_A_platt, BINS) - 1
    rec = []
    for b in range(len(BINS) - 1):
        m = ob == b
        k, n = int(oof.y_S[m].sum()), int(m.sum())
        rec.append(dict(bin=b, p_min=BINS[b], p_max=min(BINS[b + 1], 1.0), n_decided=n, k_confirmed=k,
                        k_contradicted=n - k, mean_p=float(oof.p_A_platt[m].mean()) if n else None,
                        wilson95=prior_a_wilson(k, n)))
    pb = np.digitize(p, BINS) - 1
    lo = np.array([rec[b]["wilson95"][0] for b in pb], float)
    hi = np.array([rec[b]["wilson95"][1] for b in pb], float)

    ev, evx, known = evidence_index()
    lists = public_lists()
    uid, svc = ff.unique_id.to_numpy(), ff.service.to_numpy()
    contribs, overlays = [], []
    phr = {n: phrase(n) for n in nb_names}
    for i in range(len(ff)):
        nz = np.flatnonzero(Cs[i])
        items = []
        for j in nz:
            n, f = nb_names[j], nb_fam[j]
            if f == "X" and n != "x_erk_prereq":
                ids = evx.get((uid[i], svc[i], n[2:].split(":")[0]), [])
            elif n == "x_erk_prereq":
                ids = evx.get((uid[i], svc[i], "eraktkosh"), [])
            else:
                ids = ev.get((uid[i], svc[i], WIT_FAMILY.get(f, "")), []) if f in WIT_FAMILY else []
            items.append(dict(label=n, family=f, points=float(Cs[i, j] * PTS), evidence_ids=ids, card_phrase=phr[n]))
        contribs.append(json.dumps(items))
        ov = []
        if likely[i] and p[i] - th["t_L"] < 0.05:
            ov.append("BORDERLINE")
        if place_unclear[i]:
            ov.append("PLACE_UNCLEAR")
        ov += lists.get((uid[i], svc[i]), [])
        overlays.append(ov)

    # additivity after the JSON round trip, and evidence resolution
    bad_ids = 0
    for i, s in enumerate(contribs):
        items = json.loads(s)
        tot = base[i] + sum(it["points"] for it in items) / PTS
        assert abs(tot - zs[i]) < TOL, (i, tot, zs[i])
        bad_ids += sum(e not in known for it in items for e in it["evidence_ids"])
    assert bad_ids == 0, f"{bad_ids} evidence ids do not resolve"

    at = pd.read_parquet(D2 / "facility_attributes.parquet").set_index("unique_id")
    op = ff.unique_id.map(at.operator).to_numpy()
    col24 = [SVC_24.get(s, "is_24x7_emergency" if s in EMERG else "is_24x7_facility") for s in svc]
    is24 = np.array([at.at[u, k] for u, k in zip(uid, col24)], dtype=object)
    hours = ff.unique_id.map(at.opd_hours).to_numpy()
    mv = model_version(sel, a, c)
    out = pd.DataFrame(dict(unique_id=uid, service_id=svc, band=band, overlays=overlays, p=p, lo=lo, hi=hi,
                            p_location=pl, p_exists=pe, base=base, contributions=contribs, operator=op,
                            is_24x7=pd.array([None if pd.isna(v) else bool(v) for v in is24], dtype="boolean"),
                            hours_text=hours, as_of=dt.date.today().isoformat(), model_version=mv))
    assert len(out) == 358524 and not out.duplicated(["unique_id", "service_id"]).any()
    # same eligibility rule as the app: exclude_review records (12, none a TEST facility) are not scored at all
    fac_ = pd.read_parquet(ROOT / "derived/v1/facility_location.parquet", columns=["unique_id", "loc_lat", "loc_lon"]
                           ).merge(pd.read_parquet(ROOT / "derived/v1/record_trust.parquet",
                                                   columns=["unique_id", "trust_level"]), on="unique_id", how="left")
    keep, elig = eligible_facilities(fac_)
    out = out[out.unique_id.isin(fac_.unique_id[keep])].reset_index(drop=True)
    assert len(out) == elig["kept"] * 36, (len(out), elig)
    out.to_parquet(D2 / "facility_service_scores.parquet", index=False)
    card(sel, terms, a, c, mv, rec, out, oof, elig)
    print("eligibility", elig)
    print("model_version", mv)
    print("bands", out.band.value_counts().to_dict())
    print("p quantiles", np.round(np.quantile(p, [0.01, 0.1, 0.5, 0.9, 0.99]), 3).tolist())
    print("place unclear", int(place_unclear.sum()), "evidence ids checked ok; additivity ok")


def prior_a_wilson(k: int, n: int) -> list:
    if n == 0:
        return [0.0, 1.0]
    zq = 1.959964
    ph = k / n
    d = 1 + zq * zq / n
    cc = (ph + zq * zq / (2 * n)) / d
    h = zq * math.sqrt(ph * (1 - ph) / n + zq * zq / (4 * n * n)) / d
    return [max(0.0, cc - h), min(1.0, cc + h)]


def model_version(sel: dict, a: float, c: float) -> str:
    h = hashlib.sha256()
    h.update((OUT / "A/params_A.json").read_bytes())
    h.update(json.dumps(dict(platt_a=a, platt_c=c, t_L=sel["thresholds"]["t_L"], t_U=sel["thresholds"]["t_U"],
                             location="A_prior", existence="A_prior"), sort_keys=True).encode())
    for f in CODE:
        h.update(f.read_bytes())
    return h.hexdigest()


def card(sel: dict, terms: list, a: float, c: float, mv: str, rec: list, out: pd.DataFrame, oof: pd.DataFrame,
         elig: dict) -> None:
    g = pd.read_parquet(OUT / "labels_cc/gold_dev_pairs.parquet")
    p_all = out.set_index(["unique_id", "service_id"]).p
    g = g.assign(p=p_all.reindex(pd.MultiIndex.from_frame(g[["unique_id", "service"]])).to_numpy())
    oofp = oof.set_index("pair_id").p_A_platt
    g["p_rec"] = np.where(g.pair_id.isin(oofp.index), g.pair_id.map(oofp), g.p)  # OOF for decided pairs
    gb = np.digitize(g.p_rec, BINS) - 1
    for r in rec:
        m = gb == r["bin"]
        r["k_no_info"] = int((m & g.label_service.eq("no_info") & g.searched).sum())
        r["k_never_searched"] = int((m & ~g.searched.astype(bool)).sum())
    weights = []
    for t in terms:
        weights.append(dict(term=t["name"], family=t["family"], prior_weight=t["weight"],
                            shipped_logit=t["weight"] * a, shipped_points=t["weight"] * a * PTS,
                            derivation=t["derivation"], n_fired_all=t.get("n_fired_all")))
    fam_w = (pd.DataFrame(weights).groupby("family").shipped_points.agg(["count", "min", "max"]).round(3)
             .reset_index().to_dict("records"))
    lab_stats = json.load(open(ROOT / "model/v2/labels/out/stats.json"))
    vs = json.load(open(OUT / "labels_view_stats.json"))
    pub = out.operator.eq("public")
    card_ = dict(
        model_version=mv, created=dt.datetime.now().isoformat(timespec="seconds"),
        selected="A_platt", selected_meaning=(
            "P_S = chance that a web check which finds a decisive answer confirms the service (confirmed vs "
            "contradicted; no-information checks excluded). It is not the chance that a phone call finds the service."),
        service_head=dict(base_scorecard="candidate A expert prior scorecard (fit_prior/prior_a.py), no weight fitted",
                          platt=dict(a=a, c=c, fitted_on="all 221 decided DEV pairs, unweighted",
                                     contribution_rule="every term contribution is a x prior contribution; base = a x "
                                                       "sum(intercepts) + c")),
        location_head=dict(shipped="A prior scorecard (expert settings)", comparison=sel["location"]),
        existence_head="prior-only expert settings, not learned (decision; 47 DEV negatives, all 'unclear and searched')",
        selection_rule="ship the least-fitted of A < A_platt < B < B_platt < C unless a more-fitted one lowers grouped "
                       "5-fold OOF log loss by at least one paired cluster SE",
        selection_headline=sel["cc"], selection_sensitivity=sel["sens"],
        public_vs_private=sel["operator"],
        public_note=("Public DEV pairs: 28 confirmed, 3 contradicted. The score has no demonstrated ranking ability "
                     "for public facilities (AUROC interval spans 0.5 widely)."),
        per_service_text_only=sel["per_service_text_only"],
        thresholds=sel["thresholds"],
        band_thresholds=dict(likely=dict(p=sel["thresholds"]["t_L"], p_location=GATE, p_exists=GATE),
                             unlikely=dict(p=sel["thresholds"]["t_U"]),
                             rule="LIKELY: p >= t_L, P_L and P_E >= 0.7, T >= 2. UNLIKELY: p <= t_U, or C = 2 with "
                                  "T <= 1 (the c2 term). Otherwise CALL_FIRST when T >= 2, else NO_SERVICE_TEXT."),
        eligibility=dict(elig, rule="common/eligibility.py eligible_facilities: exclude_review records are not scored"),
        conformal=sel["conformal"],
        conformal_note=("Pseudo-queries are (service, state) groups of DEV pairs, median size 2 to 3; a random order "
                        "reaches nearly the same coverage, so k carries little information about live queries."),
        calibration_by_score_bin=rec,
        calibration_note="bins on DEV OOF P_S for decided pairs and on the shipped P_S for undecided pairs",
        per_term_weights=weights, per_family_points=fam_w,
        intervals=LOHI, field_descriptions=dict(lo=LOHI, hi=LOHI),
        bands_all_pairs=out.band.value_counts().to_dict(), bands_public=out.band[pub].value_counts().to_dict(),
        label_provenance=dict(
            wording="agent-labelled, not human-checked",
            gold_primary_pairs=vs["gold_primary"], headline=vs["cc"], sensitivity=vs["sens"],
            versions="v3_dev 300 (web-labelled DEV, inclusion probabilities known), v2 140, e2e 121 primary, v1 36",
            v3_kish_effective_n=sel["cc"]["table"]["_ipw_v3_n"],
            trauma="old trauma_emergency / trauma_care gold relabelled emergency_24x7; trauma_care gold from v3 only; "
                   f"{vs['pu_trauma_care_rows_dropped']} trauma_care PU list rows dropped from training",
            test_exclusion=dict(blocked_facilities=vs["blocked_facilities"], blocked_groups=vs["blocked_groups"],
                                note="TEST facilities and their leakage groups removed from all training rows; TEST "
                                     "labels never opened"),
            labels_stats_sha256=hashlib.sha256((ROOT / "model/v2/labels/out/stats.json").read_bytes()).hexdigest(),
            second_labeller_agreement_v3=lab_stats.get("v3_second_agreement")),
        caveats=["No fairness parity is claimed; public facilities are few and nearly all confirmed in DEV.",
                 "v1 numbers are history and are not comparable with these DEV numbers.",
                 "Not-observable sources contribute 0 by construction.",
                 "Candidate D (reader) was rejected; the reader slot has weight 0 and never fires."])
    (D2 / "model_card.json").write_text(json.dumps(card_, indent=1, default=float))


if __name__ == "__main__":
    main()
