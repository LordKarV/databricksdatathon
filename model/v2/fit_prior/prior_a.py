"""Candidate A: expert prior-only scorecards v2 for P_S, P_L and P_E (no fitting on labels).

Every weight is a prior mean with a written derivation from a named audit, QA or match-precision rate (or a ported
M1 mean, model/proto/fusion/priors_M1.json). Nothing here reads a gold label. The only data-derived numbers are
r_W (website recall, anchored on own-text level T >= 4, no labels) and the per-pair witness aggregates.

Outputs (out/): params_A.json (every term: head, family, mu, sign, derivation), scores_A.parquet (all 358,524
pairs: z, P_S, family sums, P_L, P_E), contrib_gold_A.parquet (wide per-term contributions for the gold pairs).
Run: /Users/karthikvattem/projects/datathon/.venv-viz/bin/python prior_a.py
"""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

ROOT = Path("/Users/karthikvattem/projects/datathon")
D2 = ROOT / "derived/v2"
OUT = ROOT / "model/v2/fit_prior/out"
LABELS = ROOT / "model/v2/labels/out"
TOL = 1e-9
PTS = 20.0 / math.log(2.0)


def sigmoid(z: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.tanh(0.5 * np.asarray(z, float)))


def logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def jeffreys(k: float, n: float) -> float:
    """Point estimate (k + 0.5) / (n + 1), the smoothing M1 used for n1 (6.5/41)."""
    return (k + 0.5) / (n + 1.0)


# ---- named rates ---------------------------------------------------------------------------------------------
B_SERVICE = -2.9                      # M1 b_*: expert base rate about 5% for a pair with no mention
PI0 = 1.0 / (1.0 + math.exp(-B_SERVICE))
R_CONFIRM = jeffreys(10, 12)          # v1 strong stratum 10/12 confirmed: P(web check confirms | offered), lower bound
B_EXIST = 1.0                         # M1 b_ex
PI0_E = 1.0 / (1.0 + math.exp(-B_EXIST))


def llr_positive(p: float, r: float = R_CONFIRM, pi0: float = PI0) -> float:
    """LLR of a positive witness whose statement 'F offers s' is true with probability p.

    With only this witness, P(confirmed) = r p + (1 - p) pi0 (a true statement is confirmed at rate r; a false one
    leaves the pair at the base rate). The weight moves the base logit to that value."""
    return logit(r * p + (1.0 - p) * pi0) - logit(pi0)


# list match precision (k, n) from the witness table (acommon.PRECISION, research/DATASETS.md)
LIST_PREC = {"nabh": (39, 40), "nmc": (19, 20), "laqshya": (17, 20), "mohfw_tcf": (19, 20), "eraktkosh": (16, 20),
             "pmndp_goa": (1, 1)}
# meaning factor: how directly the list row states this service (expert; LABELS.md: no hand check of meaning)
ROLE_M = {"service_code": 1.0, "service": 1.0, "certificate": 1.0, "designation": 0.5, "department": 0.5,
          "department_support": 0.5, "department_proxy": 0.25}
ROLE_WHY = {"service_code": "the list states this service", "service": "the list states this service",
            "certificate": "a dated certificate for the unit that does it",
            "designation": "a scheme designation; README: 12th-plan rows not verified functional",
            "department": "a department, not the service (FEATURES.md: NABH codes are departments)",
            "department_support": "a supporting PG course (value 0.5) in a related department",
            "department_proxy": "a proxy department (cardiology for cardiac surgery)"}
# website QA cells (kb/web_evidence/qa/QA.md)
WEB_CELL = {"A": (13, 13), "B": (3, 3), "C": (8, 14), "D": (5, 12), "E": (7, 18)}
WEB_24X7 = (9, 10)                    # 24x7 emergency fact correct, QA 9/10
WEB_24X7_M = {"emergency_24x7": 1.0, "trauma_care": 0.25, "emergency_csection": 0.25}
OSM_SVC_M = 0.5                       # OSM speciality map not hand-checked (ASSEMBLE.md not run)
G_SCOPE = (67, 44)                    # G_scope hand check: claims at single-focus facilities, 67 true / 44 false
TEXT_UNIT_PREC = (96, 100)            # vf_text_unit role offer: sentence says the service is provided
# contamination priors (PATTERNS.md findings 1, 3; M1 tb_high merge audit)
Q_LOW, Q_HIGH = 0.042, 0.596          # contamination share of records at < 3 URLs and at 30+ URLs (merge audit)
OR_PUBLIC = 2.34                      # public vs private hospitals, adjusted (PATTERNS 1, discovery)
OR_WEB_NONE = 1.34                    # no website vs live site, adjusted (PATTERNS 3)
# location priors (PATTERNS 3, 4): drift odds ratios
OR_DRIFT = {"d_nabh_listed": 0.49, "k_text_pmjay": 1.59, "web_none": 1.51}
OSM_CONFLICT = (4, 15)                # osm_conflict rows that really are the facility
OSM_EXIST = {"high": (17, 20), "medium": (7, 10)}


