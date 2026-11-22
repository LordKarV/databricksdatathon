"""Facility-type fit (#117 B): specialty places are never an option, general hospitals with a wing are. pytest common"""
import pytest

from common.typefit import facility_kinds, fit_mask, fits, kinds_by_id, specialty_only

APP_SERVICES = ("trauma_emergency", "emergency_csection", "burn_care", "cardiac_surgery", "dialysis", "mri", "nicu")


@pytest.mark.parametrize("name", [
    "District Hospital AYUSH Wing",  # an AYUSH wing does not make a general hospital an AYUSH place
    "City Hospital and Dental Care",
    "Mata Chandrakala Hospital Trauma & Dental Center",
    "Shivani Hospital and IVF, Shastri Nagar, Kanpur",
    "Multispeciality Hospital & Eye Centre",
    "Umang IVF and Super Speciality Hospital",
    "Anand Hospital and Eye Centre, Jaipur",
    "Assa Diagnostics & Nursing Home",
    "Ayush Hospital",  # a personal name, not the AYUSH system
    "Siddharth Hospital",
    "Accidental Care Hospital",
    "Mother & Child Hospital",
    "Medicover Woman & Child Hospitals",
    "R Yadav Surgical and Rekha Eye Hospital",
    "Bhagyalatha Hospital - Eye Unit",
    "Shree Netralaya and Maternity Clinic",
    "I Care Diagnostic and Dialysis Center",
])
def test_general_hospital_keeps_every_service(name: str) -> None:
    kinds = facility_kinds(name, "hospital")
    assert kinds == frozenset()
    assert all(fits(kinds, s) for s in APP_SERVICES)


@pytest.mark.parametrize("name, kind", [
    ("Sharma Dental Clinic", "dental"),
    ("The Perfect Smile Multi-Speciality Dental Clinic", "dental"),
    ("Dr. Sharma's AG Dentalcare", "dental"),
    ("Bapuji Dental College and Hospital, Davengere", "dental"),
    ("Aravind Eye Hospital & Research Centre", "eye"),
    ("Sankara Nethralaya", "eye"),
    ("Government Ayurvedic College and Hospital", "ayush"),
    ("Govt. Homoeo Medical College Hospital (Guwahati, Nowgong, Jorhat)", "ayush"),
    ("Markaz Unani Hospital", "ayush"),
    ("District Ayurveda Hospital", "ayush"),
    ("Kanag ENT Superspeciality Centre", "ent"),
    ("Krishna Physiotherapy Clinic", "physio"),
    ("Sanidhya Psychiatric Hospital", "psychiatric"),
    ("Poise Skin Clinic", "skin"),
    ("Dental Zone Hospital", "dental"),
    ("Hazaribag College of Dental Sciences and Hospital", "dental"),
    ("Vedanta Centre For Ophthalmic Sciences", "eye"),
    ("Nelivigi Eye Hospital And Surgical Centre", "eye"),
    ("All India Institute of Ayurveda, New Delhi", "ayush"),
])
def test_specialty_place_offers_no_acute_service(name: str, kind: str) -> None:
    kinds = facility_kinds(name, "clinic")
    assert kind in kinds and specialty_only(kinds)
    assert not any(fits(kinds, s) for s in APP_SERVICES)


def test_type_field_comes_first() -> None:
    assert facility_kinds("Earth Smiles", "dentist") == {"dental"}  # no dental word in the name
    assert not fits(facility_kinds("Siri Dental Hospital", "dentist"), "trauma_emergency")


def test_ivf_and_diagnostic_offer_only_their_part() -> None:
    ivf = facility_kinds("Sunrise IVF Centre", "clinic")
    assert fits(ivf, "emergency_csection") and fits(ivf, "nicu") and fits(ivf, "comprehensive_emoc")
    assert not fits(ivf, "trauma_emergency") and not fits(ivf, "cardiac_surgery")
    dx = facility_kinds("Apollo Diagnostics", "clinic")
    assert fits(dx, "mri") and fits(dx, "ct_scan") and not fits(dx, "dialysis") and not fits(dx, "trauma_care")


def test_childrens_hospital_is_never_a_heart_attack_stop() -> None:
    kinds = facility_kinds("Rainbow Children's Hospital", "hospital")
    assert kinds == {"child"} and not specialty_only(kinds)
    assert not fits(kinds, "thrombolysis") and not fits(kinds, "pci_cath_lab")
    assert all(fits(kinds, s) for s in ("nicu", "trauma_emergency", "emergency_csection", "dialysis"))


def test_two_kinds_offer_what_either_may() -> None:
    kinds = facility_kinds("Delhi Child Care and Dental Hospital", "hospital")
    assert kinds == {"child", "dental"} and fits(kinds, "nicu")
    assert facility_kinds("Om Children and Dental Hospital", "hospital") == {"child", "dental"}
    assert facility_kinds("Teddy Teeth. First Exclusive Dental Clinic for Kids and Teens", "clinic") == {"dental"}
    # a child word that qualifies another specialty is not a kind of its own
    assert facility_kinds("Little Wonders Pediatric Dental Clinic", "clinic") == {"dental"}


def test_fit_mask_counts_left_out_pairs_per_service() -> None:
    names = ["Sharma Dental Clinic", "City Hospital and Dental Care", "Apollo Diagnostics"]
    kinds = kinds_by_id(["a", "b", "c"], names, ["clinic", "hospital", "clinic"])
    assert set(kinds) == {"a", "c"}
    keep, counts = fit_mask(["a", "b", "c", "c"], ["mri", "mri", "mri", "dialysis"], kinds)
    assert keep == [False, True, True, False]
    assert counts == {"dialysis": 1, "mri": 1}
