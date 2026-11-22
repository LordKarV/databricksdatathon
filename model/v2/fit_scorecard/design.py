"""Candidate B design: named 0/1 terms, prior means (candidate A centres), sign and monotone constraints.

Every column is a named indicator (or a -1/0/+1 vote for location), so contribution = weight x value and the score is
base + sum of contributions exactly. Not-observable sources (no website, list does not cover the facility type,
operator not public for IPHS) leave their columns at 0, so they contribute 0; absence from an official list has no
column at all and can never lower a score.

Prior means: candidate A (prior-only expert scorecard) had not published parameters when this ran, so the centres are
written here. Shared text terms are read unchanged from model/proto/fusion/priors_M1.json; the new v2 terms carry the
derivation in PRIORS. If candidate A publishes different means, edit service_terms() to read them and rerun fit.py.
"""
from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/karthikvattem/projects/datathon")
HERE = ROOT / "model/v2/fit_scorecard"
OUT = HERE / "out"
DER = ROOT / "derived/v2"
LAB = ROOT / "model/v2/labels/out"
sys.dont_write_bytecode = True

CATEGORIES = {
    "emergency_and_trauma": ["emergency_24x7", "trauma_care", "burn_care", "orthopaedic_trauma_surgery", "snakebite_antivenom"],
    "critical_care": ["icu", "picu", "ventilator_support"],
    "maternal_and_newborn": ["emergency_csection", "institutional_delivery", "high_risk_pregnancy", "nicu", "safe_abortion_mtp"],
    "heart_and_brain": ["cardiac_surgery", "cath_lab_angioplasty", "stemi_thrombolysis", "stroke_care", "neurosurgery"],
    "kidney": ["dialysis", "kidney_transplant"],
    "cancer": ["chemotherapy", "radiotherapy", "surgical_oncology"],
    "diagnostics_and_blood": ["mri", "ct_scan", "ultrasound", "blood_bank"],
    "mental_health": ["psychiatric_care", "de_addiction"],
    "eye": ["cataract_surgery", "eye_emergency"],
    "infectious_disease": ["tb_care", "hiv_art", "anti_rabies"],
    "child_health": ["paediatric_inpatient", "nutrition_rehabilitation"],
}
CAT_OF = {s: c for c, ss in CATEGORIES.items() for s in ss}
SERVICES = [s for ss in CATEGORIES.values() for s in ss]
W24_SERVICES = {"emergency_24x7", "trauma_care", "emergency_csection"}  # where the W hours witness is emitted
DEV_TERMS = ("t2", "t4", "p1")  # slopes that get category and service deviations
PU_FAMILIES = ("nabh", "nmc", "laqshya", "eraktkosh")
PTS = 20.0 / math.log(2.0)


@dataclass(frozen=True)
class Term:
    name: str
    family: str     # base, T, C, N, S, P, X, W, O, D, K, R, context, offset
    sign: int       # +1 (>= 0), -1 (<= 0), 0 free
    mu: float
    sd: float
    why: str
    source: str = ""  # list source_key for X terms (cross-fit masking)


def _m1() -> dict:
    return json.loads((ROOT / "model/proto/fusion/priors_M1.json").read_text())["priors"]["service"]


def _lg(k: float, n: float) -> float:
    r = (k + 0.5) / (n + 1)
    return math.log(r / (1 - r))