def m1_priors() -> dict:
    j = json.load(open(ROOT / "model/proto/fusion/priors_M1.json"))
    return {**j["priors"]["service"], **{f"L:{k}": v for k, v in j["priors"]["location"].items()},
            **{f"E:{k}": v for k, v in j["priors"]["existence"].items()}}


# ---- witness aggregates per pair -------------------------------------------------------------------------------
def pair_aggregates(keys: pd.DataFrame) -> pd.DataFrame:
    w = pd.read_parquet(D2 / "witnesses.parquet", columns=["unique_id", "service", "family", "witness", "role", "value",
                                                            "observability", "source_key"])
    w = w[(w.observability == "present") & (w.service != "*")]
    out = keys[["unique_id", "service"]].copy()
    idx = pd.MultiIndex.from_frame(out)

    def put(name: str, s: pd.Series, fill=0.0):
        out[name] = s.reindex(idx).fillna(fill).to_numpy()

    t = w[w.family == "T"]
    put("t_nonspec", t[t.witness != "vf_specialty"].groupby(["unique_id", "service"]).size().gt(0).astype(float))
    put("spec_w", t[t.witness == "vf_specialty"].groupby(["unique_id", "service"]).value.max())
    # P: distinct cues, value = 1 for a text cue, the specialty evidence weight for a specialty cue
    p = w[w.family == "P"].groupby(["unique_id", "service", "witness"]).value.max().reset_index()
    p = p.sort_values("value", ascending=False)
    p["rank"] = p.groupby(["unique_id", "service"]).cumcount()
    for r in (0, 1):
        put(f"p_v{r + 1}", p[p["rank"] == r].set_index(["unique_id", "service"]).value)
    # X: best meaning factor x value per list (one vote per list)
    x = w[w.family == "X"].copy()
    xs = x[x.role != "prerequisite"].copy()
    xs["mv"] = xs.role.map(ROLE_M) * xs.value
    assert xs.mv.notna().all(), xs[xs.mv.isna()].role.unique()
    best = xs.sort_values("mv", ascending=False).groupby(["unique_id", "service", "source_key"]).first().reset_index()
    for key in LIST_PREC:
        b = best[best.source_key == key].set_index(["unique_id", "service"])
        out[f"xmv_{key}"] = b.mv.reindex(idx).fillna(0.0).to_numpy()
    put("x_erk_prereq", x[(x.role == "prerequisite") & (x.source_key == "eraktkosh")]
        .groupby(["unique_id", "service"]).size().gt(0).astype(float))
    # W: 24x7 emergency fact rows (service cells come from e_web_cell)
    ww = w[(w.family == "W") & (w.witness == "web_24x7_emergency")]
    put("w_24x7", ww.groupby(["unique_id", "service"]).size().gt(0).astype(float))
    o = w[w.family == "O"]
    put("o_spec", o[o.witness == "osm_speciality"].groupby(["unique_id", "service"]).size().gt(0).astype(float))
    put("o_emerg", o[o.witness == "osm_emergency_yes"].groupby(["unique_id", "service"]).size().gt(0).astype(float))
    put("d_present", w[w.family == "D"].groupby(["unique_id", "service"]).size().gt(0).astype(float))
    return out


# ---- term table --------------------------------------------------------------------------------------------------
def term(name, head, family, mu, sign, derivation, source, sd=1.0):
    return dict(name=name, head=head, family=family, mu=float(mu), sd=float(sd), sign=int(sign),
                derivation=derivation, source=source)


