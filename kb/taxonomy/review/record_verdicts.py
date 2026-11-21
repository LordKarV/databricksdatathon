"""Write the reviewer's hand verdicts into the sample CSVs and print the tallies with 95% Wilson intervals.
Run after sample_specialty_map.py and sample_lexicon.py:
/Users/karthikvattem/projects/datathon/.venv/bin/python record_verdicts.py
"""
from __future__ import annotations

import os
from math import sqrt

import pandas as pd

D = os.path.dirname(os.path.abspath(__file__))
WRONG80 = {
    "spine-surgery": "should match spineNeurosurgery (neurosurgery) or both be too_general; builder's neurosurgery names include 'brain and spine surgery'",
    "neurovascularSurgery": "aneurysm/AVM surgery is neurosurgery, not acute stroke care",
    "rhinoplastyAndFacialPlasticSurgery": "cosmetic; out_of_scope, not a burn_care prerequisite",
    "haematologyAutomation": "a lab analyser; out_of_scope, not a chemotherapy or blood_bank prerequisite",
    "swasthavritta": "Ayurveda clinical department; out_of_scope like shalyatantra (harmless for the model)",
    "placentalAbruption": "obstetric emergency condition; too_general with prereq_for emergency_csection;high_risk_pregnancy",
}
DEBATABLE80 = {
    "gynaeoncology": "accepted: MCh gynae-oncology is a surgical specialty",
    "infertilityImaging": "accepted, but it is follicular ultrasound",
    "Periarticular Surgeries": "accepted: periarticular fracture fixation",
    "postSurgical": "accepted, closer to not_a_service",
    "orthopedicsJointReplacement": "accepted; orthopedicSurgery itself is too_general with ortho-trauma prereq",
    "advanceLaparoscopicSurgery": "label accepted; prereq_for trauma_emergency is wrong (elective laparoscopy)",
}
TOP30_NOTES = {
    "neurology": "prereq_for neurosurgery is wrong (neurologists do not operate); keep stroke_care",
    "urology": "label fine; should be prereq_for kidney_transplant (required capability names a urologist)",
    "pathology": "label fine; should be prereq_for surgical_oncology and chemotherapy (histopathology)",
    "criticalCareMedicine": "service label while nephrology/cardiology are too_general; corroboration 0.71 supports it",
    "medicalOncology": "service label but corroboration 0.267, below radiology->ct_scan 0.344 (too_general)",
    "orthopedicSurgery": "too_general by rule; consider a weak prior, nearly every ortho department fixes fractures",
}
LEX_WRONG = {
    "224f04d3:capa:17": ("FP", "staff sentence about a named doctor at a 'clinic'; no cath lab shown"),
    "3e2795de:desc:4": ("FP", "private diagnostic lab listed as an HIV testing centre (directory text); not ICTC or ART"),
    "92dd37f1:capa:15": ("FN", "Regional Cancer Centre designation implies radiotherapy, chemotherapy and surgery"),
    "5ba175d6:proc:23": ("FN", "fetal well-being scan is an obstetric ultrasound"),
}


def wilson(k: int, n: int, z: float = 1.96) -> str:
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return f"{k}/{n} = {p:.3f} (95% Wilson {c - h:.3f} to {c + h:.3f})"


def main() -> None:
    f = os.path.join(D, "specialty_sample_random80.csv")
    s = pd.read_csv(f)
    s["verdict"] = ["wrong" if x in WRONG80 else "correct" for x in s.specialty]
    s["note"] = [WRONG80.get(x, DEBATABLE80.get(x, "")) for x in s.specialty]
    s.to_csv(f, index=False)
    print("random80:", wilson(int((s.verdict == "correct").sum()), len(s)))
    f = os.path.join(D, "specialty_top30.csv")
    t = pd.read_csv(f)
    t["verdict"] = "correct"
    t["note"] = [TOP30_NOTES.get(x, "") for x in t.specialty]
    t.to_csv(f, index=False)
    print("top30 labels:", wilson(len(t), len(t)), "facility mentions", int(t.n_facilities.sum()))
    f = os.path.join(D, "lexicon_sample40.csv")
    x = pd.read_csv(f)
    x["verdict"] = [LEX_WRONG.get(c, ("ok", ""))[0] for c in x.claim_id]
    x["note"] = [LEX_WRONG.get(c, ("", ""))[1] for c in x.claim_id]
    x.to_csv(f, index=False)
    a, b = x[x.part == "A_fp"], x[x.part == "B_fn"]
    print("lexicon A precision:", wilson(int((a.verdict == "ok").sum()), len(a)))
    print("lexicon B missed:", wilson(int((b.verdict == "FN").sum()), len(b)))
    print("lexicon all 40 correct:", wilson(int((x.verdict == "ok").sum()), len(x)))


if __name__ == "__main__":
    main()