def service_terms() -> list[Term]:
    m1 = _m1()

    def m(name: str, sign: int, fam: str) -> Term:
        return Term(name, fam, sign, m1[name]["mu"], m1[name]["sd"], "priors_M1.json: " + m1[name]["derivation"])

    t = [Term("b0", "base", 0, -2.9, 1.5, "priors_M1 b_<service>: base rate about 5% for a pair no source speaks for")]
    t += [Term(f"b@{c}", "base", 0, 0.0, 1.0, "category deviation of the intercept, N(0, 1)") for c in CATEGORIES]
    t += [Term(f"b@{s}", "base", 0, 0.0, 0.5, "service deviation, shrunk to its category, N(0, 0.5^2)") for s in SERVICES]
    t += [m(f"t{v}", +1, "T") for v in range(1, 6)] + [m("trunc0", +1, "T"), m("c1", -1, "C"), m("c2", -1, "C"),
                                                      m("n1", -1, "N"), m("s1", -1, "S"), m("p1", +1, "P"), m("p2", +1, "P")]
    t += [
        # The three discounts are capped so that t2 + tx_urls30 + tx_public >= 0 holds at the prior means (t2 = 0.46):
        # the M1 values (tb_high -0.86) would let one more own unit lower the score before any data is seen.
        Term("tx_urls10", "T", -1, -0.15, 0.75, "contamination prior on own text (T >= 2) at 10-29 source URLs; M1 tb_mid -0.43, capped"),
        Term("tx_urls30", "T", -1, -0.3, 0.75, "contamination prior on own text at 30+ URLs; M1 tb_high -0.86 (merge audit 59.6% vs 4.2%), capped"),
        Term("tx_public", "T", -1, -0.15, 0.75, "contamination prior on own text in public records: PATTERNS 1, 49.8% vs 32.2% carry another "
             "facility's text (adjusted OR 2.34); capped by the monotone rule"),
    ]
    for d in DEV_TERMS:
        fam = "P" if d.startswith("p") else "T"
        t += [Term(f"{d}@{c}", fam, 0, 0.0, 0.5, "category deviation N(0, 0.5^2)") for c in CATEGORIES]
        t += [Term(f"{d}@{s}", fam, 0, 0.0, 0.5, "service deviation N(0, 0.5^2), shrunk to the category term") for s in SERVICES]
    t += [
        Term("x_nabh_code", "X", +1, 1.5, 1.0, "NABH service code (DIA); match 39/40; a code names the service itself", "nabh"),
        Term("x_nabh_dept", "X", +1, 1.0, 1.0, "NABH department code (NPH, OBG, EMD, CAR, ONC, TRN); match 39/40; a department, not the service", "nabh"),
        Term("x_nabh_proxy", "X", +1, 0.5, 1.0, "NABH department used as a proxy (CAR for cath lab, STEMI); weaker than a department", "nabh"),
        Term("x_nmc_dept", "X", +1, 0.8, 1.0, "NMC strong PG course; match 19/20; shows a department, not that the service runs today", "nmc"),
        Term("x_nmc_support", "X", +1, 0.4, 1.0, "NMC support course (value 0.5); half the strong course", "nmc"),
        Term("x_laqshya_valid", "X", +1, 1.5, 1.0, "valid LaQshya certificate (Maternity OT, Labour Room); match 17/20, service-specific", "laqshya"),
        Term("x_laqshya_expired", "X", +1, 0.75, 1.0, "expired LaQshya certificate: stated once, half the valid weight", "laqshya"),
        Term("x_mohfw", "X", +1, 1.0, 1.0, "MoHFW trauma care facility; match 19/20, but 12th-plan rows were not functional in 2019", "mohfw_tcf"),
        Term("x_erk_service", "X", +1, 2.0, 1.0, "e-RaktKosh blood centre at the facility (the service itself for blood_bank); 16/20 strict", "eraktkosh"),
        Term("x_erk_prereq", "X", +1, 0.3, 0.75, "e-RaktKosh blood centre as a prerequisite (C-section, trauma, burns, cardiac surgery)", "eraktkosh"),
        Term("x_pmndp", "X", +1, 1.5, 1.0, "PMNDP Goa dialysis centre list (1 match, 1/1)", "pmndp_goa"),
        Term("w_ab", "W", +1, 2.0, 1.0, f"own website cell A or B; QA 16/16 (logit {_lg(16, 16):.2f}); 2.0 because T usually co-fires"),
        Term("w_c", "W", +1, round(_lg(8, 14), 2) + 1.0, 1.0, f"own website cell C; QA 8/14, logit {_lg(8, 14):.2f} + 1.0 over the base"),
        Term("w_de", "W", +1, 0.5, 1.0, "own website cell D or E (weak); QA 12/30"),
        Term("w_24x7", "W", +1, 0.7, 1.0, "own website states 24x7 emergency (QA 9/10); emergency_24x7, trauma_care, emergency_csection only"),
        Term("w_silent", "W", -1, -0.3, 0.75, "attributable website observed and says nothing about the service (absent, not not-observable)"),
        Term("w_negated", "W", -1, -1.0, 1.0, "website line negates the service (guard)"),
        Term("o_tag", "O", +1, 0.5, 1.0, "OSM speciality or emergency=yes tag for the service; tier precision 17/20"),
        Term("d_detail", "D", +1, 0.5, 1.0, "dataset detail for the service (unit 24x7, equipment count, unit beds); 46/50; same text as T"),
        Term("k_iphs1", "K", +1, 0.5, 0.75, "IPHS 2022: essential at this public level (M1 iphs_essential)"),
        Term("k_iphs05", "K", +1, 0.25, 0.75, "IPHS 2022: desirable or size dependent at this level"),
        Term("k_iphs0", "K", -1, -0.5, 0.75, "IPHS 2022: not expected at this public level (an official standard, not an absence)"),
        Term("r1", "R", +1, 0.5, 1.0, "reader p_offers >= 0.5 (issue #50 slot; empty when this ran)"),
        Term("r2", "R", +1, 0.5, 1.0, "reader p_offers >= 0.9 (slot)"),
        Term("public", "context", 0, 0.0, 1.0, "operator public (operatorTypeId); no prior direction"),
        Term("operator_unknown", "context", 0, 0.0, 1.0, "operator not stated"),
        Term("hospital", "context", 0, 0.5, 1.0, "retyped facility type hospital; M1 type_clinic -0.5 mirrored"),
        Term("beds_missing", "context", 0, 0.0, 1.0, "M1"), Term("beds_lt30", "context", 0, -0.5, 1.0, "M1"),
        Term("beds_100p", "context", 0, 0.5, 1.0, "M1"),
        Term("spec_lt5", "context", 0, -0.3, 1.0, "M1 breadth_lt5"), Term("spec_20p", "context", 0, 0.3, 1.0, "M1 breadth_20p"),
        Term("urls_lt3", "context", 0, 0.0, 1.0, "record breadth main effect (FEATURES: broad records confirmed more often)"),
        Term("urls_30p", "context", 0, 0.0, 1.0, "record breadth main effect"),
        Term("web_none", "context", 0, 0.0, 1.0, "web_state none (PATTERNS 3); free sign, public facilities lack sites"),
        Term("web_dead", "context", 0, 0.0, 1.0, "web_state dead"),
        Term("social_high", "context", -1, -0.3, 0.75, "social-media share of sources >= 0.5; FEATURES: the most negative feature"),
        Term("nabh_listed", "context", 0, 0.3, 1.0, "facility on the NABH list (NaN for public without a match: 0)"),
        Term("k_text_nabh", "context", 0, 0.3, 1.0, "record text says NABH"),
        Term("k24_text", "context", +1, 0.5, 1.0, "record text says this service runs 24x7"),
        Term("scale_contra", "context", -1, -0.5, 1.0, "M1 scale_contradiction (guard)"),
    ]
    t += [Term(f"off@{f}", "offset", 0, 0.0, 2.5, "PU scope offset for this list family; not part of any published score") for f in PU_FAMILIES]
    return t


