"""Feature matrices for candidate C (EBM, interactions off).

Each term has a family (for the per-family summaries and the card), a monotone sign for the EBM,
and an anchor: the value whose contribution is published as exactly 0. Anchors only move a
constant between a term and the base, so they never change a score.

Coding rules from PATTERNS.md and LABELS.md:
- List features (family X) are 1 when the list states the fact and NaN otherwise. Absent and
  not observable share the NaN bin, which is anchored at 0, and a present value below 0 is clamped
  (glassbox.clamp_list_terms), so a list can only add evidence.
- Website features are NaN when the facility has no attributable website (not observable); the
  NaN bin is anchored at 0.
- The IPHS prior is NaN outside public facilities with a known level and anchored at 0 there.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

ROOT = "/Users/karthikvattem/projects/datathon"
FF_PATH = f"{ROOT}/derived/v2/facility_features.parquet"
LABEL_DIR = f"{ROOT}/model/v2/labels/out"

WEB_CELL_RANK = {"A": 5.0, "B": 4.0, "C": 3.0, "D": 2.0, "E": 1.0}


@dataclass(frozen=True)
class Term:
    name: str
    family: str
    sign: int          # +1 increasing, -1 decreasing, 0 free (EBM monotone_constraints)
    kind: str          # continuous or nominal
    anchor: object     # value published as contribution 0; np.nan means the missing bin


NAN = np.nan
# P_S terms. Families: T text, C contamination, N non-offer, S scope, P prerequisites, X lists,
# W website, D dataset details, K public-standard prior, R reader, G context.
PS_TERMS: tuple[Term, ...] = (
    Term("a_T", "T", 1, "continuous", 0.0),
    Term("a_spec_weight", "T", 1, "continuous", 0.0),
    Term("a_list_truncated", "T", 0, "continuous", 0.0),
    Term("a_contamination", "C", -1, "continuous", 0.0),
    Term("a_negation", "N", -1, "continuous", 0.0),
    Term("a_scope_conflict", "S", -1, "continuous", 0.0),
    Term("a_prereq", "P", 1, "continuous", 0.0),
    Term("x_nabh_service_code", "X", 1, "continuous", NAN),
    Term("x_nabh_full_accreditation", "X", 1, "continuous", NAN),
    Term("x_nmc_course_strong", "X", 1, "continuous", NAN),
    Term("x_laqshya_ot_valid", "X", 1, "continuous", NAN),
    Term("x_mohfw_trauma_centre", "X", 1, "continuous", NAN),
    Term("x_erk_blood_centre_on_site", "X", 1, "continuous", NAN),
    Term("e_web_strength", "W", 1, "continuous", NAN),
    Term("e_web_negated", "W", -1, "continuous", NAN),
    Term("web_state", "W", 0, "nominal", "none"),
    Term("c_log2_n_urls", "G", 0, "continuous", 0.0),
    Term("d_any_detail", "D", 1, "continuous", 0.0),
    Term("g_iphs_prior", "K", 1, "continuous", NAN),
    Term("operator_public", "G", 0, "continuous", NAN),
    Term("g_type_hospital", "G", 0, "continuous", 0.0),
    Term("g_log_beds", "G", 0, "continuous", NAN),
    Term("g_n_specialties", "G", 0, "continuous", 0.0),
    Term("k_text_24x7_any", "G", 0, "continuous", 0.0),
    Term("k_text_nabh", "G", 0, "continuous", 0.0),
    Term("k_text_pmjay", "G", 0, "continuous", 0.0),
    Term("r_reader_p_offers", "R", 1, "continuous", NAN),
)
SERVICE_TERM = Term("service", "G", 0, "nominal", "dialysis")

# Source column -> recoded list feature (1 or NaN).
LIST_SOURCES = {
    "x_nabh_service_code": "d_nabh_service_code",
    "x_nabh_full_accreditation": "d_nabh_full_accreditation",
    "x_nmc_course_strong": "d_nmc_course_strong",
    "x_laqshya_ot_valid": "d_laqshya_ot_valid",
    "x_mohfw_trauma_centre": "d_mohfw_trauma_centre",
    "x_erk_blood_centre_on_site": "d_erk_blood_centre_on_site",
}

# Website and cited-source columns shared with the gold web check (crossfit plan "ablate").
WEB_ABLATE = ("e_web_strength", "e_web_negated", "web_state", "c_log2_n_urls")

# P_L terms (facility level). b_loc_conf and b_coord_pin_km are dropped (tuned on gold).
PL_TERMS: tuple[Term, ...] = tuple(
    Term(v, "L_vote", 1, "continuous", 0.0)
    for v in ("vote_coords", "vote_pin", "vote_city", "vote_name_place", "vote_state",
              "vote_text_pin", "vote_map_link")
) + (
    Term("b_city_points_elsewhere", "L_flag", -1, "continuous", 0.0),
    Term("b_copied_geocode", "L_flag", -1, "continuous", 0.0),
    Term("coords_look_wrong", "L_flag", -1, "continuous", 0.0),
    Term("pin_looks_wrong", "L_flag", -1, "continuous", 0.0),
    Term("a_quarantine_share", "L_flag", 0, "continuous", 0.0),
    Term("p1_src", "L_context", 0, "nominal", "listing_coordinates"),
    Term("f_osm_conflict", "L_selection", -1, "continuous", 0.0),
    Term("f_osm_match", "L_selection", 1, "continuous", 0.0),
    Term("d_nabh_listed", "L_selection", 1, "continuous", NAN),
)
PL_ABLATE = ("f_osm_conflict", "f_osm_match", "d_nabh_listed")


def load_features() -> pd.DataFrame:
    """facility_features with the derived columns candidate C uses."""
    ff = pd.read_parquet(FF_PATH)
    extra = {
        new: ff[src].where(ff[src] == 1.0) for new, src in LIST_SOURCES.items()
    }
    strength = ff["e_web_cell"].map(WEB_CELL_RANK)
    extra["e_web_strength"] = strength.where(ff["e_web_service"] != 0.0, 0.0).where(
        ff["e_web_service"].notna())
    for col in ("coords_look_wrong", "pin_looks_wrong"):
        extra[col] = ff[col].astype(float)
    return ff.assign(**extra)


def active_terms(terms: tuple[Term, ...], frame: pd.DataFrame,
                 drop: tuple[str, ...] = ()) -> tuple[Term, ...]:
    """Terms present in the frame with at least one non-missing value, minus `drop`.

    The reader slot r_reader_p_offers is all NaN until issue #50 lands, so it drops out here and
    enters automatically when derived/v2/reader_scores.parquet is built into the features.
    """
    return tuple(t for t in terms
                 if t.name not in drop and t.name in frame and frame[t.name].notna().any())


def matrix(frame: pd.DataFrame, terms: tuple[Term, ...]) -> pd.DataFrame:
    out = frame[[t.name for t in terms]].copy()
    for t in terms:
        out[t.name] = out[t.name].astype(str if t.kind == "nominal" else float)
    return out


def anchor_row(terms: tuple[Term, ...]) -> pd.DataFrame:
    return pd.DataFrame([{t.name: t.anchor for t in terms}]).pipe(
        lambda d: d.astype({t.name: (str if t.kind == "nominal" else float) for t in terms}))


def family_mask_columns(plan: pd.DataFrame, terms: tuple[Term, ...]) -> dict[str, list[str]]:
    """Per PU label family: the active term columns its rows must not see (drop + ablate).

    The plan names source columns (d_nabh_service_code); the recoded x_ names map back to them.
    """
    source_of = {t.name: LIST_SOURCES.get(t.name, t.name) for t in terms}
    out: dict[str, list[str]] = {}
    for fam, rows in plan[plan.label_table == "pu_labels.parquet"].groupby("label_family"):
        named = set()
        for col in ("drop_columns", "ablate_columns"):
            for cell in rows[col]:
                named |= {c for c in str(cell).split(",") if c}
        out[fam] = [t for t, src in source_of.items() if src in named or t in named]
    return out
