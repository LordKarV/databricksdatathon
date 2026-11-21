"""One-time migration of services.json from v1.0 to v1.1, applying the review (review/REVIEW.md). Every change below is
hand-written content; the script only places it. It refuses to run on a file that is not v1.0, so it cannot apply
twice. The v1.0 file is kept in out/v1_0/services.json. build_lexicon.py afterwards refills 'coverage' and 'attributes'.

Run: /Users/karthikvattem/projects/datathon/.venv/bin/python revise_services.py
"""
from __future__ import annotations

import json
import os

D = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(D, "services.json")
ED = "emergency_24x7"


def sp(phrase: str, route: str, second: str = "", requires: list[str] | None = None, note: str = "") -> dict:
    """A symptom phrase: it selects a route, not a service. route = the service to search first."""
    d = {"phrase": phrase, "route": route}
    if second:
        d["second_card"] = second
    if requires:
        d["requires"] = requires
    if note:
        d["note"] = note
    return d


# service -> (name_phrases, symptom_phrases). Emergency symptoms go to the nearest emergency_24x7 that meets the hard
# prerequisites, with the specialised service as the second card (review issue 1). Obstetric emergencies go to CEmONC
# (emergency_csection) because a general ED cannot do the operation (review issue 14).
PHRASES: dict[str, tuple[list[str], list[dict]]] = {
    ED: (["emergency", "casualty", "24 ghante emergency", "emergency ward", "emergency kahan hai", "108"], [
        sp("behosh hai", ED, "icu"), sp("serious patient", ED, "icu"), sp("critical", ED, "icu"),
        sp("zehar kha liya", ED, "icu", note="poisoning")]),
    "trauma_care": (["trauma centre", "trauma care", "polytrauma"], [
        sp("accident ho gaya", ED, "trauma_care"), sp("accident case kahan le jaayein", ED, "trauma_care"),
        sp("road accident", ED, "trauma_care"), sp("chot lagi hai", ED, "trauma_care"),
        sp("sar pe chot", ED, "neurosurgery", ["ct_scan"])]),
    "burn_care": (["burn ward", "burn unit", "jalne ka ilaaj"], [
        sp(p, ED, "burn_care") for p in ["jal gaya", "aag se jala", "burn case", "garam paani gira", "tezaab (acid) se jala", "current laga"]]),
    "orthopaedic_trauma_surgery": (["fracture", "plaster chahiye", "rod daalna hai", "haddi ka doctor", "ortho"], [
        sp("haddi toot gayi", "orthopaedic_trauma_surgery", note="open wound over the break, cold or pulseless limb: route as emergency_24x7"),
        sp("pair toot gaya", "orthopaedic_trauma_surgery")]),
    "icu": (["ICU", "ICU bed khaali hai", "ICU wala hospital"], [sp("oxygen kam hai", ED, "icu")]),
    "picu": (["bachche ka ICU", "PICU", "bachchon ka ventilator"], [
        sp("bachcha serious hai", "paediatric_inpatient", "picu"),
        sp("bachche ko saans nahi aa rahi", ED, "picu", ["paediatric_inpatient"])]),
    "ventilator_support": (["ventilator", "ventilator wala bed", "saans ki machine", "BiPAP"], []),
    "emergency_csection": (["operation se delivery", "seezer", "sijer", "sizer", "sizerian", "C-section", "emergency delivery", "FRU", "CEmONC"], [
        sp("bachcha ulta hai", "emergency_csection"), sp("delivery mein dikkat", "emergency_csection"),
        sp("khoon jaa raha hai delivery mein", "emergency_csection", requires=["blood_bank"], note="postpartum haemorrhage"),
        sp("jhatke aa rahe hain (eclampsia)", "emergency_csection", requires=["blood_bank"], note="moved from high_risk_pregnancy")]),
    "institutional_delivery": (["delivery kahan karayein", "normal delivery", "labour room", "sarkari delivery (JSY)", "zachgi", "prasav", "dilivery"], [
        sp("dard shuru ho gaya", "institutional_delivery")]),
    "high_risk_pregnancy": (["high risk pregnancy", "HRP", "high risk"], [
        sp("BP badha hua hai pregnancy mein", "high_risk_pregnancy", note="with headache, blurred vision or fits: route as emergency_csection"),
        sp("khoon ki kami (anaemia) pregnancy", "high_risk_pregnancy"), sp("judwa bachche", "high_risk_pregnancy"),
        sp("pehle operation hua tha", "high_risk_pregnancy")]),
    "nicu": (["SNCU", "NICU", "NBSU", "machine mein rakhna hai", "kaanch ki machine (incubator)"], [
        sp("bachcha kamzor paida hua", "nicu"), sp("kam vajan ka bachcha", "nicu"), sp("premature baby", "nicu"),
        sp("samay se pehle janma", "nicu"), sp("peeliya (jaundice) wala bachcha", "nicu"),
        sp("naya bachcha saans nahi le raha", "nicu", requires=["nicu.level=NICU-III or nicu.ventilation"])]),
    "cardiac_surgery": (["dil ka operation", "bypass surgery", "valve badalna hai", "heart surgery", "open heart"], [
        sp("bachche ke dil mein chhed", "cardiac_surgery")]),
    "cath_lab_angioplasty": (["stent dalwana", "angiography", "angioplasty", "cath lab", "nas band hai"], [
        sp(p, ED, "cath_lab_angioplasty", ["stemi_thrombolysis"], "cath lab first only if it is within 120 minutes")
        for p in ["heart attack", "seene mein dard", "dil ka daura"]]),
    "stemi_thrombolysis": (["thrombolysis", "clot ka injection", "STEMI"], []),
    "stroke_care": (["stroke unit", "brain stroke"], [
        sp(p, ED, "stroke_care", ["ct_scan"], "note the time last seen well")
        for p in ["lakwa maar gaya", "laqwa", "lakva", "muh tedha ho gaya", "haath pair nahi chal rahe", "paralysis attack", "zubaan ladkhada rahi hai"]]),
    "neurosurgery": (["dimaag ka operation", "brain tumour", "neuro surgeon"], [
        sp("sar mein khoon jam gaya", ED, "neurosurgery", ["ct_scan"]), sp("head injury", ED, "neurosurgery", ["ct_scan"]),
        sp("reedh ki haddi ka operation", "neurosurgery", "orthopaedic_trauma_surgery", ["neurosurgery.spine_surgery"])]),
    "dialysis": (["dialysis", "dialisis", "dayalisis", "dialysis kahan hota hai", "khoon saaf karna", "hafte mein do baar dialysis", "free dialysis (PMNDP)"], [
        sp("kidney fail", "dialysis"), sp("gurde kharab", "dialysis")]),
    "kidney_transplant": (["kidney transplant", "gurda badalna", "kidney donate", "transplant kahan hota hai"], []),
    "chemotherapy": (["chemo", "cancer ka ilaaj", "kimo lagwana", "cancer ki dawai"], []),
    "radiotherapy": (["sikai", "radiation", "cancer ki sikai", "radiotherapy kahan hoti hai"], []),
    "surgical_oncology": (["cancer ka operation", "breast cancer surgery", "muh ka cancer operation"], [sp("gaanth nikalwani hai", "surgical_oncology")]),
    "mri": (["MRI", "MRI karana hai", "MRI kitne ka", "badi machine wali jaanch", "sar ka MRI"], []),
    "ct_scan": (["CT scan", "city scan", "sar ka scan", "CT karwana hai", "scan machine"], []),
    "ultrasound": (["sonography", "ultrasound", "USG", "4D scan", "pregnancy mein scan"], [
        sp("pet ki jaanch", "ultrasound", note="low weight: also means a stomach check-up or stool test")]),
    "blood_bank": (["blood bank", "khoon chahiye", "khoon chadhana hai", "blood ki zaroorat", "B positive blood"], []),
    "psychiatric_care": (["mental hospital", "psychiatrist", "dimaagi bimari", "depression ka ilaaj",
                          "pagalpan (match only, never display: stigmatising)"], [
        sp("khudkushi ki baat kar raha hai", ED, "psychiatric_care", note="also show Tele-MANAS 14416"),
        sp("nind nahi aati, ajeeb baatein karta hai", "psychiatric_care")]),
    "de_addiction": (["nasha mukti", "sharab chhudwana", "daru ki aadat", "smack / chitta chhudwana", "nashe ka ilaaj"], []),
    "cataract_surgery": (["motiyabind", "motiyabindu", "aankh ka operation", "lens daalna", "safed motia"], [sp("dhundla dikhta hai", "cataract_surgery")]),
    "eye_emergency": ([], [sp("aankh mein chot", "eye_emergency"), sp("aankh mein chuna (lime) gir gaya", "eye_emergency", note="wash with clean water first"),
                           sp("aankh mein kuch chala gaya", "eye_emergency"), sp("aankh laal aur dard", "eye_emergency"),
                           sp("achanak dikhna band", "eye_emergency")]),
    "tb_care": (["TB", "tibi ki jaanch", "tee bee", "DOTS ki dawai", "kshay rog"], [sp("khansi do hafte se", "tb_care"), sp("balgam ki jaanch", "tb_care")]),
    "hiv_art": (["HIV test", "ART centre", "HIV ki dawai", "AIDS ki jaanch"], [sp("PEP", "hiv_art", note="within 72 hours of exposure")]),
    "snakebite_antivenom": (["ASV injection", "zehar ka injection", "snake bite"], [
        sp(p, "snakebite_antivenom", "ventilator_support") for p in ["saanp ne kaata", "saap kaata", "naag ne dasa"]]),
    "anti_rabies": (["rabies ka teeka", "dog bite injection"], [
        sp(p, "anti_rabies") for p in ["kutte ne kaata", "kutta kaat liya", "bandar ne kaata", "chaudah injection (old belief, now 4 to 5 doses)"]]),
    "nutrition_rehabilitation": (["NRC", "poshan punarvas kendra"], [
        sp(p, "nutrition_rehabilitation") for p in ["kuposhit bachcha", "bachcha bahut kamzor hai", "laal band (MUAC red)"]]),
    "paediatric_inpatient": (["bachchon ka ward", "bachche ko bharti karna hai", "paediatric ward"], [
        sp("bachche ko tez bukhar aur jhatke", ED, "paediatric_inpatient"), sp("bachcha doodh nahi pee raha", "paediatric_inpatient")]),
    "safe_abortion_mtp": (["MTP", "safe abortion", "garbhpat"], []),
}