WEB_COLS = ("w_ab", "w_c", "w_de", "w_24x7", "w_silent", "w_negated", "urls_lt3", "urls_30p", "tx_urls10", "tx_urls30",
            "web_none", "web_dead", "social_high")  # crossfit plan gold_web_check ablation (website + cited-source columns)
NABH_SCOPE_COLS = ("nabh_listed",)  # constant inside the NABH scope (crossfit plan scope + drop)


def x_witnesses() -> pd.DataFrame:
    """Per (unique_id, service): max value of present X witnesses by (source_key, role), as wide columns."""
    import duckdb
    q = f"""select unique_id, service, split_part(source_key, ':', 1) sk, role, max(value) v
            from '{DER}/witnesses.parquet' where family = 'X' and observability = 'present' and service != '*'
            group by all"""
    d = duckdb.sql(q).df()
    key = {("nabh", "service_code"): "x_nabh_code", ("nabh", "department"): "x_nabh_dept",
           ("nabh", "department_proxy"): "x_nabh_proxy", ("nmc", "department"): "x_nmc_dept",
           ("nmc", "department_support"): "x_nmc_support", ("mohfw_tcf", "designation"): "x_mohfw",
           ("eraktkosh", "service"): "x_erk_service", ("eraktkosh", "prerequisite"): "x_erk_prereq",
           ("pmndp_goa", "service"): "x_pmndp"}
    d["col"] = [key.get((s, r)) for s, r in zip(d.sk, d.role)]
    lq = d.sk.eq("laqshya")
    d.loc[lq, "col"] = np.where(d.v[lq] >= 1, "x_laqshya_valid", "x_laqshya_expired")
    assert d.col.notna().all(), d[d.col.isna()][["sk", "role"]].drop_duplicates()
    d["one"] = 1.0
    return d.pivot_table(index=["unique_id", "service"], columns="col", values="one", aggfunc="max").reset_index()