def service_terms(services: list, m1: dict, r_w: dict) -> list:
    T = []
    for s in services:
        T.append(term(f"b_{s}", "S", "base", B_SERVICE, 0, m1["b_dialysis"]["derivation"] + " (M1 b_*, same for all 36)",
                      "priors_M1.json", sd=1.5))
    for k in ["t1", "t2", "t3", "t4", "t5"]:
        extra = " x = specialty evidence weight when the only mention is a specialties item" if k == "t1" else ""
        T.append(term(k, "S", "T", m1[k]["mu"], +1, m1[k]["derivation"] + extra, "priors_M1.json", m1[k]["sd"]))
    T.append(term("trunc0", "S", "T", m1["trunc0"]["mu"], +1, m1["trunc0"]["derivation"] + "; also when the only "
                  "mention is a specialties item", "priors_M1.json", 0.75))
    T.append(term("d_unit", "S", "D", m1["t2"]["mu"], +1, "a dataset detail (equipment count, unit beds, 24x7 unit) is "
                  "one own unit from the same text: the t2 step, only when T < 2 (D is not independent of T)",
                  "kb/vf_details 46/50; ASSEMBLE.md D note", 1.0))
    # contamination priors on own text (T >= 2), in log P(text is own) relative to a low-breadth private record
    q_mid = 1 - (1 - Q_LOW) * math.exp(m1["tb_mid"]["mu"])
    odds_mid = q_mid / (1 - q_mid)
    T.append(term("tb_mid", "S", "C_prior", m1["tb_mid"]["mu"], -1, m1["tb_mid"]["derivation"] + "; bucket by URL count "
                  "8 to 29 (v1 n_urls cut, q_share not in v2)", "priors_M1.json", 0.75))
    T.append(term("tb_high", "S", "C_prior", m1["tb_high"]["mu"], -1, m1["tb_high"]["derivation"] + "; 30+ URLs",
                  "priors_M1.json", 0.75))
    for name, orr, src in [("tp_public", OR_PUBLIC, "PATTERNS 1: public hospital contamination OR 2.34 (1.79 to 3.07)"),
                           ("tw_none", OR_WEB_NONE, "PATTERNS 3: no website contamination OR 1.34 (1.12 to 1.59)")]:
        q = orr * odds_mid / (1 + orr * odds_mid)
        mu = math.log((1 - q) / (1 - q_mid))
        T.append(term(name, "S", "C_prior", mu, -1, f"log P(own | OR {orr}) / P(own) at the mid bucket "
                      f"(q {q_mid:.3f} -> {q:.3f}), applied when T >= 2", src, 0.75))
    T.append(term("c1", "S", "C", m1["c1"]["mu"], -1, m1["c1"]["derivation"] + "; v2 witness rates 23/34 agree",
                  "priors_M1.json", 1.0))
    T.append(term("c2", "S", "C", m1["c2"]["mu"], -1, m1["c2"]["derivation"], "priors_M1.json", 1.0))
    T.append(term("n1", "S", "N", m1["n1"]["mu"], -1, m1["n1"]["derivation"], "priors_M1.json", 0.75))
    s_mu = logit(jeffreys(*G_SCOPE[:1], sum(G_SCOPE))) - logit(jeffreys(*TEXT_UNIT_PREC))
    T.append(term("s1", "S", "S", s_mu, -1, f"claim precision at single-focus facilities {G_SCOPE[0]}/{sum(G_SCOPE)} "
                  f"vs own text units {TEXT_UNIT_PREC[0]}/{TEXT_UNIT_PREC[1]}: logit difference; replaces M1 s1 -1.5 "
                  "and type_dentist -2.0 (v2 S fires for every service outside the focus)", "G_scope hand check", 1.0))
    T.append(term("p1", "S", "P", m1["p1"]["mu"], +1, m1["p1"]["derivation"] + "; x = value of the strongest distinct "
                  "cue (1 text cue, specialty evidence weight for a specialty cue)", "priors_M1.json", 1.0))
    T.append(term("p2", "S", "P", m1["p2"]["mu"], +1, m1["p2"]["derivation"] + "; x = value of the second cue",
                  "priors_M1.json", 1.0))
    k, n = LIST_PREC["eraktkosh"]
    T.append(term("x_erk_prereq", "S", "X", m1["p1"]["mu"] * k / n, +1, f"blood centre on site is a prerequisite: p1 "
                  f"({m1['p1']['mu']}) x match precision {k}/{n}", "e-RaktKosh match check", 1.0))
    for key, (k, n) in LIST_PREC.items():
        pm = jeffreys(k, n)
        for role, m in ROLE_M.items():
            if key == "nabh" and role in ("service_code", "department", "department_proxy") or \
               key == "nmc" and role in ("department",) or key in ("laqshya",) and role == "certificate" or \
               key == "mohfw_tcf" and role == "designation" or key in ("eraktkosh", "pmndp_goa") and role == "service":
                T.append(term(f"x_{key}:{role}", "S", "X", llr_positive(pm * m), +1,
                              f"llr_positive(p = match {k}/{n} -> {pm:.3f} x meaning {m} ({ROLE_WHY[role]}))",
                              f"{key} match precision", 1.0))
        if key == "nmc":
            T.append(term("x_nmc:department_support", "S", "X", llr_positive(pm * 0.25), +1,
                          f"llr_positive(p = {pm:.3f} x meaning 0.5 x value 0.5)", "nmc match precision", 1.0))
        if key == "laqshya":
            T.append(term("x_laqshya:expired", "S", "X", llr_positive(pm * 0.5), +1,
                          f"llr_positive(p = {pm:.3f} x value 0.5): certificate expired before 2026-11-21",
                          "laqshya match precision", 1.0))
    for c, (k, n) in WEB_CELL.items():
        T.append(term(f"w_cell_{c}", "S", "W", llr_positive(jeffreys(k, n)), +1,
                      f"llr_positive(QA cell {c} {k}/{n} -> {jeffreys(k, n):.3f})", "kb/web_evidence/qa/QA.md", 1.0))
    for s, m in WEB_24X7_M.items():
        T.append(term(f"w_24x7@{s}", "S", "W", llr_positive(jeffreys(*WEB_24X7) * m), +1,
                      f"llr_positive(24x7 emergency fact {WEB_24X7[0]}/{WEB_24X7[1]} x meaning {m})", "QA.md", 1.0))
    T.append(term("w_overlap", "S", "W", 1.0, +1, "shared pages counted once: contribution = -min(text points t1..t5, "
                  "website points), so text and own site together earn max(text, website); the record text was "
                  "extracted from the same web pages (FEATURES.md finding 5)", "rule", 0.0))
    T.append(term("w_silent", "S", "W", math.log(1 - r_w["r"]), -1,
                  f"site observable but silent: log(1 - r_W), r_W = P(site mentions s | own text T >= 4, site observable)"
                  f" = {r_w['k']}/{r_w['n']} (label-free anchor, as LABELS.md text_T4)", "witnesses.parquet", 1.0))
    T.append(term("o_speciality", "S", "O", llr_positive(jeffreys(17, 20) * OSM_SVC_M), +1,
                  f"llr_positive(OSM match 17/20 x meaning {OSM_SVC_M}: speciality map not hand-checked)",
                  "kb/opendata", 1.0))
    T.append(term("o_emergency", "S", "O", llr_positive(jeffreys(17, 20)), +1,
                  "llr_positive(OSM match 17/20): emergency=yes, for emergency_24x7 only", "kb/opendata", 1.0))
    T.append(term("k_iphs", "S", "K", m1["iphs_essential"]["mu"], +1, m1["iphs_essential"]["derivation"] +
                  "; v2: x = IPHS expectation 0 / 0.5 / 1 for public facilities with a known level, 36 services",
                  "priors_M1.json, acommon.IPHS", 0.75))
    for k in ["type_clinic", "type_other", "level_dh", "level_sdh", "level_chc", "level_phc", "level_mc", "beds_lt30",
              "beds_100p", "breadth_lt5", "breadth_20p", "scale_contradiction"]:
        T.append(term(k, "S", "context", m1[k]["mu"], 0, m1[k]["derivation"], "priors_M1.json", m1[k]["sd"]))
    T.append(term("r_reader", "S", "R", 0.0, +1, "slot for issue #50 reader p_offers (absent: x = 0); weight to be set "
                  "from the reader's own validation, never from gold", "slot", 1.0))
    return T