ANSWER_MODE = {  # review issues 7 and 16: services the VF text cannot carry are answered from a public-facility level prior
    "snakebite_antivenom": "prior", "anti_rabies": "prior", "nutrition_rehabilitation": "prior",
    "tb_care": "evidence_plus_prior", "hiv_art": "evidence_plus_prior", "institutional_delivery": "evidence_plus_prior",
    "emergency_csection": "evidence_plus_prior", "paediatric_inpatient": "evidence_plus_prior", "safe_abortion_mtp": "evidence_plus_prior",
    "stemi_thrombolysis": "evidence_plus_prior",
}
PRIOR_NOTE = "Public facility expected to stock or provide this under IPHS 2022; call to confirm."
VF_PUBLIC_NOTE = "VF records rarely describe government facilities (7,902 own websites vs 92 government); estimate from public lists and the IPHS level."

NEW_SERVICES = {
    ED: {
        "id": ED, "aliases": ["trauma"],
        "alias_note": "'trauma' is the cleaning/claims tag; its pattern is ported here because most of its hits are generic 24x7 emergency.",
        "names": {"en": ["24x7 emergency", "emergency department", "casualty", "accident and emergency"],
                  "hi": ["इमरजेंसी", "कैजुअल्टी", "आपातकालीन विभाग"], "mr": ["आपत्कालीन विभाग"]},
        "definition": "A round-the-clock emergency department or casualty that receives, resuscitates and stabilises any acutely ill or injured "
                      "patient and arranges transfer. It is the default first stop for emergency symptom phrases.",
        "urgency": {"profile": "emergency", "window": "as fast as possible; the first hour matters most; call ahead"},
        "required_capabilities": ["emergency department or casualty open 24x7", "doctor on duty round the clock", "oxygen and resuscitation equipment",
                                  "referral transport (108 or own ambulance)"],
        "supporting_evidence": ["'24x7 emergency', 'casualty', 'emergency department'", "emergency beds or triage area with a count"],
        "contradicting_evidence": ["ambulance-only text with no emergency department", "OPD-only timings (for example 9 am to 5 pm)",
                                   "emergency text scoped to one specialty in that clause (eye, dental, obstetric or cardiac emergency)"],
        "iphs": {"expected_from": "24x7 PHC (stabilise and refer); CHC all types (essential, 4 to 11 emergency beds); SDH and every DH (essential)",
                 "citations": ["vol2_chc Annexure 2, S.No. 1 Accident and emergency (triage, resuscitation, stabilisation, referral): E at all CHC types",
                               "vol2_chc Annexure 3: 24*7 Emergency Care 4 beds at 30-bed CHC, 6 at 50-bed, 11 at 100-bed UCHC",
                               "vol1_sdh_dh Annexure 2 'Service Areas': 24x7 Emergency Care at SDH and every DH size (7 to 44 emergency beds)"]},
        "external_confirmation": [{"dataset": "external/hotosm_ind_health_facilities", "what": "emergency=yes tags (sparse)", "strength": "weak"},
                                  {"dataset": "external/nabh_accredited", "what": "NABH specialty code EMD", "strength": "medium"}],
    },
    "stemi_thrombolysis": {
        "id": "stemi_thrombolysis", "aliases": [],
        "names": {"en": ["heart attack clot-dissolving treatment (thrombolysis)", "STEMI thrombolysis"],
                  "hi": ["हार्ट अटैक में थ्रोम्बोलिसिस (खून का थक्का घोलने का इंजेक्शन)"], "mr": ["हृदयविकाराच्या झटक्यात थ्रॉम्बोलिसिस"]},
        "definition": "An emergency department that can record and read an ECG and give a thrombolytic drug (tenecteplase, streptokinase) for a "
                      "STEMI heart attack at any hour, then transfer for angiography.",
        "urgency": {"profile": "emergency",
                    "window": "within 12 hours of symptom onset and as early as possible (drug within 10 minutes of diagnosis); used when primary "
                              "angioplasty cannot be done within 120 minutes of diagnosis (ESC 2023 ACS guideline); transfer for angiography afterwards",
                    "decision_rule": "if cath_lab_angioplasty is reachable within 120 minutes, cath lab first; otherwise stemi_thrombolysis first"},
        "required_capabilities": ["ECG 24x7", "thrombolytic drug in stock", "doctor trained to thrombolyse on duty 24x7", "defibrillator and monitored bed"],
        "supporting_evidence": ["'thrombolysis', 'tenecteplase', 'streptokinase', 'STEMI' in an emergency or cardiology sentence", "CCU or ICCU"],
        "contradicting_evidence": ["stroke, venous or peripheral thrombolysis", "cardiology OPD only"],
        "iphs": {"expected_from": "DH (acute chest pain: investigate and treat including thrombolysis); CHC (myocardial infarction among emergencies "
                                  "to manage, thrombolysis not stated, so stabilise and refer)",
                 "citations": ["vol1_sdh_dh Annexure 3 'Recommended Service Mix', Common Cardiac Problems 3a: acute chest pain, investigate and treat "
                               "(including thrombolysis) and refer", "vol1_sdh_dh Annexure 3 Cardiology Procedures: thrombolytic therapy D at 200 to 500-bed DH",
                               "vol2_chc Annexure 2, S.No. 2.11 Myocardial Infarction: E at all CHC types (capacity to manage)"]},
        "external_confirmation": [],
    },
    "paediatric_inpatient": {
        "id": "paediatric_inpatient", "aliases": [],
        "names": {"en": ["children's ward (paediatric admission)"], "hi": ["बच्चों का वार्ड", "पीडियाट्रिक वार्ड"], "mr": ["बालरुग्ण कक्ष"]},
        "definition": "Admission of sick children (pneumonia, diarrhoea with dehydration, fever with convulsions, dengue) to a paediatric ward "
                      "under a paediatrician. Most sick children need this, not a PICU.",
        "urgency": {"profile": "urgent", "window": "same day for danger signs (cannot drink, convulsions, fast breathing, lethargy); "
                                                   "unconscious or not breathing: route as emergency_24x7"},
        "required_capabilities": ["paediatrician", "paediatric beds", "oxygen", "IV fluids"],
        "supporting_evidence": ["'paediatric ward', 'children's ward', paediatric IPD with a bed count", "paediatric HDU"],
        "contradicting_evidence": ["paediatric OPD only", "paediatric dentistry"],
        "iphs": {"expected_from": "FRU-CHC (paediatrics essential); SDH and every DH (paediatric beds inside the inpatient beds; paediatric HDU)",
                 "citations": ["vol2_chc Annexure 3 Outpatient Services: Paediatrics D at non-FRU CHC, E at FRU-CHC and UCHC",
                               "vol2_chc Annexure 2, S.No. 3 Pediatric emergencies",
                               "vol1_sdh_dh section 24 Inpatient wards: beds including Paediatrics at SDH and every DH size",
                               "vol1_sdh_dh critical care table: Paediatric HDU beds 2 at SDH, 2 to 6 at 100 to 500-bed DH"]},
        "external_confirmation": [{"dataset": "external/hotosm_ind_health_facilities", "what": "healthcare:speciality paediatrics (sparse)", "strength": "weak"}],
    },
    "safe_abortion_mtp": {
        "id": "safe_abortion_mtp", "aliases": [],
        "names": {"en": ["safe abortion (MTP)", "medical termination of pregnancy"], "hi": ["सुरक्षित गर्भपात (एमटीपी)"], "mr": ["सुरक्षित गर्भपात (एमटीपी)"]},
        "definition": "Medical termination of pregnancy under the MTP Act at an approved site: medical method or manual vacuum aspiration in the "
                      "first trimester, second-trimester procedures only at approved facilities.",
        "urgency": {"profile": "urgent", "window": "legal limits depend on weeks of pregnancy (up to 20 weeks on one provider's opinion, 20 to 24 weeks "
                                                   "for specified categories, MTP (Amendment) Act 2021), so delay closes options; heavy bleeding or "
                                                   "fever after an abortion is an emergency (route as emergency_csection)"},
        "required_capabilities": ["MTP-approved site", "trained provider", "MVA kit or medical method drugs", "referral for complications"],
        "supporting_evidence": ["'MTP', 'safe abortion', 'comprehensive abortion care', 'manual vacuum aspiration'"],
        "contradicting_evidence": ["miscarriage management only (spontaneous, missed, recurrent abortion)", "'MTP joint' (foot)",
                                   "any sex-selection wording (illegal under PCPNDT; never route)"],
        "iphs": {"expected_from": "24x7 PHC (safe abortion services E; medical method at every PHC); CHC (MVA E, safe abortion E at FRU types, D at "
                                  "non-FRU); SDH and DH (MTP and mid-trimester abortion)",
                 "citations": ["vol3_phc list of services: Safe abortion services E at 24x7 PHC; Medical Method of Abortion E at PHC",
                               "vol2_chc Annexure 2: Safe Abortion Services as per MTP act D at non-FRU CHC, E at FRU types; MTP using MVA E at all types",
                               "vol1_sdh_dh Annexure 3 Obstetrics and Gynaecology procedures: mid trimester abortion, MTP"]},
        "external_confirmation": [],
    },
}
TRAUMA_CARE_EDIT = {
    "id": "trauma_care", "aliases": ["trauma_emergency"],
    "alias_note": "MODEL_SPEC_v1 gold id. v1.0 trauma_emergency mixed this with generic 24x7 emergency (now emergency_24x7).",
    "names": {"en": ["trauma care", "trauma centre", "polytrauma care"], "hi": ["ट्रॉमा सेंटर", "दुर्घटना का इलाज"], "mr": ["अपघात उपचार केंद्र (ट्रॉमा)"]},
    "definition": "Care of injured patients (road accidents, falls, assault, polytrauma): a 24x7 emergency department with surgery or orthopaedics, CT "
                  "and blood on site or arranged; MoHFW trauma care facilities are graded level I to III.",
    "urgency": {"profile": "emergency", "window": "as fast as possible; the first hour after injury matters most ('golden hour' is a convention, "
                                                  "not a hard threshold); call ahead", "model_spec": "emergency, D_s 30 km"},
}

