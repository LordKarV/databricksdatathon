"""Source of lexicon.json: per-service include / exclude / related / negation / quantity patterns.

The 8 services already tagged in cleaning/claims (dialysis, csection, nicu, cardiac_surgery, mri, burns, trauma, icu)
are ported verbatim from cleaning/claims/lexicon.py (imported read-only) so the knowledge base and claims.parquet agree;
their audit-driven exclusions are kept. The other services are new here; their exclusions come from reading matched
sentences in claims.parquet (explore_lexicon.py) and are commented with the false positive they remove.

Regex flavour: Python `re`, applied case-insensitively to one claim sentence. Patterns use \\b and (?!...) lookahead
(Java / Spark rlike accept both; RE2 / DuckDB regexp do not accept lookahead).
"""
from __future__ import annotations

import re
import sys

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/cleaning/claims")
import lexicon as L  # noqa: E402  (read-only import; also pulls audit/claims/services.py)

# cleaning/claims key -> canonical service id (MODEL_SPEC_v1 gold keys win where they differ)
CORE_IDS = {"dialysis": "dialysis", "csection": "emergency_csection", "nicu": "nicu", "cardiac_surgery": "cardiac_surgery",
            "mri": "mri", "burns": "burn_care", "trauma": "emergency_24x7", "icu": "icu"}
# v1.1: the cleaning/claims "trauma" pattern is generic 24x7 emergency (review: only 41% of its sentences name trauma), so it
# now feeds emergency_24x7; trauma_care is new below and carries the MODEL_SPEC id trauma_emergency as an alias.