def project(terms: list, A_rows: list) -> np.ndarray:
    """Constrained point closest to the prior means in the prior metric (the B4 rule, P/fusion/fit.py)."""
    names = [t["name"] for t in terms]
    mu = np.array([t["mu"] for t in terms])
    sd = np.array([max(t["sd"], 1e-3) for t in terms])
    free = np.array([t["sd"] > 0 for t in terms])
    rows = []
    for i, t in enumerate(terms):
        if t["sign"]:
            r = np.zeros(len(terms)); r[i] = t["sign"]; rows.append(r)
    for pairs in A_rows:
        r = np.zeros(len(terms))
        for n, c in pairs:
            r[names.index(n)] = c
        rows.append(r)
    A = np.array(rows)
    if (A @ mu >= -1e-12).all():
        return mu
    res = minimize(lambda b: np.sum(((b - mu) / sd) ** 2), mu, jac=lambda b: 2 * (b - mu) / sd ** 2,
                   constraints=[{"type": "ineq", "fun": lambda b: A @ b, "jac": lambda b: A},
                                {"type": "eq", "fun": lambda b: (b - mu)[~free]}], method="SLSQP",
                   options={"ftol": 1e-14, "maxiter": 500})
    assert res.success, res.message
    b = np.where(np.abs(res.x) < 1e-10, 0.0, res.x)
    assert (A @ b >= -1e-9).all()
    return b


