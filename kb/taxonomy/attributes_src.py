"""Attribute slots for hours and details (review issue 8): what the KB step must fill per (facility, service) and per
facility. build_lexicon.py copies the schema into services.json ('attributes') and lexicon.json ('attribute_patterns',
'facility_attributes') and counts how often each pattern fires (out/attribute_counts.csv).

Scope rule: a service attribute is read only from a sentence that matched that service (a hospital's 24x7 pharmacy
says nothing about its cath lab). 'from_service' attributes are not text patterns: they are true when the same
facility has positive evidence for the named service (blood_on_site <- blood_bank). Facility attributes are read from
any of the facility's sentences. Patterns are Python re, case-insensitive. A hit is a claim, not a verified fact.
"""
from __future__ import annotations

import re

H24 = r"24 ?(x|/|×|\*) ?7|24 ?(hours?|hrs?)|24-hours?|round[- ]the[- ]clock|day and night|all (days|hours)"
BEDS = r"(\d+)\s*-?\s*bed(ded|s)?"


def a(kind: str, pattern: str = "", note: str = "", from_service: str = "", values: dict[str, str] | None = None) -> dict:
    d = {"type": kind, "note": note}
    if pattern:
        d["pattern"] = pattern
    if from_service:
        d["from_service"] = from_service
    if values:
        d["values"] = values  # enum: value -> pattern, first match wins
    return d


HOURS = a("bool", H24, "24x7 stated in a sentence about this service")