NEW: dict[str, dict[str, str]] = {
    "ct_scan": dict(
        include=r"\bCT\b|\bCECT\b|\bNCCT\b|\bHRCT\b|\bMDCT\b|computed tomograph|\bCAT scan|\d+[- ]?slices?\b|\bPET[- ]?CT\b|\bCT[- ]?(scan|angio)",
        # 'CT surgeon/surgery' = cardiothoracic; 'CT value' = PCR cycle threshold; CTVS units are cardiac surgery
        exclude=r"\bCT (surg|surgeon|surgery)|\bCT value|\bCTVS|\bCT[- ]?(ratio|count)|cone[- ]beam|\bCBCT\b",
        related=r"radiolog|imaging|diagnostic cent",
        quantity=r"(\d{1,3})\s*-?\s*slices?\b",
    ),
    "blood_bank": dict(
        include=r"blood (bank|centre|center|storage)|\bBSU\b|blood transfusion|transfusion (medicine|service|facilit)|blood component"
                r"|component (separation|therapy)|apheresis|immuno-?ha?ematolog|\bBTS\b",
        # cord/stem-cell banks are not transfusion services; 'blood test/sugar' are labs
        exclude=r"cord blood|stem cell bank|umbilical cord|blood (test|sugar|pressure|glucose)|blood bank (tie|linkage)",
        related=r"\btransfusion|platelet|plasma|\bFFP\b|\bPRBC|packed (red )?cell",
        quantity=r"(\d[\d,]*)\s*(units|bags)\b",
    ),
    "cath_lab_angioplasty": dict(
        include=r"cath(eteri[sz]ation)?[- ]?lab|angioplast|\bPTCA\b|\bPCI\b|coronary (stent|intervention|angiograph)|\bCAG\b"
                r"|interventional cardiolog|primary angioplasty|coronary stent",
        # neuro / peripheral / renal / biliary interventions use a cath lab but are not coronary care
        exclude=r"neuro[- ]?(cath|interven)|peripheral angioplast|renal angioplast|carotid|ureteric stent|\bDJ stent|biliary|ERCP"
                r"|o?esophageal stent|venous angioplast|fistula angioplast|balloon sinuplast",
        related=r"angiograph|stent|pacemaker|\bECG\b|echocardiograph|\bTMT\b|cardiolog",
        quantity=r"(\d+)\s*cath[- ]?labs?|(single|dual|bi)[- ]?plane",
    ),
    "neurosurgery": dict(
        include=r"neuro[- ]?surg|brain surg|craniotom|craniectom|cranial surg|\bVP shunt|ventriculo[- ]?peritoneal|brain tumou?r (surg|remov|resect|excis)"
                r"|neuro[- ]?endoscop|spinal cord (surg|tumou?r)|aneurysm clipp",
        # IPHS lists 'craniotomy - dead foetus' as an obstetric procedure
        exclude=r"craniotomy[- ]+(of )?(dead )?f(o)?etus|dead f(o)?etus",
        related=r"spine surg|spinal surg|neurolog|head injur|\bEEG\b",
        quantity=r"",
    ),
    "stroke_care": dict(
        include=r"stroke (unit|care|centre|center|ready|management|treatment|thrombolysis|team|clinic|program)|acute (isch(a)?emic )?stroke"
                r"|(mechanical|endovascular) thrombectomy|brain attack|thromboly\w*.{0,40}stroke|stroke.{0,40}thromboly",
        exclude=r"heat ?stroke|sun ?stroke|post[- ]?stroke|stroke rehab|stroke (prevention|risk|awareness)|rehabilitation",
        related=r"\bstroke\b|neurolog|thromboly|\bt-?PA\b|alteplase|tenecteplase",
        quantity=r"",
    ),
    "orthopaedic_trauma_surgery": dict(
        include=r"fractures?\b|\bORIF\b|(internal|external) fixat|intramedullary|interlocking nail|orthop(a)?edic trauma|trauma (and|&) orthop"
                r"|fracture surg|limb (salvage|replant)|polytrauma surg",
        # dental / facial / stress-fracture-screening and osteoporosis 'fracture risk' are not fracture surgery
        exclude=r"dental|tooth|teeth|root fracture|crown fracture|mandib|maxill|jaw|facial|zygom|nasal|orbital|fracture risk"
                r"|osteoporo|bone (density|mineral)|DEXA|vertebroplast|kyphoplast",
        related=r"orthop(a)?edic|plaster|\bcast\b|\bC-?arm|traction|bone setting",
        quantity=r"",
    ),
    "chemotherapy": dict(
        include=r"chemo-?therap|\bchemo\b|chemo ?port|medical oncolog|day ?care chemo|immuno-?therapy.{0,30}cancer|cancer.{0,30}immuno-?therapy"
                r"|targeted therapy|hormon(e|al) therapy.{0,30}cancer|hemato-?oncolog|haemato-?oncolog",
        exclude=r"chemoprophyla|chemosis|post[- ]?chemo|chemical",
        related=r"oncolog|cancer|tumou?r board|regional cancer cent",
        quantity=r"(\d+)\s*-?\s*(bed(ded|s)?|chairs?)\b.{0,20}(chemo|day ?care)",
    ),
    "radiotherapy": dict(
        include=r"radio-?therap|radiation (therapy|oncolog|treatment)|\bLINAC\b|linear accelerator|brachy-?therap|\bIMRT\b|\bIGRT\b|\bSBRT\b"
                r"|stereotactic radio|cyber ?knife|tomo-?therapy|gamma ?knife|cobalt[- ]?60|tele-?therapy|\bVMAT\b|true ?beam|halcyon",
        exclude=r"radiation (safety|protection|free|dose|exposure)|without radiation|no radiation|low radiation|radio-?frequency",
        related=r"oncolog|cancer|regional cancer cent",
        quantity=r"(\d+)\s*(LINACs?|linear accelerators?)",
    ),
    "surgical_oncology": dict(
        include=r"surgical oncolog|onco-?surg|cancer surg|surgery for (\w+ )?cancer|oncologic(al)? surg|tumou?r (resection|surgery)"
                r"|mastectomy|whipple|o?esophagectomy|gastrectomy|radical (neck|hysterectomy|prostatectomy|nephrectomy|cystectomy)|commando|\bHIPEC\b",
        exclude=r"brain tumou?r|post[- ]?mastectomy|breast reconstruct|prophylactic|sleeve gastrectomy|bariatric|benign",
        related=r"oncolog|cancer|biopsy|frozen section|regional cancer cent",
        quantity=r"",
    ),
    "picu": dict(
        include=r"\bPICU\b|p(a)?ediatric (intensive|icu|critical care)|children'?s? (icu|intensive care)|\bPICCU\b",
        exclude=r"ambulance|transport",
        related=r"p(a)?ediatric|ventilator",
        quantity=r"(\d+)\s*-?\s*bed(ded|s)?.{0,15}(PICU|p(a)?ediatric)",
    ),
    "ventilator_support": dict(
        include=r"\bventilators?\b|mechanical ventilation|ventilatory support|invasive ventilation|\bBiPAP\b|\bNIV\b|high[- ]flow nasal|\bHFNC\b|life support",
        # building ventilation and ambulance ventilators; neonatal-only ventilators still count (service is ventilation)
        exclude=r"ambulance|natural ventilation|air ventilation|well[- ]ventilated|ventilated (rooms|wards|building)|\bHVAC\b|basic life support|\bBLS\b|advanced (cardiac )?life support (training|course)|\bACLS\b|\bATLS\b",
        related=r"\bICU\b|intensive care|oxygen",
        quantity=r"(\d+)\s*ventilators?",
    ),
    "kidney_transplant": dict(
        include=r"(kidney|renal) transplant|donor nephrectomy|renal allograft|living donor kidney|transplant nephrolog",
        exclude=r"post[- ]?transplant (care|follow)|transplant (counsel|evaluation) only|transplant follow[- ]?up|follow[- ]?up (clinic )?(for|after) (kidney |renal )?transplant",
        related=r"nephrolog|dialysis|transplant",
        quantity=r"(\d[\d,]*)\+?\s*(kidney|renal) transplants",
    ),
    "psychiatric_care": dict(
        include=r"psychiatr\w* (emergenc|ward|in-?patient|admission|unit|icu|crisis|hospital|rehabilitation|beds?|care unit|department|services|treatment|care)"
                r"|mental health (unit|ward|in-?patient|emergenc|crisis|hospital|services|care|treatment)|acute psychiatr|psychiatric care|crisis intervention"
                r"|(department|dept\.?|division|unit|ward|wing|centre|center|clinic) (of|for) psychiatr",  # v1.1: 39 of 40 missed
        exclude=r"psychiatric (assessment|evaluation) only|tele-?psychiatr|online|counsel(l)?ing only",
        related=r"psychiatr|mental health|psycholog|counsel",
        quantity=r"(\d+)\s*-?\s*bed(ded|s)?.{0,20}psychiatr",
    ),
    "de_addiction": dict(
        include=r"de-?addiction|addiction (treatment|medicine|psychiatry|centre|center|services|care|recovery)|alcohol (de-?addiction|detox|withdrawal|use disorder)"
                r"|substance (use|abuse) (disorder|treatment)|opioid substitution|\bOST\b|detoxification|\brehab(ilitation)? cent\w* for (alcohol|drug)",
        # Ayurveda panchakarma 'detoxification' is not addiction treatment
        exclude=r"liver detox|digital detox|detox (diet|juice|tea)|smoking cessation (camp|awareness)|panchakarma|ayurved|rejuvenat|naturopath",
        related=r"psychiatr|alcohol|tobacco cessation|smoking cessation",
        quantity=r"",
    ),
    "eye_emergency": dict(
        include=r"eye (emergenc|trauma|injur|casualty)|ocular (trauma|emergenc|injur)|emergency eye|24 ?(x|/|hours?) ?7?.{0,20}eye|eye.{0,20}24 ?(x|/) ?7"
                r"|open globe|corneal (ulcer|foreign body|tear)|foreign body (removal )?(from|in) (the )?eye|chemical (injur|burn)\w* (of|to) (the )?eye|retinal detachment",
        exclude=r"",
        related=r"ophthalm|\beye\b|retina|cornea",
        quantity=r"",
    ),
    "cataract_surgery": dict(
        include=r"cataract|phaco|\bSICS\b|\bECCE\b|intra-?ocular lens|\bIOLs?\b|small incision",
        exclude=r"cataract (screening|awareness|detection)",
        related=r"ophthalm|\beye\b",
        quantity=r"(\d[\d,]*)\+?\s*(cataract|eye) (surgeries|operations)",
    ),
    "snakebite_antivenom": dict(
        include=r"snake ?bite|snake venom|anti[- ]?snake|\bASV\b|anti-?venom|envenom",
        # template line "Animal bites (Excluding Snake Bite)" appears on many records
        exclude=r"excluding snake",
        related=r"poison|bites?\b",
        quantity=r"(\d+)\s*vials",
    ),
    "anti_rabies": dict(
        include=r"rabies|dog ?bites?|animal ?bites?|\bARV\b.{0,20}(dog|bite|rabies)",
        exclude=r"",
        related=r"vaccinat|immuni[sz]ation|bites?\b",
        quantity=r"",
    ),
    "high_risk_pregnancy": dict(
        include=r"high[- ]risk (pregnan|obstet|deliver|mother|antenatal|preg)|(maternal|feto)[- ]?(fetal|maternal) medicine|f(o)?etal medicine|\bMFM\b"
                r"|perinatolog|obstetric (icu|hdu|high dependency|intensive)|eclampsia|complicated pregnan",
        exclude=r"",
        related=r"antenatal|\bANC\b|obstetric|pregnan|level (ii|2) (scan|ultrasound)",
        quantity=r"",
    ),
    "institutional_delivery": dict(
        include=r"normal (vaginal )?deliver|vaginal (birth|deliver)|labou?r (room|ward|suite|theatre|unit)|\bLDRP?\b|institutional deliver|child ?birth|birthing"
                r"|painless (labou?r|deliver)|labou?r analgesia|maternity (ward|services|care|unit|home|hospital)|\d[\d,]*\+? deliveries|deliveries (per|a|every|conducted|annually)"
                r"|deliver(y|ies) (room|ward|suite)|obstetric (care|services)|\bJSSK\b|\bJSY\b",
        # 'delivery' alone is mostly service/drug delivery language
        exclude=r"drug deliver|home deliver|medicine deliver|service deliver|care deliver|healthcare deliver",
        related=r"antenatal|postnatal|obstetric|maternity|delivery",
        quantity=r"(\d[\d,]*)\+?\s*(deliveries|births)|(\d+)\s*labou?r (beds|tables|rooms)",
    ),
    "tb_care": dict(
        include=r"tuberculosis|\bTB\b|\bDOTS\b|\bRNTCP\b|\bNTEP\b|\bDR-?TB\b|\bMDR[- ]?TB|CBNAAT|gene ?xpert|true ?nat",
        exclude=r"\bTB\b (of|storage)|terabyte",
        related=r"chest|pulmonolog|sputum",
        quantity=r"",
    ),
    "hiv_art": dict(
        include=r"\bART (cent|clinic|services?|plus)|anti-?retroviral|\bICTC\b|\bPPTCT\b|\bHIV\b.{0,30}(care|treatment|clinic|testing|counsel|management)|\bLink ART\b",
        # 'state-of-the-art centre' and assisted-reproduction 'ART clinics / banks' (ICMR registry, PGS/PGD) are not HIV care
        exclude=r"of[- ]the[- ]art|assisted reproduct|\bART\b.{0,20}(IVF|fertility|ICSI|IUI|bank|PGS|PGD)|(IVF|fertility|ICSI|IUI|ICMR|PGS|PGD).{0,60}\bART\b|ART clinics and banks",
        related=r"\bHIV\b|\bAIDS\b|\bSTI\b",
        quantity=r"",
    ),
    "nutrition_rehabilitation": dict(
        include=r"nutrition(al)? rehabilitation|\bNRC\b|severe acute malnutrition|\bSAM\b (child|management|treatment)|malnourished children",
        exclude=r"",
        related=r"malnutrition|nutrition",
        quantity=r"",
    ),
    "ultrasound": dict(
        include=r"ultrasound|ultra-?sonograph|\bUSG\b|sonograph|colou?r doppler|doppler (study|scan|ultra)|anomaly scan|\bNT scan|\b(3|4|5)D (scan|ultrasound)|obstetric scan"
                r"|f(o)?etal well[- ]?being (scan|ultrasound|study)|\bNT[- ]?scan|growth scan|level[- ]?(ii|2) (scan|ultrasound|anomaly)|\bTIFFA\b|nuchal translucency",  # v1.1
        # physiotherapy ultrasound, HIFU and dental ultrasonic scalers are not imaging
        exclude=r"ultrasound therapy|therapeutic ultrasound|\bHIFU\b|ultrasonic|ultrasound[- ]guided (nerve|block|injection)|member of|federation|society of",
        related=r"radiolog|imaging|diagnostic",
        quantity=r"",
    ),
    # ---- v1.1 additions (review issues 2, 6, 15 and missing services) ----
    "trauma_care": dict(
        # explicit trauma words only; generic 24x7 emergency text now goes to emergency_24x7
        include=r"\btrauma|polytrauma|accident(al)? (care|cases?|victims?|ward|surg\w*|injur\w*)|road (traffic )?accidents?|\bRTA\b|head injur\w*"
                r"|golden hour",
        # sentence level: training and affiliation lines (builder hand check v0)
        exclude=r"training program|affiliated (with|to)|mandib|maxill|implant placement",
        # clause level: specialty-scoped or non-physical trauma (department lists keep their other clauses)
        exclude_clause=r"\bdental|dentist|tooth|teeth|\beye|ocular|ophthalm|psychiatric|emotional|psycholog|veterinar|maxillofacial|facial trauma"
                       r"|hand (and|&) face trauma|trauma[- ]informed|childhood trauma|ptsd|post[- ]?traumatic stress|birth trauma|acoustic trauma"
                       r"|trauma x-?ray|sports injur"
                       # orthopaedic 'trauma' (fractures, joints) is orthopaedic_trauma_surgery unless a trauma unit or emergency word is present
                       r"|^(?!.*(trauma (cent|unit|ward|care|team|icu|bay)|polytrauma|emergenc|casualty|accident)).*(orthop|joint|fracture|limb|arthroscop|spine|bone)",
        related=r"fracture|orthop(a)?edic|\bCT\b|blood bank|ambulance",
        quantity=r"(\d+)\s*-?\s*bed(ded|s)?|level[- ]?(i|ii|iii|1|2|3)\b.{0,10}trauma",
    ),
    "stemi_thrombolysis": dict(
        include=r"thromboly\w*|fibrinoly\w*|tenecteplase|streptokinase|reteplase|\bSTEMI\b|chest pain (unit|clinic|cent\w*)"
                r"|heart attack (care|management|treatment)",
        # stroke, venous and peripheral thrombolysis are other pathways
        exclude=r"stroke|brain attack|cerebr|isch(a)?emic brain|pulmonary embol|\bDVT\b|deep vein|catheter[- ]directed|peripheral|limb|venous"
                r"|intra[- ]?arterial",  # v1.1 hand check: IA thrombolysis is interventional radiology
        related=r"myocardial infarction|heart attack|\bECG\b|\bMI\b|cardiac emergenc|\bI?CCU\b",
        quantity=r"",
    ),
    "paediatric_inpatient": dict(
        include=r"p(a)?ediatric(s)? (ward|in-?patient|ipd|admissions?|beds?|hdu|high dependency)|children'?s? (ward|in-?patient)|child(ren)? (admission|ward)"
                r"|\d+\s*-?\s*bed(ded|s)?\s*(p(a)?ediatric|children)(?!\s*(intensive|icu|critical))|in-?patient (p(a)?ediatric|care for children)",
        exclude=r"p(a)?ediatric (dental|dentist)|ambulance|\bI?CCU\b|coronary",  # v1.1 hand check: ICCU paediatric beds
        related=r"p(a)?ediatric|paediatrician|pediatrician|child health",
        quantity=r"(\d+)\s*-?\s*bed(ded|s)?.{0,15}(p(a)?ediatric|children)",
    ),
    "safe_abortion_mtp": dict(
        include=r"\bMTP\b|medical termination of pregnancy|termination of pregnancy|safe abortion|abortion (services?|care|facilit\w*|procedures?)"
                r"|comprehensive abortion|manual vacuum aspiration|medical (method of )?abortion",
        # 'MTP joint' is the metatarsophalangeal joint; miscarriage management is not induced abortion
        exclude=r"MTP joint|metatarsophalang|spontaneous abortion|missed abortion|recurrent (abortion|miscarriage|pregnancy loss)|habitual abortion|threatened abortion",
        related=r"abortion|\bD ?& ?C\b|dilatation and curettage|miscarriage",
        quantity=r"",
    ),
    "palliative_care": dict(  # candidate only
        include=r"palliative|hospice|end[- ]of[- ]life care",
        exclude=r"palliative (surgery|radiotherapy|radiation|chemo\w*|stent\w*|procedure)",
        related=r"pain (management|clinic)|oncolog",
        quantity=r"",
    ),
}