# ---- design ------------------------------------------------------------------------------------------------------
def service_design(ff: pd.DataFrame, ag: pd.DataFrame, at: pd.DataFrame, terms: list, w: dict) -> tuple:
    """Return (X, overlap_x): X has one column per term (w_overlap column filled after the text points are known)."""
    n = len(ff)
    Tv = ff.a_T.to_numpy()
    spec_only = (Tv == 1) & (ag.t_nonspec.to_numpy() == 0) & (ag.spec_w.to_numpy() > 0)
    no_nonspec = (Tv == 0) | spec_only
    attr = at.set_index("unique_id").reindex(ff.unique_id)
    ftype = attr.facility_type.to_numpy()
    lvl = attr.facility_level.to_numpy()
    beds = attr.beds.to_numpy(float)
    nurl = ff.c_n_urls.to_numpy()
    t2p = Tv >= 2
    cols = {}
    for t in terms:
        if t["name"].startswith("b_"):
            cols[t["name"]] = (ff.service.to_numpy() == t["name"][2:]).astype(float)
    cols["t1"] = np.where(spec_only, ag.spec_w.to_numpy(), (Tv >= 1).astype(float))
    for v in range(2, 6):
        cols[f"t{v}"] = (Tv >= v).astype(float)
    cols["trunc0"] = (no_nonspec & (ff.a_list_truncated.to_numpy() == 1)).astype(float)
    cols["d_unit"] = ((ag.d_present.to_numpy() == 1) & (Tv < 2)).astype(float)
    cols["tb_mid"] = (t2p & (nurl >= 8) & (nurl < 30)).astype(float)
    cols["tb_high"] = (t2p & (nurl >= 30)).astype(float)
    cols["tp_public"] = (t2p & (ff.operator_public.to_numpy() == 1)).astype(float)
    cols["tw_none"] = (t2p & (ff.web_state.to_numpy() == "none")).astype(float)
    C = ff.a_contamination.to_numpy()
    cols["c1"], cols["c2"] = (C >= 1).astype(float), (C >= 2).astype(float)
    cols["n1"] = (ff.a_negation.to_numpy() >= 1).astype(float)
    cols["s1"] = (ff.a_scope_conflict.to_numpy() >= 1).astype(float)
    cols["p1"], cols["p2"] = ag.p_v1.to_numpy(), ag.p_v2.to_numpy()
    cols["x_erk_prereq"] = ag.x_erk_prereq.to_numpy()
    # X: one indicator per list, at its best meaning-x-value level
    level_of = {("nabh", 1.0): "service_code", ("nabh", 0.5): "department", ("nabh", 0.25): "department_proxy",
                ("nmc", 0.5): "department", ("nmc", 0.25): "department_support", ("laqshya", 1.0): "certificate",
                ("laqshya", 0.5): "expired", ("mohfw_tcf", 0.5): "designation", ("eraktkosh", 1.0): "service",
                ("pmndp_goa", 1.0): "service"}
    names = {t["name"] for t in terms}
    for key in LIST_PREC:
        mv = ag[f"xmv_{key}"].to_numpy()
        seen = np.zeros(n, bool)
        for (k2, lv), role in level_of.items():
            if k2 != key:
                continue
            nm = f"x_{key}:{role}"
            assert nm in names, nm
            cols[nm] = np.isclose(mv, lv).astype(float)
            seen |= np.isclose(mv, lv)
        assert ((mv > 0) == seen).all(), f"unmapped X level for {key}: {np.unique(mv[(mv > 0) & ~seen])}"
    # W: best website witness only
    cell = ff.e_web_cell.fillna("").to_numpy()
    wpts = np.zeros(n)
    wcands = {}
    for c in WEB_CELL:
        wcands[f"w_cell_{c}"] = (cell == c)
    for s in WEB_24X7_M:
        wcands[f"w_24x7@{s}"] = (ag.w_24x7.to_numpy() == 1) & (ff.service.to_numpy() == s)
    best_name = np.array([""] * n, dtype=object)
    for nm, mask in wcands.items():
        better = mask & (w[nm] > wpts)
        wpts = np.where(better, w[nm], wpts)
        best_name = np.where(better, nm, best_name)
    for nm in wcands:
        cols[nm] = (best_name == nm).astype(float)
    obs_w = ff.obs_W.to_numpy()
    cols["w_silent"] = ((obs_w == "absent") & (wpts == 0)).astype(float)
    assert not ((obs_w == "not_observable") & (wpts > 0)).any()
    # O: best service tag
    oe = (ag.o_emerg.to_numpy() == 1) & (ff.service.to_numpy() == "emergency_24x7")
    cols["o_emergency"] = oe.astype(float)
    cols["o_speciality"] = ((ag.o_spec.to_numpy() == 1) & ~oe).astype(float)
    cols["k_iphs"] = np.nan_to_num(ff.g_iphs_prior.to_numpy(), nan=0.0)
    ft = np.where(np.isin(ftype, ["hospital", "clinic", "dentist"]), ftype, "other")
    cols["type_clinic"] = (ft == "clinic").astype(float)
    cols["type_other"] = (ft == "other").astype(float)
    for l in ["dh", "sdh", "chc", "phc", "mc"]:
        cols[f"level_{l}"] = (lvl == l).astype(float)
    cols["beds_lt30"] = (beds < 30).astype(float)
    cols["beds_100p"] = (beds >= 100).astype(float)
    nsp = ff.g_n_specialties.to_numpy()
    cols["breadth_lt5"] = (nsp <= 4).astype(float)
    cols["breadth_20p"] = (nsp >= 20).astype(float)
    cols["scale_contradiction"] = ff.b_scale_contradiction.to_numpy(float)
    cols["r_reader"] = np.nan_to_num(ff.r_reader_p_offers.to_numpy(float), nan=0.0)
    # overlap: -min(text points, website points)
    tpts = sum(w[f"t{v}"] * cols[f"t{v}"] for v in range(1, 6))
    cols["w_overlap"] = -np.minimum(tpts, wpts)
    X = np.column_stack([np.asarray(cols[t["name"]], float) for t in terms])
    assert np.isfinite(X).all()
    return X


