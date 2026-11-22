"""Shared paths, the 36-service list, the source precision registry and the IPHS level prior for the
v2 witness knowledge base (model/v2/assemble). Named acommon so it never shadows
model/proto/evidence/common.py, which this folder imports read-only.

Self-check: /Users/karthikvattem/projects/datathon/.venv-viz/bin/python acommon.py
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/karthikvattem/projects/datathon")
HERE = Path(__file__).resolve().parent
OUT = ROOT / "derived/v2"
PROTO_EV = ROOT / "model/proto/evidence"
TAX = ROOT / "kb/taxonomy"
EXT = ROOT / "data/external"
TODAY = pd.Timestamp("2026-11-21")

# proto evidence modules (atoms, facility) are imported read-only; they import their own common.py
for p in (str(PROTO_EV),):
    if p not in sys.path:
        sys.path.insert(0, p)

SERVICES_JSON = json.loads((TAX / "services.json").read_text())
SERVICES: list[str] = [s["id"] for c in SERVICES_JSON["categories"] if c["id"] != "candidate" for s in c["services"]]
assert len(SERVICES) == 36 and "palliative_care" not in SERVICES and "trauma_care" in SERVICES, SERVICES
ALIASES = {"trauma_emergency": "trauma_care"}   # MODEL_SPEC v1 key -> taxonomy id

FAMILIES = {"T": "own text", "C": "contamination", "N": "non-offer", "S": "scope", "P": "prerequisites",
            "X": "official list", "W": "website", "O": "open data", "D": "dataset details", "R": "reader slot",
            "K": "context"}


def wilson(k: float, n: float, z: float = 1.959964) -> tuple[float, float]:
    """95% Wilson interval; (nan, nan) when n == 0."""
    if not n:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 4), round(c + h, 4))


# Hand-checked precision per source, (k, n, what it measures, where). Every row is copied from the named file.
# A witness row carries source_key; build.py joins k, n and the basis from here.
PRECISION = {
    # T family: share of sentences of this role that say the service is provided (support), sentence labels
    "vf_text:offer": (96, 100, "sentence says the service is provided (role offer)", "model/proto/evidence/attribution_rates.csv role:offer"),
    "vf_text:unit_or_equipment": (53, 61, "sentence says the service is provided (role unit_or_equipment)", "model/proto/evidence/attribution_rates.csv role:unit_or_equipment"),
    "vf_text:quantity": (2, 2, "sentence says the service is provided (role quantity)", "model/proto/evidence/attribution_rates.csv role:quantity"),
    "vf_text:weak": (17, 17, "list item names the service (role list)", "model/proto/evidence/attribution_rates.csv role:list"),
    "vf_specialty": (39, 40, "specialty value maps to the right service (fresh v1.1 sample); value is the specialty evidence weight", "kb/taxonomy/TAXONOMY.md specialty map hand checks"),
    # C family: share of rejections that really were about another facility (1 - own rate)
    "vf_reject:names_other_facility": (14, 18, "rejected sentence is really about another facility", "model/proto/evidence/attribution_rates.csv ownership:other_facility"),
    "vf_reject:ambiguous_reference": (9, 16, "rejected sentence is really about another facility", "model/proto/evidence/attribution_rates.csv ownership:ambiguous"),
    "vf_reject:sibling_branch": (10, 10, "rejected sentence is really about another branch", "model/proto/evidence/attribution_rates.csv ownership:sibling"),
    "vf_reject:other_state_place": (0, 2, "rejected sentence is really about another place", "model/proto/evidence/attribution_rates.csv ownership:other_place"),
    "vf_reject:quarantined_merge": (17, 23, "cleaning other-facility flag true positive", "model/proto/evidence/attribution_rates.csv seed:cleaning_other_facility_TP"),
    "vf_nonoffer": (34, 40, "non-offer cue read correctly", "model/proto/evidence/attribution_rates.csv seed:nonoffer_v2_cue_correct"),
    "scope_rule": (44, 111, "single-focus facility did NOT offer the claimed service (G_scope hand check: 67 true, 44 false)", "derived/v1/README.md evidence rules G_scope"),
    "prereq_text": (None, None, "not hand-checked", ""),
    # X family: entity-match precision of each list (the list's service meaning is a separate caveat, see note)
    "nabh": (39, 40, "NABH-to-VF match correct (two seeds of 20)", "external/nabh_accredited/README.md"),
    "nmc": (19, 20, "NMC college-to-VF match correct", "external/nmc_colleges/README.md"),
    "laqshya": (17, 20, "LaQshya facility-to-VF match correct (3 more plausible, 0 wrong)", "external/laqshya_master/README.md"),
    "mohfw_tcf": (19, 20, "MoHFW trauma care facility-to-VF match correct", "external/mohfw_trauma_196/README.md"),
    "eraktkosh": (16, 20, "e-RaktKosh centre-to-VF match correct (strict; 18/20 counting likely)", "external/eraktkosh_blood_centres/README.md"),
    "pmndp_goa": (1, 1, "PMNDP Goa centre-to-VF match correct (recall 1/8)", "external/pmndp_counts_and_state_lists/README.md"),
    # W family: QA evidence-structure cells (strength x pages x line kind), 60-pair service QA
    "web:A": (13, 13, "strong quote on 2+ pages: page says facility provides service now", "kb/web_evidence/qa/QA.md cell A"),
    "web:B": (3, 3, "strong quote, 1 page, list item", "kb/web_evidence/qa/QA.md cell B"),
    "web:C": (8, 14, "strong quote, 1 page, sentence", "kb/web_evidence/qa/QA.md cell C"),
    "web:D": (5, 12, "weak quote on 2+ pages", "kb/web_evidence/qa/QA.md cell D"),
    "web:E": (7, 18, "weak quote, 1 page", "kb/web_evidence/qa/QA.md cell E"),
    "web:negated": (None, None, "none of 12 sampled negated items was an explicit 'we do not offer'", "kb/web_evidence/WEB_EVIDENCE.md self-check"),
    "web:hours_24x7_emergency": (9, 10, "24x7 emergency fact correct", "kb/web_evidence/qa/out/qa_results.json hrs_emergency_24x7"),
    # O family: kb/opendata tiers (identity of the match only)
    "osm:high": (17, 20, "OSM/Wikidata match correct, high tier, out-of-sample validation", "kb/opendata/OPENDATA.md"),
    "osm:medium": (7, 10, "OSM/Wikidata match correct, medium tier (pooled, in-sample)", "kb/opendata/OPENDATA.md"),
    "osm:conflict": (4, 15, "same-name match is really the facility (conflict tier: location warning)", "kb/opendata/OPENDATA.md"),
    # D family: vf_details extraction precision by fact type (extraction against the sentence, not truth)
    "vf_details:all": (46, 50, "fact type, value and polarity are what the sentence says", "kb/vf_details/out/handcheck.json"),
    # K family
    "iphs_reading": (None, None, "hand reading of services.json iphs.expected_from; not hand-checked", "kb/taxonomy/services.json"),
}
VF_DETAILS_BY_TYPE = {  # kb/vf_details/out/handcheck.json by_type (correct, n)
    "accreditation": (4, 5), "ambulance": (4, 4), "blood_centre": (4, 4), "empanelment": (6, 6),
    "equipment_count": (4, 4), "free_or_government": (3, 4), "hours_24x7": (6, 6), "hours_dialysis_shifts": (2, 2),
    "opd_hours": (4, 4), "staffing": (3, 5), "unit_beds": (6, 6)}

# IPHS 2022 level prior for PUBLIC facilities: 1 = essential at that level, 0.5 = desirable or only at some
# sizes/FRU, 0 = not expected. A hand reading of services.json iphs.expected_from (quoted per row in IPHS_TEXT
# below). Levels from the name: phc, chc, sdh, dh, mc. ponytail: one table, no bed-size split; add the size
# conditions (for example CT essential only at 200+ bed DH) when the model can use beds for public rows.
IPHS_LEVELS = ["phc", "chc", "sdh", "dh", "mc"]
_I = {  # service: (phc, chc, sdh, dh, mc)
    "emergency_24x7": (0.5, 1, 1, 1, 1), "trauma_care": (0, 1, 1, 1, 1), "burn_care": (0, 1, 0.5, 1, 1),
    "orthopaedic_trauma_surgery": (0, 1, 1, 1, 1), "snakebite_antivenom": (1, 1, 1, 1, 1),
    "icu": (0, 0, 1, 1, 1), "picu": (0, 0, 0.5, 1, 1), "ventilator_support": (0, 0, 1, 1, 1),
    "emergency_csection": (0, 0.5, 1, 1, 1), "institutional_delivery": (0.5, 1, 1, 1, 1),
    "high_risk_pregnancy": (0, 0.5, 1, 1, 1), "nicu": (0, 0.5, 1, 1, 1), "safe_abortion_mtp": (0.5, 1, 1, 1, 1),
    "cardiac_surgery": (0, 0, 0, 0, 0.5), "cath_lab_angioplasty": (0, 0, 0, 0, 0.5),
    "stemi_thrombolysis": (0, 0, 0, 0.5, 1), "stroke_care": (0, 0, 0, 0.5, 1), "neurosurgery": (0, 0, 0, 0, 0.5),
    "dialysis": (0, 0, 1, 1, 1), "kidney_transplant": (0, 0, 0, 0, 0), "chemotherapy": (0, 0, 0, 0.5, 0.5),
    "radiotherapy": (0, 0, 0, 0, 0), "surgical_oncology": (0, 0, 0, 0, 0), "mri": (0, 0, 0, 0.5, 1),
    "ct_scan": (0, 0, 0, 0.5, 1), "ultrasound": (0, 0.5, 1, 1, 1), "blood_bank": (0, 0.5, 0.5, 1, 1),
    "psychiatric_care": (0, 0, 0.5, 0.5, 1), "de_addiction": (0, 0, 0, 0, 0), "cataract_surgery": (0, 0.5, 1, 1, 1),
    "eye_emergency": (0, 0, 0, 1, 1), "tb_care": (1, 1, 1, 1, 1), "hiv_art": (0, 0, 0, 0.5, 1),
    "anti_rabies": (1, 1, 1, 1, 1), "paediatric_inpatient": (0, 0.5, 1, 1, 1),
    "nutrition_rehabilitation": (0, 0.5, 0.5, 1, 1),
}
IPHS = {s: dict(zip(IPHS_LEVELS, v)) for s, v in _I.items()}
IPHS_TEXT = {s["id"]: s.get("iphs", {}).get("expected_from", "") for c in SERVICES_JSON["categories"] for s in c["services"]}
assert set(IPHS) == set(SERVICES)

# Public level from the name (MODEL_SPEC v1 evidence build LEVEL_RX, first match wins), applied only to
# facilities whose operator is public.
LEVEL_RX = [
    ("mc", r"medical college|\bAIIMS\b|institute of medical sciences|\bGMCH?\b|government medical"),
    ("dh", r"\b(district|dist\.?|zila|zilla|jilla)\b.{0,20}\bhospital|district (headquarters?|hq)|civil hospital|sadar hospital|\bDH\b"),
    ("sdh", r"sub[- ]?divisional|\bSDH\b|sub[- ]?district hospital|taluk[a]? (general )?hospital|tehsil hospital|rural hospital|area hospital"),
    ("chc", r"community health (centre|center)|\bCHC\b"),
    ("phc", r"primary health (centre|center)|\bU?PHC\b|health (and|&) wellness"),
]
LEVEL_RX = [(k, re.compile(r, re.I)) for k, r in LEVEL_RX]
# name markers of a government facility (overrides a missing operatorTypeId; a stated private operator is kept
# unless the name says government outright)
PUBLIC_NAME = re.compile(r"\bgovt\.?\b|\bgovernment\b|district hospital|civil hospital|sadar hospital|\bzil+a hospital"
                         r"|primary health (centre|center)|community health (centre|center)|\bU?PHC\b|\bCHC\b"
                         r"|sub[- ]?divisional hospital|\bAIIMS\b|\bESIC?\b.{0,10}hospital|municipal|railway hospital"
                         r"|cantonment|military hospital|\bPGIMER\b|\bJIPMER\b", re.I)
STRONG_PUBLIC_NAME = re.compile(r"\bgovt\.?\b|\bgovernment\b|primary health (centre|center)|community health (centre|center)"
                                r"|\bAIIMS\b", re.I)
PRIVATE_NAME = re.compile(r"\bpvt\b|\bprivate limited\b|\bltd\b|\bllp\b", re.I)


def operator(op_type: str | None, name: str | None) -> tuple[str, str]:
    """(public | private | unknown, source). operatorTypeId first; the name fills a gap or overrides
    'private' only on an explicit government word."""
    n = name or ""
    op = (op_type or "").lower()
    if op in ("public", "government"):
        return "public", "operatorTypeId"
    if op == "private":
        return ("public", "name_overrides_operatorTypeId") if STRONG_PUBLIC_NAME.search(n) else ("private", "operatorTypeId")
    if PUBLIC_NAME.search(n):
        return "public", "name"
    if PRIVATE_NAME.search(n):
        return "private", "name"
    return "unknown", "none"


def public_level(name: str | None) -> str:
    for lv, rx in LEVEL_RX:
        if rx.search(str(name or "")):
            return lv
    return "unknown"


def jlist(s) -> list:
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return []
    if isinstance(s, (list, np.ndarray)):
        return list(s)
    try:
        v = json.loads(s)
    except (TypeError, ValueError):
        return []
    return v if isinstance(v, list) else []


def rp(rel: str) -> pd.DataFrame:
    return pd.read_parquet(ROOT / rel)


if __name__ == "__main__":
    assert operator("public", "X") == ("public", "operatorTypeId")
    assert operator(None, "Govt. District Hospital, Gaya")[0] == "public"
    assert operator("private", "Government Medical College Hospital")[0] == "public"
    assert operator("private", "Apollo Hospital") == ("private", "operatorTypeId")
    assert operator(None, "Smile Kraft Dental Clinic") == ("unknown", "none")
    assert public_level("Civil Hospital, Panipat") == "dh" and public_level("CHC Canacona") == "chc"
    assert public_level("Siddharth Hospital") == "unknown"
    assert all(set(v) == set(IPHS_LEVELS) for v in IPHS.values())
    assert wilson(17, 20) == (0.6396, 0.9476)
    print("acommon ok:", len(SERVICES), "services,", len(PRECISION), "precision sources")