# Service-specific negation cues on top of the shared NONOFFER cues (cleaning/claims/lexicon.py CUES).
NEGATION_EXTRA = {
    "cardiac_surgery": r"without (surgery|open|incision)|non[- ]surgical|minimally invasive alternative",
    "cath_lab_angioplasty": r"referred for angioplast|angioplasty (is )?not",
    "dialysis": r"dialysis (is )?not|no dialysis",
    "burn_care": r"no burns?|without burns?",
    "ventilator_support": r"no ventilators?|ventilators? (are )?not",
    "mri": r"no MRI|MRI (is )?not",
    "ct_scan": r"no CT\b|CT (scan )?(is )?not",
}

# Quantity patterns for the 8 cleaning/claims services (their qty regexes, plus the shared extractor's units).
CORE_QTY = {
    "dialysis": r"(dialysis|haemodialysis|hemodialysis) (machines?|stations?|beds?|chairs?)\s*[:=-]?\s*(\d+)|(\d+)\s*-?\s*(bed(ded|s)?|machines?|stations?|chairs?)",
    "emergency_csection": r"(\d[\d,]*)\+?\s*(deliveries|births|c-?sections|caesareans?|cesareans?|LSCS)",
    "nicu": r"(\d+)\s*-?\s*(bed(ded|s)?|incubators?|warmers?|ventilators?|cots?)|level[- ]?(ii|iii|2|3)\b",
    "cardiac_surgery": r"(\d[\d,]*)\+?\s*(open[- ]heart|cardiac surg|heart surg|CABG|bypass)",
    "mri": r"(\d(\.\d)?)\s*-?\s*T(esla)?\b|(\d+)\s*channel",
    "burn_care": r"(\d+)\s*-?\s*bed(ded|s)?",
    "emergency_24x7": r"(\d+)\s*-?\s*bed(ded|s)?",
    "icu": r"(\d+)\s*-?\s*bed(ded|s)?|(\d+)\s*ventilators?",
}


