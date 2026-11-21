"""Hand check of 60 random specialty_map rows (seed 20261121) drawn from the automatic pipeline output (before manual
overrides). Verdicts are the author's reading of each value against the label definitions in build_specialty_map.prompt.
Writes out/handcheck_specialty_map.csv and prints precision with a 95% Wilson interval."""
from __future__ import annotations
import math, sys
import pandas as pd

WRONG = {  # specialty -> why the automatic label is wrong
    "neurologyTests": "diagnostic tests (EEG, NCV) outside the taxonomy: out_of_scope, not too_general",
    "emergencyMedicalServices": "LLM said emergency_csection; EMS is ambulance or emergency care, not caesarean",
    "pulmonaryVascularMedicineSpecialist": "narrow pulmonary hypertension specialty: out_of_scope, not too_general",
}

WRONG_SVC = {
    "traumaAndJointReplacement": "orthopaedic, should be orthopaedic_trauma_surgery not trauma_emergency (rule fixed)",
    "Osteoporosis & Osteoporotic Fracture": "osteoporosis clinic, not fracture surgery (rule fixed)",
    "Onco Care": "LLM said surgical_oncology; too_general (manual override)",
}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(c - h, 3), round(c + h, 3)


def main(auto_csv: str) -> None:
    m = pd.read_csv(auto_csv)
    s = m.sample(60, random_state=20261121)[["specialty", "service_id", "method", "confidence", "n_facilities"]].copy()
    s["correct"] = ~s.specialty.isin(WRONG)
    s["note"] = s.specialty.map(WRONG).fillna("")
    s.to_csv("out/handcheck_specialty_map.csv", index=False)
    k, n = int(s.correct.sum()), len(s)
    print(f"overall {k}/{n} = {k/n:.3f}, Wilson95 {wilson(k, n)}")
    for meth, g in s.groupby("method"):
        print(f"  {meth}: {int(g.correct.sum())}/{len(g)}")
    # Supplementary: the random 60 holds few service labels, so 40 rows labelled with a service id (seed 11).
    svc = m[~m.service_id.isin(["too_general", "out_of_scope", "not_a_service"])].sample(40, random_state=11)
    svc = svc[["specialty", "service_id", "method", "confidence", "n_facilities"]].copy()
    svc["correct"] = ~svc.specialty.isin(WRONG_SVC)
    svc["note"] = svc.specialty.map(WRONG_SVC).fillna("")
    svc.to_csv("out/handcheck_specialty_map_service_labels.csv", index=False)
    k, n = int(svc.correct.sum()), len(svc)
    print(f"service-labelled {k}/{n} = {k/n:.3f}, Wilson95 {wilson(k, n)}")


if __name__ == "__main__":
    main(sys.argv[1])