def load_pairs() -> pd.DataFrame:
    """facility_features joined with the X witness columns; one row per (facility, service)."""
    ff = pd.read_parquet(DER / "facility_features.parquet")
    xw = x_witnesses()
    ff = ff.merge(xw, on=["unique_id", "service"], how="left")
    return ff


def service_X(df: pd.DataFrame, terms: list[Term]) -> np.ndarray:
    """Design matrix (n x len(terms)); offset columns are 0 here (set per PU row by the caller)."""
    n = len(df)
    T = df.a_T.to_numpy()
    svc = df.service.to_numpy()
    urls = df.c_n_urls.to_numpy()
    pub = df.operator_public.to_numpy()
    beds = df.g_log_beds.to_numpy()
    nsp = df.g_n_specialties.to_numpy()
    cell = df.e_web_cell.fillna("").to_numpy()
    iphs = df.g_iphs_prior.to_numpy()
    rp = df.r_reader_p_offers.to_numpy()
    one = lambda c: df[c].fillna(0).to_numpy() >= 1  # noqa: E731  NaN (not observable) -> 0
    cols = {"b0": np.ones(n, bool)}
    for c, ss in CATEGORIES.items():
        cols[f"b@{c}"] = np.isin(svc, ss)
    for s in SERVICES:
        cols[f"b@{s}"] = svc == s
    for v in range(1, 6):
        cols[f"t{v}"] = T >= v
    cols.update(trunc0=(T == 0) & (df.a_list_truncated.to_numpy() >= 1), c1=df.a_contamination.to_numpy() >= 1,
                c2=df.a_contamination.to_numpy() >= 2, n1=df.a_negation.to_numpy() >= 1, s1=df.a_scope_conflict.to_numpy() >= 1,
                p1=df.a_prereq.to_numpy() >= 1, p2=df.a_prereq.to_numpy() >= 2,
                tx_urls10=(T >= 2) & (urls >= 10) & (urls < 30), tx_urls30=(T >= 2) & (urls >= 30), tx_public=(T >= 2) & (pub == 1))
    for d in DEV_TERMS:
        for c, ss in CATEGORIES.items():
            cols[f"{d}@{c}"] = cols[d] & np.isin(svc, ss)
        for s in SERVICES:
            cols[f"{d}@{s}"] = cols[d] & (svc == s)
    for c in ("x_nabh_code", "x_nabh_dept", "x_nabh_proxy", "x_nmc_dept", "x_nmc_support", "x_laqshya_valid",
              "x_laqshya_expired", "x_mohfw", "x_erk_service", "x_erk_prereq", "x_pmndp"):
        cols[c] = one(c) if c in df else np.zeros(n, bool)
    cols.update(w_ab=np.isin(cell, ["A", "B"]), w_c=cell == "C", w_de=np.isin(cell, ["D", "E"]),
                w_24x7=one("e_web_24x7_emergency") & np.isin(svc, list(W24_SERVICES)),
                w_silent=df.obs_W.to_numpy() == "absent", w_negated=one("e_web_negated"),
                o_tag=df.obs_O.to_numpy() == "present", d_detail=df.obs_D.to_numpy() == "present",
                k_iphs1=iphs == 1, k_iphs05=iphs == 0.5, k_iphs0=iphs == 0,
                r1=np.nan_to_num(rp, nan=0) >= 0.5, r2=np.nan_to_num(rp, nan=0) >= 0.9,
                public=pub == 1, operator_unknown=np.isnan(pub), hospital=one("g_type_hospital"),
                beds_missing=np.isnan(beds), beds_lt30=beds < math.log10(30), beds_100p=beds >= 2.0,
                spec_lt5=nsp < 5, spec_20p=nsp >= 20, urls_lt3=urls < 3, urls_30p=urls >= 30,
                web_none=df.web_state.to_numpy() == "none", web_dead=df.web_state.to_numpy() == "dead",
                social_high=df.c_share_social.fillna(0).to_numpy() >= 0.5, nabh_listed=one("d_nabh_listed"),
                k_text_nabh=one("k_text_nabh"), k24_text=one("k_text_service_24x7"), scale_contra=one("b_scale_contradiction"))
    for f in PU_FAMILIES:
        cols[f"off@{f}"] = np.zeros(n, bool)
    return np.column_stack([np.asarray(cols[t.name], float) for t in terms])