def core_spec(key: str) -> dict[str, str]:
    d = L.SERVICES[key]
    sid = CORE_IDS[key]
    out = dict(include=d["core"].pattern, exclude=d["exclude"].pattern, related=d["related"].pattern, quantity=CORE_QTY[sid])
    if key == "icu":
        out["strip_before_match"] = L.ICU_STRIP.pattern  # NICU / PICU text is removed before adult-ICU matching
    out["prereqs"] = {k: {"text": p.pattern, "specialty_tags": sorted(t)} for k, (p, t) in d["prereqs"].items()}
    return out


TRAUMA_EXCLUDE_V10 = (r"dental|dentist|tooth|teeth|eye|ocular|ophthalm|psychiatric|emotional|psycholog|veterinar|contracept|"
                      r"maxillofacial trauma|facial trauma|trauma[- ]informed|childhood trauma|ptsd"
                      r"|^(?!.*(emergency (department|room|ward|unit)|casualty|trauma)).*ambulance")


# Fixes found by the kb hand check (handcheck_lexicon.py, v0 sample) on top of the cleaning/claims patterns.
# They live here, not in cleaning/claims, so claims.parquet tags stay as built; build_lexicon reports the difference.
KB_FIXES = {
    "emergency_csection": {"include": ("c-? ?section", r"\bc-? ?section")},   # 'paediatric section' matched
    "cardiac_surgery": {"exclude_add": r"peripheral bypass|fem\w*[- ]?pop\w* bypass|vascular bypass|limb bypass"},
    "burn_care": {"exclude_add": r"minor burns"},
    # v1.1 (review issue 3): the specialty-scope words veto only their own clause, 'dental' is anchored (it matched
    # 'Accidental'), the ambulance-only guard accepts 'emergency care/services', and ER is case-sensitive (Er:YAG, Er.).
    "emergency_24x7": {
        "include": (r"|\bER\b|", r"|(?-i:\bER\b)|"),
        "include_2": (r"\btrauma|polytrauma|", r"\btrauma (centre|center|unit|ward|bay|icu)|polytrauma (unit|centre|center|ward)|"),
        "exclude_replace": (TRAUMA_EXCLUDE_V10,
                            r"trauma[- ]informed|childhood trauma|ptsd|training program|affiliated (with|to)|postgraduate|\bintake\b|degrees? in"
                            r"|^(?!.*(emergency (department|room|ward|unit|care|services?)|casualty|trauma)).*ambulance"),
        "exclude_clause": r"\bdental|dentist|tooth|teeth|\beye|ocular|ophthalm|psychiatric|emotional|psycholog|veterinar|contracept"
                          r"|maxillofacial trauma|facial trauma|hand (and|&) face trauma|emergency obstetric|obstetric emergenc"
                          r"|emergency cardiac|cardiac emergenc",
        "prereqs_keep": ["emergency_24x7"],
    },
    # v1.1 (review issue 18): 'fistula' vetoed 'Piles & Fistula' lists and PD sentences; 'dialysis access' hit 'accessories'
    "dialysis": {"exclude_replace": ("dialysis profile|profile test|fistula|dialysis access|access (creation|salvage|surgery)",
                                     r"dialysis profile|profile test"),
                 # v1.1 hand check: access surgery vetoes only its own clause, and only without a unit word
                 "exclude_clause": r"^(?!.*\b(units?|cent(re|er)s?|machines?|sessions?|shifts?)\b).*(fistula|permacath|dialysis catheter"
                                   r"|line (insertion|management)|dialysis access\b|access (creation|salvage|surgery))"},
}
FUTURE_ADD = r"|plans? to (establish|build|develop|set up)"  # 'Plans to establish ... bypass surgeries' was missed
# v1.1 (review issue 28): 'Blood is arranged from the district blood bank' fired no cue
THIRD_PARTY_ADD = r"|arranged (from|through)|(from|through) (the )?(district|government|nearby|nearest) blood (bank|cent\w*)"