SERVICE_ATTRIBUTES: dict[str, dict[str, dict]] = {
    "emergency_24x7": {"hours_24x7": HOURS, "emergency_beds": a("int", BEDS), "triage": a("bool", r"triage"),
                       "ambulance": a("bool", r"ambulance|\b108\b")},
    "trauma_care": {"hours_24x7": HOURS,
                    "level": a("enum", note="MoHFW trauma care facility level; external/mohfw_trauma_196 is the stronger source",
                               values={"I": r"level[- ]?(i|1)\b(?!i).{0,15}trauma|trauma (centre|center).{0,15}level[- ]?(i|1)\b(?!i)",
                                       "II": r"level[- ]?(ii|2)\b.{0,15}trauma|trauma (centre|center).{0,15}level[- ]?(ii|2)\b",
                                       "III": r"level[- ]?(iii|3)\b.{0,15}trauma|trauma (centre|center).{0,15}level[- ]?(iii|3)\b"}),
                    "surgery_on_site": a("bool", r"general surg|orthop(a)?edic|operat(ion|ing)[- ]?theat"),
                    "ct_on_site": a("bool", from_service="ct_scan"), "blood_on_site": a("bool", from_service="blood_bank")},
    "burn_care": {"beds": a("int", BEDS), "burn_icu": a("bool", r"burns? (icu|intensive)")},
    "orthopaedic_trauma_surgery": {"hours_24x7": HOURS, "c_arm": a("bool", r"\bC-?arm|image intensifier")},
    "icu": {"beds": a("int", BEDS, "can be the whole hospital's beds; check the noun the number attaches to"),
            "ventilators": a("int", r"(\d+)\s*ventilators?"),
            "unit_types": a("enum", values={"MICU": r"\bMICU", "SICU": r"\bSICU", "CCU": r"\bI?CCU\b", "neuro_icu": r"neuro ?(icu|intensive)",
                                            "HDU": r"\bHDU\b|high dependency"})},
    "picu": {"beds": a("int", BEDS), "ventilation": a("bool", r"ventilat")},
    "ventilator_support": {"count": a("int", r"(\d+)\s*ventilators?"),
                           "age_group": a("enum", note="review: an adult snakebite case must not be matched to a NICU ventilator",
                                          values={"neonatal": r"neonat|newborn|\bNICU|\bSNCU", "paediatric": r"p(a)?ediatric|\bPICU|child",
                                                  "adult": r"\bICU|\bMICU|\bSICU|adult|intensive care"})},
    "nicu": {"level": a("enum", note="NBSU = stabilise and refer; SNCU = level II, no ventilation; NICU-III = ventilation",
                        values={"NICU-III": r"level[- ]?(iii|3)\b|neonatal ventilat|ventilat\w*.{0,30}(neonat|newborn|nicu)|(neonat|newborn|nicu).{0,30}ventilat"
                                            r"|\bHFO|surfactant",
                                "SNCU": r"\bSNCU\b|special newborn care|level[- ]?(ii|2)\b",
                                "NBSU": r"\bNBSU\b|newborn stabili[sz]ation"}),
             "ventilation": a("bool", r"ventilat|\bCPAP\b|surfactant|\bHFO"), "beds": a("int", BEDS)},
    "emergency_csection": {"hours_24x7": HOURS, "blood_on_site": a("bool", from_service="blood_bank"),
                           "obstetric_hdu": a("bool", r"obstetric (hdu|icu|high dependency)"),
                           "laqshya": a("bool", r"laqshya", "external/laqshya_master is the stronger source")},
    "institutional_delivery": {"hours_24x7": HOURS, "deliveries": a("int", r"(\d[\d,]*)\+?\s*(deliveries|births)"),
                               "jssk_jsy": a("bool", r"\bJSSK\b|\bJSY\b|janani")},
    "high_risk_pregnancy": {"obstetric_hdu": a("bool", r"obstetric (hdu|icu|high dependency)")},
    "cardiac_surgery": {"paediatric": a("bool", r"p(a)?ediatric cardiac|congenital")},
    "cath_lab_angioplasty": {"primary_pci_24x7": a("bool", r"primary (pci|angioplasty|ptca)|(24 ?(x|/) ?7|round[- ]the[- ]clock).{0,40}(cath|angioplast|pci)"
                                                          r"|(cath|angioplast|pci).{0,40}(24 ?(x|/) ?7|round[- ]the[- ]clock)"),
                             "labs": a("int", r"(\d+)\s*cath[- ]?labs?")},
    "stemi_thrombolysis": {"hours_24x7": HOURS,
                           "agent": a("enum", values={"tenecteplase": r"tenecteplase", "streptokinase": r"streptokinase",
                                                      "reteplase": r"reteplase", "alteplase": r"alteplase"})},
    "stroke_care": {"thrombolysis": a("bool", r"thromboly|\bt-?PA\b|alteplase|tenecteplase"), "thrombectomy": a("bool", r"thrombectomy"),
                    "ct_on_site": a("bool", from_service="ct_scan")},
    "neurosurgery": {"spine_surgery": a("bool", r"spin(e|al) surg|discectomy|laminectomy|spinal fusion|spine (cent|unit)",
                                        "spine is an attribute, not the service (v1.1)"),
                     "emergency_head_injury": a("bool", r"head injur|\bTBI\b|traumatic brain|emergency craniotom|extradural|subdural")},
    "dialysis": {"machines": a("int", r"(\d+)\s*-?\s*((dialysis|ha?emodialysis) )?(machines?|stations?|chairs?|beds?)"),
                 "shifts": a("int", r"(\d|two|three|four)\s*shifts?"),
                 "hbv_machine": a("bool", r"(hbv|hcv|hepatitis|sero-?positive|isolation).{0,30}(machine|dialy)|separate machine",
                                  "desirable, not confirmed as a PMNDP rule"),
                 "free_under_pmndp": a("bool", r"\bPMNDP\b|pradhan mantri (national )?dialysis|free (of cost )?dialysis|dialysis (is )?free"),
                 "emergency_dialysis": a("bool", r"emergency dialysis|acute (kidney|renal) (injury|failure)|\bAKI\b|\bCRRT\b|\bSLED\b|bedside dialysis"
                                                 r"|icu dialysis", "emergency (AKI) dialysis needs an ICU; standalone PPP centres do maintenance only"),
                 "peritoneal": a("bool", r"peritoneal|\bCAPD\b"), "hours_24x7": HOURS},
    "ct_scan": {"hours_24x7": HOURS, "slices": a("int", r"(\d{1,3})\s*-?\s*slices?\b")},
    "mri": {"tesla": a("float", r"(\d(\.\d)?)\s*-?\s*T(esla)?\b"), "hours_24x7": HOURS},
    "ultrasound": {"obstetric": a("bool", r"obstetric|anomaly|f(o)?etal|\bNT\b|antenatal|pregnan"),
                   "pcpndt_registered": a("bool", r"PC-?PNDT|\bPNDT")},
    "blood_bank": {"type": a("enum", values={"storage_unit": r"\bBSU\b|blood storage", "blood_centre": r"blood (bank|cent)"}),
                   "components": a("bool", r"component"), "hours_24x7": HOURS},
    "radiotherapy": {"linacs": a("int", r"(\d+)\s*(LINACs?|linear accelerators?)"), "brachytherapy": a("bool", r"brachy")},
    "chemotherapy": {"day_care": a("bool", r"day ?care")},
    "psychiatric_care": {"inpatient": a("bool", r"ward|in-?patient|admission|beds?")},
    "de_addiction": {"inpatient": a("bool", r"beds?|in-?patient|admission")},
    "tb_care": {"naat": a("bool", r"CBNAAT|gene ?xpert|true ?nat|\bNAAT"), "dr_tb": a("bool", r"\bDR-?TB|\bMDR")},
    "hiv_art": {"level": a("enum", values={"link_art": r"link ART", "art_centre": r"\bART (cent|clinic)|anti-?retroviral",
                                           "ictc_testing": r"\bICTC\b|\bPPTCT\b|testing"})},
    "snakebite_antivenom": {"asv_stock": a("bool", r"\bASV\b|anti-?(snake )?venom"),
                            "ventilator_on_site": a("bool", from_service="ventilator_support")},
    "anti_rabies": {"immunoglobulin": a("bool", r"immunoglobulin|\bE?H?RIG\b")},
    "nutrition_rehabilitation": {"beds": a("int", BEDS)},
    "paediatric_inpatient": {"beds": a("int", BEDS), "hdu": a("bool", r"\bHDU\b|high dependency")},
    "safe_abortion_mtp": {"second_trimester": a("bool", r"second trimester|mid[- ]trimester|(20|24) weeks")},
    "kidney_transplant": {"deceased_donor": a("bool", r"cadaver|deceased donor"),
                          "count": a("int", r"(\d[\d,]*)\+?\s*(kidney|renal) transplants")},
    "cataract_surgery": {"count": a("int", r"(\d[\d,]*)\+?\s*(cataract|eye) (surgeries|operations)")},
    "eye_emergency": {"hours_24x7": HOURS},
}