WINDOWS = {  # review issues 12, 13, plus section 1 notes for stroke, tb and dialysis
    "burn_care": "refer the same day for burns of 10% or more of the body (about 10 palms of the patient's hand), any deep burn, burns of the face, "
                 "hands, feet, genitals or joints, electrical or chemical burns, smoke inhalation, or any burn in a child; start fluids and cool "
                 "the burn first (ABA referral criteria)",
    "orthopaedic_trauma_surgery": "open fracture: antibiotics within 1 hour, immediate surgery for heavy contamination or vascular injury, debridement "
                                  "within 12 hours for high-energy and within 24 hours for other open fractures (BOAST 4); a cold, pale or pulseless "
                                  "limb, or severe pain under a plaster (compartment syndrome), is an emergency; closed fractures are fixed within days",
    "stroke_care": "thrombolysis within about 4.5 hours and thrombectomy in selected patients up to about 24 hours, counted from when the patient was "
                   "last known well, not from when symptoms were found (a wake-up stroke counts from bedtime) (AHA/ASA 2019)",
    "tb_care": "test within days for a cough of 2 weeks or more, or any cough in a person with HIV, diabetes or a TB contact; treatment is daily for "
               "6+ months near home",
}


def all_services(s: dict) -> list[dict]:
    return [x for c in s["categories"] for x in c["services"]]