def apply_fixes(specs: dict[str, dict]) -> dict[str, dict]:
    out = {k: dict(v) for k, v in specs.items()}
    for sid, f in KB_FIXES.items():
        if "include" in f:
            old, new = f["include"]
            assert old in out[sid]["include"]
            out[sid]["include"] = out[sid]["include"].replace(old, new)
        if "include_2" in f:
            old, new = f["include_2"]
            assert out[sid]["include"].startswith(old), out[sid]["include"]
            out[sid]["include"] = out[sid]["include"].replace(old, new, 1)
        if "exclude_add" in f:
            out[sid]["exclude"] = out[sid]["exclude"] + "|" + f["exclude_add"]
        if "exclude_replace" in f:
            old, new = f["exclude_replace"]
            assert out[sid]["exclude"] == old, (sid, out[sid]["exclude"])
            out[sid]["exclude"] = new
        if "exclude_clause" in f:
            out[sid]["exclude_clause"] = f["exclude_clause"]
        if "prereqs_keep" in f:
            out[sid]["prereqs"] = {k: v for k, v in out[sid]["prereqs"].items() if k in f["prereqs_keep"]}
    return out


def shared_cues() -> dict[str, str]:
    c = {k: LS_CUES[k].pattern for k in L.NONOFFER + L.WEAKENING}
    c["future"] += FUTURE_ADD
    c["third_party"] += THIRD_PARTY_ADD
    return c