FACILITY_ATTRIBUTES: dict[str, dict] = {
    "beds_total": a("int", r"(\d{2,4})\s*\+?\s*-?\s*bed(ded|s)?\s*(hospital|facility|multi|super|tertiary|capacity)|bed (strength|capacity)\D{0,10}(\d{2,4})",
                    "hospital size; unit bed counts are service attributes"),
    "accreditation": a("enum", values={"NABH": r"\bNABH\b", "NABL": r"\bNABL\b", "JCI": r"\bJCI\b|joint commission", "NQAS": r"\bNQAS\b|national quality assurance",
                                       "LaQshya": r"laqshya", "Kayakalp": r"kayakalp", "ISO": r"\bISO ?9001"},
                       note="multi-valued; external/nabh_accredited and external/laqshya_master are the stronger sources"),
    "empanelment": a("enum", values={"PMJAY": r"PM-?JAY|ayushman|pradhan mantri jan arogya|\bAB-?ArK\b", "CGHS": r"\bCGHS\b", "ECHS": r"\bECHS\b",
                                     "ESIC": r"\bESIC?\b|employees'? state insurance",
                                     "state_scheme": r"aarogyasri|arogyasri|\bMJPJAY\b|jan arogya|\bCMCHIS\b|chief minister'?s? (comprehensive )?health insurance"
                                                     r"|biju swasthya|\bBSKY\b|swasthya sathi|\bKASP\b|mukhyamantri",
                                     "private_insurance": r"\bTPA\b|cashless|insurance"}, note="multi-valued"),
    "hours_24x7": a("bool", H24, "any 24x7 statement; per-service hours are in the service attributes"),
    "opd_hours": a("text", r"OPD (timings?|hours)|\b\d{1,2}(:\d{2})?\s*(am|a\.m\.)\s*(to|-|–)\s*\d{1,2}(:\d{2})?\s*(pm|p\.m\.)"),
    "ownership": a("enum", values={"government": r"\bgovernment\b|\bgovt\b|district hospital|civil hospital|municipal|\bAIIMS\b|\bESI hospital",
                                   "trust_or_mission": r"charitable|\btrust\b|mission hospital|\bNGO\b|non-profit"},
                   note="text hint only; facility_type and the public lists are the stronger sources"),
    "ambulance": a("bool", r"ambulance|\b108\b|\b102\b"),
}


def compiled(attrs: dict[str, dict]) -> dict[str, list[tuple[str, re.Pattern]]]:
    """attr -> [(value_label, pattern)]: one entry for bool/int/text, one per enum value."""
    out = {}
    for name, d in attrs.items():
        if "values" in d:
            out[name] = [(v, re.compile(p, re.I)) for v, p in d["values"].items()]
        elif "pattern" in d:
            out[name] = [("", re.compile(d["pattern"], re.I))]
    return out


if __name__ == "__main__":
    nic = compiled(SERVICE_ATTRIBUTES["nicu"])
    assert [v for v, r in nic["level"] if r.search("Level III NICU with neonatal ventilators")][0] == "NICU-III"
    assert [v for v, r in nic["level"] if r.search("12-bed SNCU with phototherapy")][0] == "SNCU"
    lev = compiled(SERVICE_ATTRIBUTES["trauma_care"])["level"]
    assert [v for v, r in lev if r.search("Level II trauma centre")][0] == "II"
    assert [v for v, r in lev if r.search("Level I trauma center")][0] == "I"
    emp = compiled(FACILITY_ATTRIBUTES)["empanelment"]
    assert {v for v, r in emp if r.search("Empanelled under Ayushman Bharat PM-JAY and CGHS")} == {"PMJAY", "CGHS"}
    assert compiled(SERVICE_ATTRIBUTES["dialysis"])["shifts"][0][1].search("dialysis in 3 shifts")
    assert not compiled(FACILITY_ATTRIBUTES)["opd_hours"][0][1].search("open 24x7")
    print("attributes_src self-check ok")
