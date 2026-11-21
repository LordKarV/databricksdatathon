"""Smallest check of the name rules, built from the false matches seen in hand-checks.
Run: .venv/bin/python -I external/hotosm_ind_health_facilities/test_match.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from match import core, distinctive, name_score, norm, tier  # noqa: E402


def pair(a, b):
    na, nb = norm(a), norm(b)
    return name_score({"n": na, "c": core(na)}, {"n": nb, "c": core(nb)})


assert pair("Mission Hospital, Nagercoil", "Mission Hospital") == 100
assert pair("Indo American Dental and Implant Clinic", "Dental Clinic") < 90  # OSM name is all generic
assert pair("Shifaa Hospital", "Hospital") < 90
assert pair("Modern Diagnostic & Research Centre", "RB Diagnostic") < 85
assert tier(100, 9.5, True, 44) is None  # "Siva" vs "Siva Head and Neck Hospital" at 9.5 km
assert tier(100, 0.3, True, 44) == "strong"
assert not distinctive(core(norm("Government Hospital")))
assert not distinctive(core(norm("Government Hospital Padubidri")), "Padubidri")
print("ok")