LS_CUES = L.CUES


def all_specs() -> dict[str, dict]:
    specs = {CORE_IDS[k]: core_spec(k) for k in CORE_IDS}
    trauma_prereqs = dict(specs["emergency_24x7"]["prereqs"])  # 24x7, surgery or ortho, CT: these belong to trauma care
    specs = apply_fixes(specs)
    specs.update({k: dict(v) for k, v in NEW.items()})
    specs["trauma_care"]["prereqs"] = trauma_prereqs
    for sid, extra in NEGATION_EXTRA.items():
        specs[sid] = {**specs[sid], "negation_extra": extra}
    return specs


def compile_specs(specs: dict[str, dict]) -> dict[str, dict[str, re.Pattern | None]]:
    """Compile include/exclude/strip patterns once; empty pattern -> None."""
    def c(p: str | None) -> re.Pattern | None:
        return re.compile(p, re.I) if p else None
    return {s: {k: c(d.get(k)) for k in ("include", "exclude", "exclude_clause", "related", "strip_before_match", "negation_extra",
                                         "quantity")}
            for s, d in specs.items()}


CLAUSE_SPLIT = re.compile(r"[;,|\u2022]|\s-\s")


def clause_ok(text: str, include: re.Pattern, exclude_clause: re.Pattern) -> bool:
    """True when some clause that carries the include hit has no clause-level exclusion. A hit that spans clauses
    (no single clause matches) is judged on the whole sentence."""
    clauses = [c for c in CLAUSE_SPLIT.split(text) if include.search(c)] or [text]
    return any(not exclude_clause.search(c) for c in clauses)