def main() -> None:
    s = json.load(open(P))
    assert s["version"] == "1.0", "already migrated"
    svc = {x["id"]: x for x in all_services(s)}
    cand = {x["id"]: x for x in s["candidates_not_included"]}

    # trauma_emergency -> trauma_care (keeps the old entry's evidence lists), plus emergency_24x7
    tr = svc["trauma_emergency"]
    tr.update(TRAUMA_CARE_EDIT)
    tr["required_capabilities"] = ["24x7 emergency department or casualty", "general surgery or orthopaedics", "CT scan on site or within reach",
                                   "blood storage or blood bank", "operating theatre 24x7"]
    tr["supporting_evidence"] = ["'trauma centre', 'polytrauma', 'accident and trauma'", "level I/II/III trauma centre wording",
                                 "listed in the MoHFW 196 trauma care facilities"]
    tr["contradicting_evidence"] = [c for c in tr["contradicting_evidence"] if "OPD" not in c] + ["sports-injury or orthopaedic OPD only",
                                                                                                  "trauma X-ray at a home-collection service"]
    tr["iphs"]["expected_from"] = "CHC all types (RTA among emergencies to manage, stabilise and refer); SDH and DH (polytrauma unit integrated with emergency)"
    ed = s["categories"][0]["services"]
    ed.insert(0, NEW_SERVICES[ED])

    # CEmONC (review issue 14)
    cs = svc["emergency_csection"]
    cs["names"]["en"] = ["emergency obstetric surgery (CEmONC)", "emergency caesarean section"] + [n for n in cs["names"]["en"] if "caesarean" not in n.lower()]
    cs["definition"] = ("Comprehensive emergency obstetric and newborn care (CEmONC): caesarean section, blood transfusion and anaesthesia available "
                        "together round the clock, so the facility can manage obstructed labour, haemorrhage (PPH) and eclampsia. The id is kept "
                        "for MODEL_SPEC_v1.")
    cs["hard_prerequisites"] = ["blood_bank", "anaesthesia 24x7", "operating theatre 24x7"]
    hr = svc["high_risk_pregnancy"]
    hr["iphs"]["expected_from"] = "FRU-CHC (high-risk deliveries managed or referred); SDH and DH 100+ beds (obstetric HDU essential; desirable at 50-bed DH)"
    hr["urgency"]["window"] = "scheduled antenatal visits; eclampsia (fits), heavy bleeding or very high BP with headache is an emergency: route as emergency_csection"

    # NICU levels (review issue 10)
    nc = svc["nicu"]
    nc["required_attributes"] = {"level": ["NBSU", "SNCU", "NICU-III"], "ventilation": "bool"}
    nc["level_note"] = ("NBSU stabilises and refers; SNCU (level II) has warmers, phototherapy and oxygen but no ventilation; NICU-III ventilates. "
                        "A baby who needs a ventilator must be routed only to NICU-III or a unit with ventilation evidence.")
    nc["iphs"]["level_prior"] = {"CHC": "NBSU", "SDH": "SNCU", "DH 50": "SNCU", "DH 100+": "SNCU plus NICU-III beds"}

    # neurosurgery scope (review issue 11)
    ns = svc["neurosurgery"]
    ns["names"]["en"] = ["neurosurgery", "brain surgery"]
    ns["definition"] = ("Brain surgery, including emergency surgery for head injury with bleeding (craniotomy, burr holes), brain tumours and VP "
                        "shunts. Spine surgery is recorded as the attribute spine_surgery, because orthopaedic spine surgeons do it too.")
    ns["urgency"]["window"] = "head injury with bleeding: surgery within hours; tumours are scheduled"

    # IPHS priors (review issue 5)
    pc = svc["psychiatric_care"]
    pc["iphs"] = {"expected_from": "DH 100+ beds (psychiatry OPD E; D at SDH and 50-bed DH). CHC: counselling and basic treatment of common mental "
                                   "disorders by medical officers, not psychiatrist care or admission, so the IPHS prior for this service is zero below DH",
                  "citations": ["vol1_sdh_dh 'Table: Specialty wise consultation services in SDH and DH': Psychiatry D at SDH and 50-bed DH, E at 100 to 500-bed DH",
                                "vol2_chc Annexure 2, S.No. 32 INTEGRATED COUNSELLING SERVICES: Mental health E (counselling, not psychiatric care)",
                                "vol2_chc Annexure 2, S.No. 46 NMHP: early identification and treatment of common mental disorders E at all CHC types"],
                  "prior_below_dh": 0}
    pc["legal_context"] = ("Mental Healthcare Act 2017: emergency treatment is allowed at any health establishment for up to 72 hours; admission "
                           "needs a registered mental health establishment. Tele-MANAS (14416) is a non-facility fallback for suicide-risk phrases.")
    da = svc["de_addiction"]
    da["iphs"] = {"expected_from": "no IPHS de-addiction treatment service; CHC lists drug de-addiction under counselling only, so the IPHS prior is none",
                  "citations": ["vol2_chc Annexure 2, S.No. 32 INTEGRATED COUNSELLING SERVICES: Drug de-addiction E (counselling)"], "prior_below_dh": 0}
    hv = svc["hiv_art"]
    hv["iphs"] = {"expected_from": "testing: ICTC at every CHC type. Treatment: NACO ART centres sit mainly at medical colleges and DHs, with link ART "
                                   "centres at smaller facilities, so the IPHS prior for ART treatment is zero below DH (link ART at most)",
                  "citations": ["vol2_chc Annexure 2, S.No. 31 Integrated Counseling and Testing services (HIV): E at all CHC types",
                                "vol2_chc Annexure 3 and vol1_sdh_dh Annexure 2 list 'ART Services' E under Support Services; vol1 abbreviations "
                                "(line 108) expand ART as Anti-Retroviral Therapy, but the row is a support-service entry and is not used as a treatment prior"],
                  "prior_below_dh": 0}

    # dialysis (review issue 29)
    dl = svc["dialysis"]
    dl["required_capabilities"] = [c for c in dl["required_capabilities"] if "HBV" not in c]
    dl["desirable_capabilities"] = ["separate machines for HBV/HCV positive patients (not confirmed as a PMNDP rule)"]
    dl["dialysis_types_note"] = ("emergency dialysis (acute kidney injury, high potassium) needs a hospital with an ICU; standalone PPP centres "
                                 "do maintenance sessions only")
    dl["contradicting_evidence"] = ["'dialysis access' or AV fistula surgery only (no unit, machine, session or shift word)"] + \
        [c for c in dl["contradicting_evidence"] if "fistula" not in c]
    svc["stroke_care"]["hard_prerequisites"] = ["ct_scan 24x7"]
    for k, w in WINDOWS.items():
        svc[k]["urgency"]["window"] = w

    # cath lab: point the other branch at the new service (review issue 6)
    svc["cath_lab_angioplasty"]["urgency"]["window"] = ("heart attack: primary angioplasty if it can be done within 120 minutes of diagnosis; "
                                                        "otherwise stemi_thrombolysis at the nearest capable facility first; elective angioplasty is scheduled")

    # new categories and services
    cats = {c["id"]: c for c in s["categories"]}
    cats["heart_and_brain"]["services"].insert(2, NEW_SERVICES["stemi_thrombolysis"])
    cats["maternal_and_newborn"]["services"].append(NEW_SERVICES["safe_abortion_mtp"])
    sb, ar, nr = cand.pop("snakebite_antivenom"), cand.pop("anti_rabies"), cand.pop("nutrition_rehabilitation")
    for x in (sb, ar, nr):
        x.pop("not_included_because", None)
        x.pop("category", None)
    nr["required_capabilities"] = ["NRC beds", "paediatrician or trained medical officer", "therapeutic feeds (F-75, F-100)", "dietician or nutrition counsellor"]
    nr["iphs"] = {"expected_from": "FRU-CHC and UCHC (10-bed NRC desirable); SDH and 50-bed DH (desirable); DH 100+ beds (essential, 10 to 30 beds)",
                  "citations": ["vol2_chc Annexure 3: NRC (10 Beds) D at FRU-CHC and UCHC", "vol1_sdh_dh section 23 'Table: The number of NRC beds': "
                                "10 (D) at SDH, 6 (D) at 50-bed DH, 10 to 30 (E) at 100 to 500-bed DH"]}
    cats["emergency_and_trauma"]["services"].append(sb)
    cats["infectious_disease"]["services"].append(ar)
    s["categories"].append({"id": "child_health", "name": {"en": "Child health", "hi": "बाल स्वास्थ्य"},
                            "services": [NEW_SERVICES["paediatric_inpatient"], nr]})
    s["candidates_not_included"] = list(cand.values()) + [{
        "id": "palliative_care", "names": {"en": ["palliative care", "hospice"], "hi": ["पैलिएटिव केयर"], "mr": ["उपशामक सेवा"]},
        "definition": "Symptom control and end-of-life care for people with serious illness.",
        "urgency": {"profile": "scheduled", "window": "planned"},
        "not_included_because": "review candidate: few specialties values (7 facilities with palliativeCare); not a time-critical referral. "
                                "Counts are in coverage."}]

    # phrases, answer modes
    for x in all_services(s):
        x.pop("phrases", None)
        names, symptoms = PHRASES[x["id"]]
        x["name_phrases"], x["symptom_phrases"] = names, symptoms
        x["answer_mode"] = ANSWER_MODE.get(x["id"], "evidence")
        if x["answer_mode"] == "prior":
            x["display_note"] = PRIOR_NOTE
        elif x["id"] in ("tb_care", "hiv_art", "institutional_delivery"):
            x["display_note"] = VF_PUBLIC_NOTE
    for x in s["candidates_not_included"]:
        x["answer_mode"] = "not_answered"
    assert {x["id"] for x in all_services(s)} == set(PHRASES), set(PHRASES) ^ {x["id"] for x in all_services(s)}

    s["version"] = "1.1"
    s["revised"] = "2026-11-21: review fixes (TAXONOMY.md CHANGELOG)"
    s["inclusion_rule"] = ("A service is in the taxonomy when it is referral-relevant for intermediaries and either at least 20 usable records "
                           "mention it, or IPHS 2022 expects it at public facility levels so a level prior over public facility lists can answer it "
                           "(answer_mode 'prior'). low_coverage is computed on text evidence only: fewer than 100 facilities with positive text, or "
                           "fewer than 25 with positive text in 2 or more text fields.")
    s["phrase_routing"] = ("name_phrases select the service. symptom_phrases select a route: search 'route' first among facilities that also meet "
                           "'requires', and show 'second_card' (the specialised service) next. Emergency symptoms route to emergency_24x7 so the "
                           "nearest facility that can stabilise comes first; obstetric emergencies route to emergency_csection (CEmONC).")
    s["answer_modes"] = {"evidence": "facility text and specialties evidence", "evidence_plus_prior": "evidence, plus an IPHS level prior for public "
                         "facilities the VF data rarely describes", "prior": "IPHS level prior over public facility lists; display_note shown",
                         "not_answered": "candidate only"}
    s["about"] = s["about"].replace("Ids of the 7 MODEL_SPEC_v1 gold services and icu are kept", "Ids of the MODEL_SPEC_v1 gold services and icu are "
                                    "kept, except trauma_emergency, which is now the alias of trauma_care")
    json.dump(s, open(P, "w"), indent=2, ensure_ascii=False)
    print("services:", len(all_services(s)), "categories:", len(s["categories"]), "candidates:", [x["id"] for x in s["candidates_not_included"]])


if __name__ == "__main__":
    main()
