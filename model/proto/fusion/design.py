"""Term tables and design matrices for the three Witness Ledger heads (spec 5.1, 5.2, 5.4).

Every column is a named 0/1 (or -1/0/+1 vote) indicator, so a contribution is weight x value and can be printed.
Ordinal families use cumulative steps (x = 1[T >= v]); with a >= 0 constraint on each step the family is monotone.
Variants (ablations): noown (ownership filter off), noecho (echo collapse off), nobucket (no bucket terms),
nocontext (no context terms).
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from fcommon import SERVICES


@dataclass(frozen=True)
class Term:
    name: str
    group: str        # evidence | context | intercept | deviation
    sign: int         # +1 (>= 0), -1 (<= 0), 0 free
    family: str = ""  # T, C, N, S, P, bucket, context, ...
    service: str = "*"


EVIDENCE = [Term(f"t{v}", "evidence", +1, "T") for v in range(1, 6)] + [
    Term("tb_mid", "evidence", -1, "T"), Term("tb_high", "evidence", -1, "T"), Term("trunc0", "evidence", +1, "T"),
    Term("c1", "evidence", -1, "C"), Term("c2", "evidence", -1, "C"), Term("n1", "evidence", -1, "N"),
    Term("s1", "evidence", -1, "S"), Term("p1", "evidence", +1, "P"), Term("p2", "evidence", +1, "P")]
# x_on / x_absent (external list) and r1 / r2 (role classifier) abstain everywhere in v1: no column, listed in weights
ABSTAIN = [Term("x_on", "evidence", +1, "X"), Term("x_absent", "evidence", -1, "X"),
           Term("r1", "evidence", +1, "R"), Term("r2", "evidence", +1, "R")]
CONTEXT = [Term("g_mid", "context", 0, "bucket"), Term("g_high", "context", 0, "bucket")] + [
    Term(n, "context", s, "context") for n, s in [
        ("type_clinic", 0), ("type_dentist", 0), ("type_other", 0), ("public", 0), ("level_dh", 0), ("level_sdh", 0),
        ("level_chc", 0), ("level_phc", 0), ("level_mc", 0), ("iphs_essential", +1), ("beds_missing", 0), ("beds_lt30", 0),
        ("beds_100p", 0), ("doctors_missing", 0), ("doctors_lt5", 0), ("doctors_20p", 0), ("breadth_lt5", 0),
        ("breadth_20p", 0), ("scale_contradiction", 0)]]
DEV_TERMS = ("t2", "t4", "p1")
INTERCEPTS = [Term(f"b_{s}", "intercept", 0, "intercept", s) for s in SERVICES]
DEVIATIONS = [Term(f"{t}@{s}", "deviation", 0, {"t2": "T", "t4": "T", "p1": "P"}[t], s) for t in DEV_TERMS for s in SERVICES]

LOCATION = [Term("b_loc", "intercept", 0, "intercept"), Term("src_pin", "context", 0, "source"),
            Term("src_city", "context", 0, "source"), Term("src_map", "context", 0, "source")] + [
    Term(v, "evidence", +1, "vote") for v in ["v_coords", "v_pin", "v_city", "v_name", "v_state"]] + [
    Term(f, "evidence", -1, "flag") for f in ["f_copied_geocode", "f_coords_look_wrong", "f_pin_looks_wrong", "f_text_pin_elsewhere"]]
EXISTENCE = [Term("b_ex", "intercept", 0, "intercept")] + [Term(n, "evidence", s, "existence") for n, s in [
    ("e_web_own", +1), ("e_web_other", 0), ("e_phone_shared3", -1), ("e_phone_none", -1), ("e_phone_landline", 0),
    ("e_multi_source", +1), ("e_recency", +1), ("e_nonfacility", -1), ("e_dup_member", 0), ("e_coord_shared3", -1)]]


def service_terms(variant=()):
    ev = [t for t in EVIDENCE if not ("nobucket" in variant and t.name in ("tb_mid", "tb_high"))]
    cx = [] if "nocontext" in variant else [t for t in CONTEXT if not ("nobucket" in variant and t.family == "bucket")]
    return INTERCEPTS + ev + cx + DEVIATIONS


def service_X(df: pd.DataFrame, terms, variant=()) -> np.ndarray:
    T = df["T_noown" if "noown" in variant else "T_noecho" if "noecho" in variant else "T"].to_numpy()
    C = np.zeros(len(df), int) if "noown" in variant else df.C.to_numpy()
    b = df.bucket.to_numpy()
    svc = df.service.to_numpy()
    cols = {}
    for s in SERVICES:
        cols[f"b_{s}"] = svc == s
    for v in range(1, 6):
        cols[f"t{v}"] = T >= v
    cols.update(tb_mid=(T >= 2) & (b == "mid"), tb_high=(T >= 2) & (b == "high"), g_mid=b == "mid", g_high=b == "high",
                trunc0=(T == 0) & df.list_truncated.to_numpy(bool), c1=C >= 1, c2=C >= 2, n1=df.N.to_numpy() >= 1,
                s1=df.S.to_numpy() >= 1, p1=df.P.to_numpy() >= 1, p2=df.P.to_numpy() >= 2)
    ft, lv = df.ftype4.to_numpy(), df.level.to_numpy()
    cols.update(type_clinic=ft == "clinic", type_dentist=ft == "dentist", type_other=ft == "other", public=df.public.to_numpy(bool),
                iphs_essential=df.iphs_essential.to_numpy() == 1, scale_contradiction=df.scale_contradiction.to_numpy(bool))
    for l in ["dh", "sdh", "chc", "phc", "mc"]:
        cols[f"level_{l}"] = lv == l
    for k in ["missing", "lt30", "100p"]:
        cols[f"beds_{k}"] = df.beds_bin.to_numpy() == k
    for k in ["missing", "lt5", "20p"]:
        cols[f"doctors_{k}"] = df.doctors_bin.to_numpy() == k
    for k in ["lt5", "20p"]:
        cols[f"breadth_{k}"] = df.breadth_bin.to_numpy() == k
    for t in DEV_TERMS:
        for s in SERVICES:
            cols[f"{t}@{s}"] = cols[t] & (svc == s)
    return np.column_stack([cols[t.name] for t in terms]).astype(float)


def facility_X(ff: pd.DataFrame, head: str) -> tuple:
    terms = LOCATION if head == "location" else EXISTENCE
    cols = {"b_loc": np.ones(len(ff)), "b_ex": np.ones(len(ff)),
            "src_pin": ff.p1_src.eq("postcode_centre"), "src_city": ff.p1_src.eq("address_city_centre"),
            "src_map": ff.p1_src.eq("map_link"), "e_coord_shared3": ff.coord_dup_names.fillna(0) >= 3}
    for t in terms:
        if t.name not in cols:
            cols[t.name] = ff[t.name]
    return terms, np.column_stack([np.asarray(cols[t.name], float) for t in terms])


def constraints(terms) -> np.ndarray:
    """Rows of A (A beta >= 0): sign constraints plus the composite monotonicity constraints."""
    idx = {t.name: i for i, t in enumerate(terms)}
    rows = []

    def row(pairs):
        r = np.zeros(len(terms))
        for n, c in pairs:
            r[idx[n]] = c
        rows.append(r)

    for t in terms:
        if t.sign:
            row([(t.name, float(t.sign))])
    for t in DEV_TERMS:
        for s in SERVICES:
            if f"{t}@{s}" in idx:
                row([(t, 1.0), (f"{t}@{s}", 1.0)])
                if t == "t2":
                    for g in ("tb_mid", "tb_high"):
                        if g in idx:  # one more own unit on a merged record never lowers the score
                            row([("t2", 1.0), (f"t2@{s}", 1.0), (g, 1.0)])
    if "trunc0" in idx:  # leaving T = 0 on a truncated record never lowers the score
        row([("t1", 1.0), ("trunc0", -1.0)])
    return np.array(rows) if rows else np.zeros((0, len(terms)))