def location_terms(m1: dict) -> list:
    L = []
    for k, fam in [("b_loc", "base"), ("v_coords", "vote"), ("v_pin", "vote"), ("v_city", "vote"), ("v_name", "vote"),
                   ("v_state", "vote"), ("src_pin", "source"), ("src_city", "source"), ("src_map", "source"),
                   ("f_copied_geocode", "flag"), ("f_coords_look_wrong", "flag"), ("f_pin_looks_wrong", "flag"),
                   ("f_text_pin_elsewhere", "flag")]:
        p = m1[f"L:{k}"]
        sign = {"vote": +1, "flag": -1}.get(fam, 0)
        L.append(term(k, "L", fam, p["mu"], sign, p["derivation"], "priors_M1.json", p["sd"]))
    for k, src in [("d_nabh_listed", "PATTERNS 4: NABH list match drift OR 0.49 (0.40 to 0.60)"),
                   ("k_text_pmjay", "PATTERNS 4: PM-JAY text drift OR 1.59 (1.20 to 2.10)"),
                   ("web_none", "PATTERNS 3: no website drift OR 1.51 (1.20 to 1.89)")]:
        L.append(term(f"l_{k}", "L", "prior", -math.log(OR_DRIFT[k]), +1 if OR_DRIFT[k] < 1 else -1,
                      f"-log(drift OR {OR_DRIFT[k]}) as an LLR on location-right odds; NaN (not observable) is 0", src))
    L.append(term("l_osm_conflict", "L", "flag", math.log(1 - jeffreys(*OSM_CONFLICT)), -1,
                  f"log(1 - p): an OSM same-name point elsewhere really is the facility {OSM_CONFLICT[0]}/"
                  f"{OSM_CONFLICT[1]}", "kb/opendata"))
    return L


def location_design(fac: pd.DataFrame, terms: list) -> np.ndarray:
    cols = {"b_loc": np.ones(len(fac)), "v_coords": fac.vote_coords, "v_pin": fac.vote_pin, "v_city": fac.vote_city,
            "v_name": fac.vote_name_place, "v_state": fac.vote_state,
            "src_pin": fac.p1_src.eq("postcode_centre"), "src_city": fac.p1_src.eq("address_city_centre"),
            "src_map": fac.p1_src.eq("map_link"), "f_copied_geocode": fac.copied_geocode,
            "f_coords_look_wrong": fac.coords_look_wrong, "f_pin_looks_wrong": fac.pin_looks_wrong,
            "f_text_pin_elsewhere": fac.vote_text_pin.eq(-1),
            "l_d_nabh_listed": fac.d_nabh_listed.fillna(0).eq(1), "l_k_text_pmjay": fac.k_text_pmjay.eq(1),
            "l_web_none": fac.web_state.eq("none"), "l_osm_conflict": fac.f_osm_conflict.fillna(0).eq(1)}
    return np.column_stack([np.asarray(cols[t["name"]], float) for t in terms])


def existence_terms(m1: dict) -> list:
    E = []
    for k in ["b_ex", "e_web_own", "e_web_other", "e_phone_shared3", "e_phone_none", "e_multi_source", "e_recency",
              "e_nonfacility", "e_dup_member", "e_coord_shared3"]:
        p = m1[f"E:{k}"]
        sign = {"e_web_own": 1, "e_phone_shared3": -1, "e_phone_none": -1, "e_multi_source": 1, "e_recency": 1,
                "e_nonfacility": -1, "e_coord_shared3": -1}.get(k, 0)
        E.append(term(k, "E", "base" if k == "b_ex" else "existence", p["mu"], sign, p["derivation"], "priors_M1.json",
                      p["sd"]))
    for tier, (k, n) in OSM_EXIST.items():
        E.append(term(f"e_osm_{tier}", "E", "O", llr_positive(jeffreys(k, n), r=1.0, pi0=PI0_E), +1,
                      f"llr_positive(OSM/Wikidata {tier} tier {k}/{n}, r = 1, base P_E {PI0_E:.3f})", "kb/opendata"))
    k, n = LIST_PREC["nabh"]
    E.append(term("e_nabh_listed", "E", "X", llr_positive(jeffreys(k, n), r=1.0, pi0=PI0_E), +1,
                  f"llr_positive(NABH match {k}/{n}, r = 1): an accredited facility exists; absence is 0",
                  "NABH match check"))
    return E