def service_constraints(terms: list[Term]) -> np.ndarray:
    """Rows of A with A @ beta >= 0: signs, then monotone composites for every service."""
    idx = {t.name: i for i, t in enumerate(terms)}
    rows = []

    def row(pairs):
        r = np.zeros(len(terms))
        for nm, c in pairs:
            r[idx[nm]] += c
        rows.append(r)

    for t in terms:
        if t.sign:
            row([(t.name, float(t.sign))])
    for s in SERVICES:
        c = CAT_OF[s]
        for d in DEV_TERMS:
            row([(d, 1.0), (f"{d}@{c}", 1.0), (f"{d}@{s}", 1.0)])
        # one more own unit never lowers the score, even on the broadest public record
        row([("t2", 1.0), ("t2@" + c, 1.0), ("t2@" + s, 1.0), ("tx_urls30", 1.0), ("tx_public", 1.0)])
        row([("t2", 1.0), ("t2@" + c, 1.0), ("t2@" + s, 1.0), ("tx_urls10", 1.0), ("tx_public", 1.0)])
    row([("t1", 1.0), ("trunc0", -1.0)])  # leaving T = 0 on a truncated record never lowers the score
    return np.array(rows)


# ---------- location head P_L ----------
VOTES = ["vote_coords", "vote_pin", "vote_city", "vote_name_place", "vote_state", "vote_text_pin", "vote_map_link"]


def location_terms() -> list[Term]:
    m1 = json.loads((ROOT / "model/proto/fusion/priors_M1.json").read_text())["priors"]["location"]
    mp = {"vote_coords": "v_coords", "vote_pin": "v_pin", "vote_city": "v_city", "vote_name_place": "v_name", "vote_state": "v_state"}
    t = [Term("b_loc", "base", 0, m1["b_loc"]["mu"], m1["b_loc"]["sd"], "priors_M1: " + m1["b_loc"]["derivation"])]
    t += [Term("src_pin", "context", 0, m1["src_pin"]["mu"], 1.0, "priors_M1"), Term("src_city", "context", 0, -0.5, 1.0, "priors_M1"),
          Term("src_map", "context", 0, 0.5, 1.0, "priors_M1")]
    for v in VOTES:
        if v in mp:
            t.append(Term(v, "vote", +1, m1[mp[v]]["mu"], m1[mp[v]]["sd"], "priors_M1 " + mp[v] + " (x = -1 / 0 / +1)"))
        else:
            t.append(Term(v, "vote", +1, 0.5, 0.75, "expert: a PIN written in text or a name-matched map link, half the PIN vote"))
    t += [Term("f_copied_geocode", "flag", -1, -1.0, 0.75, "priors_M1"), Term("f_coords_look_wrong", "flag", -1, -0.5, 0.75, "priors_M1"),
          Term("f_pin_looks_wrong", "flag", -1, -0.5, 0.75, "priors_M1"),
          Term("f_osm_conflict", "flag", -1, -0.3, 0.75, "OSM conflict, 4/15 are really the facility (ablate: matcher gate)"),
          Term("nabh_listed", "context", +1, round(-math.log(0.49), 2), 0.5, "PATTERNS 4: NABH match halves drift odds, OR 0.49 (0.40-0.60)"),
          Term("pmjay_text", "context", -1, round(-math.log(1.59), 2), 0.5, "PATTERNS 4: PM-JAY text drift OR 1.59 (weak drift risk)"),
          Term("web_none", "context", -1, round(-math.log(1.51), 2), 0.5, "PATTERNS 3: no website drift OR 1.51"),
          Term("breadth", "context", -1, round(-math.log(2.45) / 2, 2), 0.5,
               "PATTERNS 5: drift OR 2.45 per doubling of URLs, halved (drift is broader than > 25 km); x = log2(URLs) - 3")]
    return t