def match(text: str, comp: dict[str, dict[str, re.Pattern | None]]) -> list[str]:
    """Services whose include pattern hits the sentence and whose exclude pattern does not (same rule as build_claims.tag)."""
    hits = []
    for sid, c in comp.items():
        t = c["strip_before_match"].sub(" ", text) if c["strip_before_match"] else text
        if c["include"].search(t) and not (c["exclude"] and c["exclude"].search(t)) \
                and (not c["exclude_clause"] or clause_ok(t, c["include"], c["exclude_clause"])):
            hits.append(sid)
    return hits


if __name__ == "__main__":
    comp = compile_specs(all_specs())
    assert match("Performs LSCS", comp) == ["emergency_csection"]
    assert "emergency_csection" not in match("Outpatient department includes paediatric section", comp)
    assert "emergency_24x7" not in match("Provides 24-hour emergency obstetric services", comp)
    # v1.1 review fixes
    assert "emergency_24x7" in match("Departments: Emergency Medicine, Ophthalmology, Dental", comp)
    assert "emergency_24x7" in match("24x7 emergency services and ambulance", comp)
    assert "emergency_24x7" not in match("24x7 ambulance service", comp)
    assert "emergency_24x7" not in match("Er:YAG laser for skin", comp) and "emergency_24x7" in match("ER open 24x7", comp)
    assert "trauma_care" in match("Trauma/Accidental Surgery", comp)  # 'dental' no longer vetoes 'Accidental'
    assert "emergency_24x7" in match("Emergency and casualty, Dental OPD", comp)
    assert "emergency_24x7" not in match("Offers postgraduate degrees in General Medicine, Emergency Medicine", comp)
    assert "trauma_care" in match("Level II trauma centre", comp) and "trauma_care" not in match("24 hour emergency services", comp)
    assert "trauma_care" not in match("Trauma-informed counselling", comp)
    assert "trauma_care" not in match("Performs trauma surgeries for limb fractures", comp)
    assert "trauma_care" in match("Orthopaedic and trauma care hospital", comp)
    assert "emergency_24x7" not in match("Pediatric orthopedics and trauma surgery", comp)
    assert "stemi_thrombolysis" not in match("Intra-arterial thrombolysis", comp)
    assert "paediatric_inpatient" not in match("Has 8-bed pediatric intensive care unit", comp)
    assert "dialysis" in match("Dialysis unit with 10 machines; AV fistula creation also done", comp)
    assert "dialysis" in match("Departments: Piles & Fistula, Dialysis", comp)
    assert "dialysis" not in match("AV fistula surgery for dialysis access", comp)
    assert "dialysis" in match("Peritoneal dialysis accessories provided free", comp)
    assert "dialysis" not in match("Fistula Surgery for Dialysis", comp) and "dialysis" not in match("Fistula creation for dialysis", comp)
    assert "dialysis" in match("PD fluids, catheters and other peritoneal dialysis accessories provided free", comp)
    assert "ultrasound" not in match("Garbh Sanskar supports maternal and fetal wellbeing", comp)
    assert "psychiatric_care" in match("Department of Psychiatry with 20-bed ward", comp)
    assert "ultrasound" in match("Fetal well-being scan", comp)
    assert "kidney_transplant" not in match("Kidney transplant follow-up clinic", comp)
    assert "stemi_thrombolysis" in match("Thrombolysis for STEMI round the clock", comp)
    assert "stemi_thrombolysis" not in match("Stroke thrombolysis with tenecteplase", comp)
    assert "paediatric_inpatient" in match("Paediatric ward with 30 beds", comp)
    assert "safe_abortion_mtp" in match("MTP services up to 20 weeks", comp) and "safe_abortion_mtp" not in match("MTP joint pain", comp)
    assert re.search(shared_cues()["third_party"], "Blood is arranged from the district blood bank", re.I)
    assert "cardiac_surgery" not in match("Peripheral bypass surgery", comp)
    assert "ct_scan" in match("128-slice CT scanner", comp) and "ct_scan" not in match("CT surgeon on call", comp)
    assert "icu" not in match("Level III NICU with 10 beds", comp) and "nicu" in match("Level III NICU with 10 beds", comp)
    assert "neurosurgery" not in match("Craniotomy-dead foetus", comp)
    assert "hiv_art" not in match("ART and IVF treatments", comp) and "hiv_art" in match("ART centre for HIV patients", comp)
    assert "stroke_care" not in match("Post-stroke rehabilitation", comp) and "stroke_care" in match("Acute stroke thrombolysis 24x7", comp)
    assert "orthopaedic_trauma_surgery" not in match("Treats dental root fracture", comp)
    assert "ventilator_support" not in match("ICU ambulance with ventilator", comp)
    assert "hiv_art" not in match("State-of-the-art centre for eye care", comp)
    assert "snakebite_antivenom" not in match("Animal bites (Excluding Snake Bite)", comp)
    assert "de_addiction" not in match("Panchakarma detoxification therapies", comp)
    assert "anti_rabies" in match("Anti-rabies vaccination for dog bites", comp)
    assert "institutional_delivery" not in match("Home delivery of medicines", comp)
    print("lexicon_src self-check ok")