def existence_design(fac: pd.DataFrame, osm_tier: pd.Series, terms: list) -> np.ndarray:
    tier = osm_tier.reindex(fac.unique_id).fillna("").to_numpy()
    cols = {"b_ex": np.ones(len(fac)), "e_web_own": fac.website_class.eq("own_domain"),
            "e_web_other": fac.website_class.isin(["directory_or_host", "government_portal"]),
            "e_phone_shared3": fac.b_directory_phone.eq(1), "e_phone_none": fac.phone_class.eq("none"),
            "e_multi_source": fac.n_source_ids >= 2, "e_recency": fac.page_recency_present,
            "e_nonfacility": fac.non_facility_type, "e_dup_member": fac.strong_dup_member,
            "e_coord_shared3": fac.coord_shared_3plus_names, "e_osm_high": tier == "high",
            "e_osm_medium": tier == "medium", "e_nabh_listed": fac.d_nabh_listed.fillna(0).eq(1)}
    return np.column_stack([np.asarray(cols[t["name"]], float) for t in terms])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ff = pd.read_parquet(D2 / "facility_features.parquet")
    at = pd.read_parquet(D2 / "facility_attributes.parquet")
    services = sorted(ff.service.unique())
    assert len(services) == 36 and len(ff) == 358524
    reader = D2 / "reader_scores.parquet"
    print("reader_scores present:", reader.exists(), "| v3 dev labels present:",
          (ROOT / "model/gold/v3/dev_labels.json").exists())
    m1 = m1_priors()
    ag = pair_aggregates(ff)
    # r_W: website recall on pairs with strong own text, site observable (label-free)
    anchor = (ff.a_T >= 4) & (ff.obs_W != "not_observable")
    r_w = dict(k=int((ff.obs_W[anchor] == "present").sum()), n=int(anchor.sum()))
    r_w["r"] = jeffreys(r_w["k"], r_w["n"])
    spec_only = (ff.a_T == 1) & (ag.t_nonspec == 0) & (ag.spec_w > 0)
    spec_w_max = float(ag.spec_w[spec_only].max())
    terms = service_terms(services, m1, r_w)
    # composite monotonicity (MODEL_SPEC 3.2): one more own unit never lowers the score, even on the riskiest record;
    # replacing a specialties-only mention (x = weight) by a text mention never lowers it while trunc0 is lost
    A_rows = [[("t2", 1.0), ("tb_high", 1.0), ("tp_public", 1.0), ("tw_none", 1.0)],
              [("t1", 1.0 - spec_w_max), ("trunc0", -1.0)]]
    beta = project(terms, A_rows)
    for t, b in zip(terms, beta):
        t["weight"] = float(b)
        t["projected"] = bool(abs(b - t["mu"]) > 1e-9)
    w = {t["name"]: t["weight"] for t in terms}
    X = service_design(ff, ag, at, terms, w)
    names = [t["name"] for t in terms]
    contrib = X * beta
    contrib[:, names.index("w_overlap")] = X[:, names.index("w_overlap")] * 1.0  # weight 1 on -min(text, web)
    assert w["w_overlap"] == 1.0
    z = X @ beta
    assert np.max(np.abs(z - contrib.sum(1))) < TOL
    fam = {}
    for t, c in zip(terms, contrib.T):
        fam.setdefault(t["family"], np.zeros(len(ff)))
        fam[t["family"]] = fam[t["family"]] + c
    assert np.max(np.abs(sum(fam.values()) - z)) < TOL
    # monotonicity check on the data: removing the website witness or the X lists never raises z
    wcols = [i for i, n in enumerate(names) if n.startswith("w_cell") or n.startswith("w_24x7")]
    no_web = z - contrib[:, wcols].sum(1) - contrib[:, names.index("w_overlap")]
    assert (no_web <= z + 1e-12).all()

    fac = ff.drop_duplicates("unique_id").reset_index(drop=True)
    w_all = pd.read_parquet(D2 / "witnesses.parquet", columns=["unique_id", "service", "family", "witness", "observability"])
    o = w_all[(w_all.family == "O") & (w_all.observability == "present") & (w_all.service == "*")]
    o = o[o.witness.str.contains("_match_")].assign(tier=lambda d: d.witness.str.split("_").str[-1])
    osm_tier = o.sort_values("tier").groupby("unique_id").tier.first()  # 'high' sorts before 'medium'
    Lt, Et = location_terms(m1), existence_terms(m1)
    for T_, A_ in [(Lt, []), (Et, [])]:
        bt = project(T_, A_)
        for t, b in zip(T_, bt):
            t["weight"], t["projected"] = float(b), bool(abs(b - t["mu"]) > 1e-9)
    XL, XE = location_design(fac, Lt), existence_design(fac, osm_tier, Et)
    zL = XL @ np.array([t["weight"] for t in Lt])
    zE = XE @ np.array([t["weight"] for t in Et])
    for Xh, Th, zh in [(XL, Lt, zL), (XE, Et, zE)]:
        assert np.max(np.abs((Xh * np.array([t["weight"] for t in Th])).sum(1) - zh)) < TOL

    sc = ff[["unique_id", "service", "leakage_group_id"]].copy()
    sc["z_S"], sc["P_S"] = z, sigmoid(z)
    for f, v in fam.items():
        sc[f"fam_{f}"] = v
    sc["T"] = ff.a_T.to_numpy()
    sc["operator_public"] = ff.operator_public.to_numpy()
    fl = pd.DataFrame({"unique_id": fac.unique_id, "z_L": zL, "P_L": sigmoid(zL), "z_E": zE, "P_E": sigmoid(zE)})
    for t, c in zip(Lt, (XL * np.array([t["weight"] for t in Lt])).T):
        fl[f"L:{t['name']}"] = c
    for t, c in zip(Et, (XE * np.array([t["weight"] for t in Et])).T):
        fl[f"E:{t['name']}"] = c
    sc = sc.merge(fl[["unique_id", "z_L", "P_L", "z_E", "P_E"]], on="unique_id", how="left")
    sc.to_parquet(OUT / "scores_A.parquet", index=False)
    fl.to_parquet(OUT / "facility_contrib_A.parquet", index=False)

    gold = pd.read_parquet(LABELS / "gold_dev_pairs.parquet")[["unique_id", "service"]]
    key = pd.MultiIndex.from_frame(ff[["unique_id", "service"]])
    rows = key.get_indexer(pd.MultiIndex.from_frame(gold))
    assert (rows >= 0).all()
    cg = pd.DataFrame(contrib[rows], columns=names)
    xg = pd.DataFrame(X[rows], columns=[f"x:{n}" for n in names])
    cg = pd.concat([gold.reset_index(drop=True), cg, xg], axis=1)
    cg["z_S"] = z[rows]
    cg.to_parquet(OUT / "contrib_gold_A.parquet", index=False)

    fired = (X != 0).sum(0)
    for t, k in zip(terms, fired):
        t["n_fired_all"] = int(k)
    params = dict(candidate="A_prior_only_v2", created_by="model/v2/fit_prior/prior_a.py", fitted_on_labels=False,
                  constants=dict(B_SERVICE=B_SERVICE, R_CONFIRM=R_CONFIRM, PI0=PI0, B_EXIST=B_EXIST, r_W=r_w,
                                 spec_w_max=spec_w_max, points_per_logit=PTS),
                  composite_constraints=[[list(p) for p in r] for r in A_rows],
                  service=terms, location=Lt, existence=Et,
                  inputs={p.name: hashlib.sha256(p.read_bytes()).hexdigest()[:16] for p in
                          [D2 / "facility_features.parquet", D2 / "witnesses.parquet", D2 / "facility_attributes.parquet",
                           ROOT / "model/proto/fusion/priors_M1.json"]})
    json.dump(params, open(OUT / "params_A.json", "w"), indent=1)
    # recompute z from the saved file alone
    pj = json.load(open(OUT / "params_A.json"))
    beta2 = np.array([t["weight"] for t in pj["service"]])
    assert np.max(np.abs(X @ beta2 - z)) < TOL
    print(f"terms S {len(terms)} L {len(Lt)} E {len(Et)}; projected: {[t['name'] for t in terms + Lt + Et if t['projected']]}")
    print(f"r_W {r_w}; spec_w_max {spec_w_max:.4f}; max |z - sum contrib| {np.max(np.abs(z - contrib.sum(1))):.2e}")
    print("P_S quantiles", np.round(np.quantile(sc.P_S, [0.5, 0.9, 0.99, 0.999, 1.0]), 3))
    print("P_L quantiles", np.round(np.quantile(fl.P_L, [0.01, 0.1, 0.5]), 3), "P_E", np.round(np.quantile(fl.P_E, [0.01, 0.1, 0.5]), 3))
    for t in terms + Lt + Et:
        if not t["name"].startswith("b_") or t["name"] in ("b_loc", "b_ex", "b_dialysis"):
            print(f"  {t['head']} {t['family']:8s} {t['name']:28s} mu {t['mu']:+.3f} w {t['weight']:+.3f} "
                  f"fired {t.get('n_fired_all', '')}")


if __name__ == "__main__":
    main()