def location_X(fac: pd.DataFrame, terms: list[Term]) -> np.ndarray:
    n = len(fac)
    cols = {"b_loc": np.ones(n), "src_pin": fac.p1_src.eq("postcode_centre"), "src_city": fac.p1_src.eq("address_city_centre"),
            "src_map": fac.p1_src.eq("map_link"), "f_copied_geocode": fac.copied_geocode, "f_coords_look_wrong": fac.coords_look_wrong,
            "f_pin_looks_wrong": fac.pin_looks_wrong, "f_osm_conflict": fac.f_osm_conflict.fillna(0) >= 1,
            "nabh_listed": fac.d_nabh_listed.fillna(0) >= 1, "pmjay_text": fac.k_text_pmjay.fillna(0) >= 1,
            "web_none": fac.web_state.eq("none"), "breadth": fac.c_log2_n_urls.to_numpy() - 3.0}
    for v in VOTES:
        cols[v] = fac[v].to_numpy()
    return np.column_stack([np.asarray(cols[t.name], float) for t in terms])


def sign_rows(terms: list[Term]) -> np.ndarray:
    rows = []
    for i, t in enumerate(terms):
        if t.sign:
            r = np.zeros(len(terms))
            r[i] = t.sign
            rows.append(r)
    return np.array(rows)


if __name__ == "__main__":
    st = service_terms()
    names = [t.name for t in st]
    assert len(names) == len(set(names)), "duplicate term"
    df = pd.DataFrame(dict(unique_id=["u"] * 2, service=["dialysis", "mri"], a_T=[2.0, 0.0], a_list_truncated=[0.0, 1.0],
                           a_contamination=[0.0, 0.0], a_negation=[0.0, 0.0], a_scope_conflict=[0.0, 0.0], a_prereq=[1.0, 0.0],
                           c_n_urls=[40.0, 2.0], operator_public=[1.0, np.nan], g_log_beds=[np.nan, 2.5], g_n_specialties=[3.0, 25.0],
                           e_web_cell=["A", None], g_iphs_prior=[1.0, np.nan], r_reader_p_offers=[np.nan, np.nan],
                           e_web_24x7_emergency=[1.0, np.nan], obs_W=["present", "not_observable"], e_web_negated=[0.0, np.nan],
                           obs_O=["absent", "absent"], obs_D=["absent", "absent"], g_type_hospital=[1.0, 0.0], web_state=["alive", "none"],
                           c_share_social=[0.0, 0.6], d_nabh_listed=[np.nan, 0.0], k_text_nabh=[0.0, 0.0],
                           k_text_service_24x7=[np.nan, np.nan], b_scale_contradiction=[0.0, 0.0], x_nabh_dept=[1.0, np.nan]))
    X = service_X(df, st)
    g = dict(zip(names, X[0]))
    assert g["t2"] == 1 and g["t3"] == 0 and g["tx_urls30"] == 1 and g["tx_public"] == 1 and g["w_ab"] == 1 and g["w_24x7"] == 0
    assert g["x_nabh_dept"] == 1 and g["k_iphs1"] == 1 and g["b@kidney"] == 1 and g["t2@dialysis"] == 1 and g["beds_missing"] == 1
    h = dict(zip(names, X[1]))
    assert h["trunc0"] == 1 and h["web_none"] == 1 and h["operator_unknown"] == 1 and h["w_silent"] == 0 and h["x_nabh_dept"] == 0
    A = service_constraints(st)
    beta = np.array([t.mu for t in st])
    assert (A @ beta >= -1e-9).all(), np.where(A @ beta < -1e-9)[0]  # candidate A means are feasible
    lt = location_terms()
    print("design ok:", len(st), "service terms,", A.shape[0], "constraints,", len(lt), "location terms")
