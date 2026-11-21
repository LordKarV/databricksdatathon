"""Adversarial probes for lexicon_src.match: hand-written sentences with the services a reader would expect.
Prints every probe whose matched set differs from the expectation (missing = false negative, extra = false positive).
'nonoffer' probes check that the shared non-offer cues fire. Run from kb/taxonomy:
/Users/karthikvattem/projects/datathon/.venv/bin/python review/probe_lexicon.py
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lexicon_src as LS  # noqa: E402

PROBES: list[tuple[str, set[str]]] = [
    ("Dialysis unit with 10 machines; AV fistula creation also done", {"dialysis"}),
    ("Haemodialysis in 3 shifts, 6 am to 10 pm", {"dialysis"}),
    ("Fetal well-being scan", {"ultrasound"}),
    ("Anomaly scan and NT scan for pregnant women", {"ultrasound"}),
    ("SNCU with 12 beds and phototherapy", {"nicu"}),
    ("Newborn care corner in the labour room", {"institutional_delivery"}),
    ("Normal delivery and LSCS available 24x7", {"institutional_delivery", "emergency_csection"}),
    ("Caesarean section", {"emergency_csection"}),
    ("Primary PCI for STEMI 24x7", {"cath_lab_angioplasty"}),
    ("PTCA and stenting", {"cath_lab_angioplasty"}),
    ("Thrombolysis for acute myocardial infarction", set()),
    ("Linear accelerator (LINAC) for radiation", {"radiotherapy"}),
    ("Tomotherapy and IMRT", {"radiotherapy"}),
    ("Cobalt-60 teletherapy unit", {"radiotherapy"}),
    ("Gamma knife radiosurgery", {"radiotherapy"}),
    ("Casualty services available round the clock", {"trauma_emergency"}),
    ("24 hour emergency services", {"trauma_emergency"}),
    ("ICU on wheels", set()),
    ("Oxygen concentrator available", set()),
    ("Heat stroke management", set()),
    ("Heartburn and acidity treatment", set()),
    ("Burn ward with 6 beds", {"burn_care"}),
    ("Blood storage unit", {"blood_bank"}),
    ("MRI 1.5 Tesla", {"mri"}),
    ("Mrityunjay Hospital, Sagar", set()),
    ("Department of Psychiatry with 20-bed ward", {"psychiatric_care"}),
    ("Counselling services by a clinical psychologist", set()),
    ("Phacoemulsification with foldable IOL", {"cataract_surgery"}),
    ("SICS with IOL implantation", {"cataract_surgery"}),
    ("Retinal detachment surgery", {"eye_emergency"}),
    ("Chemoport insertion", {"chemotherapy"}),
    ("Day care chemotherapy", {"chemotherapy"}),
    ("Link ART centre", {"hiv_art"}),
    ("ICTC for HIV testing", {"hiv_art"}),
    ("CBNAAT machine for TB testing", {"tb_care"}),
    ("DOTS centre", {"tb_care"}),
    ("Paediatric ward with 30 beds", set()),
    ("PICU and NICU", {"picu", "nicu"}),
    ("Level III NICU with neonatal ventilators", {"nicu"}),
    ("HDU with 6 beds", {"icu"}),
    ("Level II trauma centre", {"trauma_emergency"}),
    ("Fracture clinic and plaster room", {"orthopaedic_trauma_surgery"}),
    ("Eye bank", set()),
    ("Snake bite management with ASV", {"snakebite_antivenom"}),
    ("Anti rabies vaccine available", {"anti_rabies"}),
    ("Organophosphate poisoning management", set()),
    ("Regional Cancer Centre", set()),
    ("Cath lab", {"cath_lab_angioplasty"}),
    ("Brachytherapy", {"radiotherapy"}),
    ("Emergency obstetric care", set()),
    ("Thalassaemia day care transfusion", {"blood_bank"}),
    ("Spine surgery", {"neurosurgery"}),
    ("Kidney transplant follow-up clinic", set()),
    ("Stroke rehabilitation", set()),
    ("Mechanical thrombectomy for stroke", {"stroke_care"}),
]
NONOFFER: list[str] = [
    "No ICU facility", "Dialysis is not available", "Patients are referred to AIIMS for cardiac surgery",
    "CT scan through tie-up with a diagnostic centre", "MRI on outsourced basis", "Blood is arranged from the district blood bank",
]


def main() -> None:
    comp = LS.compile_specs(LS.all_specs())
    bad = 0
    for text, exp in PROBES:
        got = set(LS.match(text, comp))
        if got != exp:
            bad += 1
            print(f"MISMATCH  {text!r}: missing={sorted(exp - got)} extra={sorted(got - exp)}")
    cues = {k: re.compile(p, re.I) for k, p in LS.shared_cues().items()}
    for text in NONOFFER:
        fired = [k for k, r in cues.items() if r.search(text)]
        print(f"CUE {text!r}: services={LS.match(text, comp)} cues={fired}")
    print(f"{bad}/{len(PROBES)} probes differ from expectation")


if __name__ == "__main__":
    main()
