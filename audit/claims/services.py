"""Service detectors: regex specs per target service plus sentence-level cue detectors.

Every pattern is applied to one sentence (one JSON array item, or one description sentence).
`core` = the sentence states the service itself. `related` = adjacent evidence that does not by
itself mean the service is offered. `prereqs` = clinical prerequisites, each a (text regex,
specialty-enum set) pair, satisfied if ANY sentence in ANY field or the enum matches.
"""
import re

I = re.I


def rx(p):
    return re.compile(p, I)


def norm_spec(s):
    """Specialty enum normaliser: 'Plastic Surgery' / 'plasticSurgery' -> 'plasticsurgery'."""
    return re.sub(r"[^a-z]", "", s.lower())


OBS = {"gynecologyandobstetrics", "obstetricsandgynecology", "obstetricsandgynaecology", "obstetrics",
       "obstetricsandmaternitycare", "maternalfetalmedicineorperinatology", "obstetricsgynaecology",
       "maternalandchildhealth"}
ANES = {"anesthesia", "anesthesiology", "anaesthesiology", "anaesthesia", "obstetricanesthesiology",
        "criticalcaremedicineanesthesiology", "anesthesiologyandcriticalcare"}
PAED = {"pediatrics", "paediatrics", "neonatologyperinatalmedicine", "neonatology", "pediatricsandneonatology",
        "paediatricsandneonatology", "neonatalperinatalmedicine", "neonatalperinatal", "pediatricsneonatology",
        "pediatricneonatology", "pediatriccriticalcaremedicine"}
CTS = {"cardiacsurgery", "cardiothoracicsurgery", "cardiothoracicandvascularsurgery", "cardiovascularsurgery",
       "cardiothoracicsurgery", "pediatriccardiacsurgery", "cardiacsciences"}
PLASTIC = {"plasticsurgery", "reconstructiveplasticsurgery", "burnandtraumaplasticsurgery",
           "plasticandreconstructivesurgery", "cosmeticandplasticsurgery", "burns", "burngeneralsurgery"}
SURG_ORTHO = {"generalsurgery", "orthopedicsurgery", "orthopedictraumaandfracturesurgery", "polytrauma",
              "orthopaedics", "orthopaedicsurgery", "emergencymedicine"}
CRIT = {"criticalcaremedicine", "criticalcare", "intensivecareunit", "icuandcriticalcare",
        "anesthesiologyandcriticalcare", "criticalcaremedicineanesthesiology", "neurocriticalcare"} | ANES

OT = r"operat(ion|ing)[- ]?(theat|room|suite)|\bOTs?\b|modular (OT|theat)|surgical (theat|suite)"

SERVICES = {
    "dialysis": dict(
        core=rx(r"dialy[sz]|haemodialy|hemodialy|\bCAPD\b|\bCRRT\b|\bSLED\b|renal replacement|artificial kidney"
                r"|\bPMNDP\b|national dialysis"),
        exclude=rx(r"dialysis profile|profile test|fistula|dialysis access|access (creation|salvage|surgery)"),
        related=rx(r"nephrolog|nephrologist|kidney (care|centre|center|disease|failure)|renal (care|failure|unit)"),
        spec_core={"dialysis", "nephrologyincludingdialysis", "nephrologyanddialysis", "pediatricdialysis"},
        prereqs={
            "nephrology": (rx(r"nephrolog"), {"nephrology", "pediatricnephrology", "paediatricnephrology",
                                              "nephrologyincludingdialysis", "nephrologyanddialysis",
                                              "nephrologyandurology"}),
            "dialysis_unit_or_machine": (rx(r"dialy\w* (machine|unit|centre|center|ward|bed|station|chair|suite|facility|room)"
                                            r"|(machine|unit|centre|center|ward|bed|station|chair)s? (for|of) (haemo|hemo)?dialy"
                                            r"|\bRO (water|plant|system)|reverse osmosis|fresenius|nipro|b\.? ?braun|\bCRRT\b"
                                            r"|haemodialysis machine|hemodialysis machine"), set()),
        },
        qty=rx(r"\d+\s*(-?bed(ded|s)?|machines?|stations?|chairs?|units?|sessions?|dialys)"
               r"|(machines?|beds?|stations?|sessions?)\s*[:=-]?\s*\d+|over \d[\d,]* |\d[\d,]*\+? (patients|dialysis)"),
    ),
    "csection": dict(
        core=rx(r"caesar|cesar|c-? ?section|\bLSCS\b|lower segment|emergency obstetric|\bB?C?EmON?C\b"
                r"|obstetric emergenc|emergency (delivery|deliveries)|operative (vaginal )?deliver"),
        exclude=rx(r"after (c|caes|ces)\w*[- ]?section|VBAC|scar (endometriosis|ectopic)|cesarean scar|post[- ]?caesarean (wound|scar)"),
        related=rx(r"high[- ]risk (pregnan|obstet|deliver|mother)|labou?r (room|ward|suite)|\bLDRP?\b|delivery|maternity"
                   r"|\bPMSMA\b|\bJSSK\b|\bJSY\b|blood bank|birthing"),
        spec_core=set(),
        prereqs={
            "obstetrics": (rx(r"obstetric|gyn(a)?ecolog|maternity|\bobg|\bOB-?GYN"), OBS),
            "operating_theatre": (rx(OT), set()),
            "anaesthesia": (rx(r"an(a)?esthe(s|t)"), ANES),
        },
        qty=rx(r"\d[\d,]*\+?\s*(deliveries|births|c-?sections|caesarean|cesarean|LSCS)|labou?r (rooms?|beds?)\s*[:=-]?\s*\d+|\d+\s*labou?r"),
    ),
    "nicu": dict(
        core=rx(r"\bNICU|\bNICCU|\bSNCU|neonatal (intensive|icu|critical)|newborn (intensive|icu|care unit)"
                r"|special newborn care|level[- ]?(ii|iii|2|3)\b.{0,20}(nicu|neonat)|neonatal ventilat"),
        exclude=rx(r"ambulance|transport"),
        related=rx(r"neonat|newborn|nursery|incubator|radiant warmer|phototherapy|premature|preterm|kangaroo|\bKMC\b"),
        spec_core=set(),
        prereqs={
            "paeds_or_neonatology": (rx(r"p(a)?ediatric|neonatolog|neonatologist|paediatrician|pediatrician"), PAED),
            "incubator_warmer_ventilator": (rx(r"incubator|radiant warmer|\bwarmers?\b|ventilator|\bCPAP\b|bubble cpap"
                                               r"|phototherapy|ventilation"), set()),
        },
        qty=rx(r"\d+\s*-?\s*(bed(ded|s)?|incubators?|warmers?|ventilators?|cots?)|(beds?|cots?)\s*[:=-]?\s*\d+|level[- ]?(ii|iii|2|3)\b"),
    ),
    "cardiac_surgery": dict(
        core=rx(r"\bCABG|bypass (graft|surg)|open[- ]heart|valve (replace|repair|surg)|\b(AVR|MVR|DVR)\b"
                r"|cardiac surg|heart surg|cardio[- ]?thoracic|cardio[- ]vascular (and|&) thoracic|\bCTVS\b|\bCVTS\b"
                r"|heart transplant|congenital heart (surg|defect surg)|cardiac (OT|operation theat)"),
        exclude=rx(r"cardio[- ]?thoracic radiolog|cardiac an(a)?esthe(s|t)|cardiothoracic imaging|bariatric|gastric bypass"
                   r"|transcatheter|\bTAVR|\bTAVI|\bTMVR|percutaneous|balloon valv|brain bypass|EC-IC|without surgery|non[- ]surgical"),
        related=rx(r"angioplast|cath(eterisation|eterization)? ?lab|\bPTCA\b|stent|interventional cardio|angiograph|pacemaker"),
        spec_core=CTS,
        prereqs={
            "cardiothoracic_surgeon_or_dept": (rx(r"cardio[- ]?thoracic|\bCTVS\b|\bCVTS\b|cardiac surgeon|cardiothoracic surgeon"
                                                 r"|department of cardiac surg"), CTS),
            "cathlab_or_heart_lung": (rx(r"cath(eterisation|eterization)? ?lab|heart[- ]lung machine|perfusion|\bIABP\b|\bECMO\b"
                                         r"|cardiac (OT|operation theat)|bypass machine"), set()),
        },
        qty=rx(r"\d[\d,]*\+?\s*(open[- ]heart|cardiac surg|heart surg|CABG|bypass)|(over|more than) \d[\d,]*"),
    ),
    "mri": dict(
        core=rx(r"\bMRI|magnetic resonance|\bMRA\b|\bMR (scan|imaging|angio)"),
        exclude=rx(r"MRI[- ]compatible|MRI[- ]guided"),
        related=rx(r"\bCT\b|radiolog|imaging"),
        spec_core=set(),
        prereqs={
            "mri_scanner": (rx(r"(MRI|magnetic resonance)\s*(scanner|machine|system|unit|suite|equipment)"
                               r"|\d(\.\d)?\s*-?\s*T(esla)?\b.{0,15}MRI|MRI.{0,15}\d(\.\d)?\s*-?\s*T(esla)?\b|tesla"
                               r"|siemens|philips|\bGE\b|magnetom|signa|ingenia|achieva|open MRI"), set()),
        },
        qty=rx(r"\d(\.\d)?\s*-?\s*T(esla)?\b|tesla"),
    ),
    "burns": dict(
        core=rx(r"\bburns?\b"),
        exclude=rx(r"heart ?burn|sun ?burn|burn ?out|burning|razor burn|calorie|\bfat\b|burn prevention"),
        related=rx(r"\bplastic surg|skin graft|reconstructive surg"),
        spec_core={"burnandtraumaplasticsurgery", "burns", "burngeneralsurgery"},
        prereqs={
            "burn_unit_or_plastic_surgery": (rx(r"burns? (unit|ward|icu|centre|center|care unit)|\bplastic surg|plastic (and|&) reconstruct"),
                                             PLASTIC),
        },
        qty=rx(r"\d+\s*-?\s*bed(ded|s)?|beds?\s*[:=-]?\s*\d+"),
    ),
    "trauma": dict(
        core=rx(r"\btrauma|polytrauma|casualty|accident (and|&) emergenc|\bA ?& ?E\b|emergency (department|room|ward|service|care|unit|medicine|surg)"
                r"|\bER\b|24 ?(x|/|×|\*|hours?|hrs?|-hour) ?7?.{0,25}emergenc|emergenc.{0,25}24 ?(x|/|×|\*|hours?|hrs?)"),
        exclude=rx(r"dental|dentist|tooth|teeth|eye|ocular|ophthalm|psychiatric|emotional|psycholog|veterinar|contracept|"
                   r"maxillofacial trauma|facial trauma|trauma[- ]informed|childhood trauma|ptsd"),
        related=rx(r"ambulance|fracture|orthop(a)?edic"),
        spec_core={"emergencymedicine", "polytrauma", "orthopedictraumaandfracturesurgery", "accidentandemergency"},
        prereqs={
            "emergency_24x7": (rx(r"(24 ?(x|/|×|\*|hours?|hrs?|-hour) ?7?|round[- ]the[- ]clock|24-hour|24 hour).{0,40}(emergenc|casualty|trauma)"
                                  r"|(emergenc|casualty|trauma).{0,40}(24 ?(x|/|×|\*|hours?|hrs?)|round[- ]the[- ]clock)"), set()),
            "surgery_or_ortho": (rx(r"general surg|orthop(a)?edic|trauma surg|laparoscop|operat(ion|ing)[- ]?theat"),
                                 SURG_ORTHO - {"emergencymedicine"}),
            "ct": (rx(r"\bCT\b|computed tomograph|\bCT[- ]?scan|\d+[- ]slice"), set()),
        },
        qty=rx(r"\d+\s*-?\s*bed(ded|s)?|beds?\s*[:=-]?\s*\d+|level[- ]?(i|ii|1|2)\b trauma"),
    ),
    "icu": dict(
        core=rx(r"\bICUs?\b|intensive care|critical care|\bMICU|\bSICU|\bCCU|\bICCU|\bCTICU|\bCVTS ICU|\bHDU|high dependency"),
        exclude=rx(r"ambulance|icu on wheels|transport"),
        related=rx(r"ventilator|monitor|intensivist"),
        spec_core={"criticalcaremedicine", "criticalcare", "intensivecareunit", "icuandcriticalcare"},
        prereqs={
            "ventilator": (rx(r"ventilator|ventilation|\bBiPAP|\bCPAP"), set()),
            "critical_care_or_anaesthesia": (rx(r"intensivist|critical care|an(a)?esthe(s|t)"), CRIT),
        },
        qty=rx(r"\d+\s*-?\s*bed(ded|s)?|beds?\s*[:=-]?\s*\d+|\d+\s*ventilators?"),
    ),
}

# ICU: neonatal/paediatric-only intensive care is NICU/PICU, not adult ICU. Strip before matching.
ICU_STRIP = rx(r"neonatal intensive care|p(a)?ediatric intensive care|neonatal icu|newborn intensive care|\bNICCU\b")

# Sentence cue detectors. Applied only to sentences that already carry a core mention.
# v1 cues (tuned on hand-check sample seed 42, precision 17/58) were too loose: "referral centre",
# "empanelled", "family planning", "closed heart surgery", "No.1", "formerly known as" all fired.
CUES_V1 = {
    "negation": rx(r"\bno\b|\bnot\b|\bnone\b|unavailable|n't\b|\bwithout\b|\black(s|ing)?\b|absence of"),
    "referral": rx(r"\brefer(s|red|ral|rals)?\b|transfer(red)? to|shifted to|send(s)? (patients )?to"),
    "future": rx(r"\bplann(ed|ing)\b|upcoming|coming soon|\bproposed\b|under construction|\bwill (be|soon|start|open|have|launch)"
                 r"|to be (started|set up|established|launched|opened|commissioned)|\bsoon\b|in the pipeline"),
    "partner": rx(r"tie[- ]?up|tied[- ]up|collaborat|in partnership|partner(ed|ship)? with|\bMoU\b|outsourc|empanel"),
    "camp": rx(r"\bcamps?\b"),
    "past": rx(r"\bformerly\b|\bpreviously\b|\bearlier\b|\bused to\b|\bclosed\b|discontinued|\bwas (started|set up|established)"),
}
# v2 cues: phrase-level, each must say the service is NOT delivered here and now.
CUES = {
    "negation": rx(r"\bnot (available|offered|provided|present|performed|listed|done|equipped)|\bdo(es)? not (have|offer|provide|list|perform)"
                   r"|n't (have|offer|provide)|unavailable|\bno [a-z ]{0,25}(facility|facilities|services?|units?|available|on[- ]?site)\b"
                   r"|\bwithout (dialysis|surgery|open|the need|incision|scar|cuts?)|\bno (burns?|scars?|surgery|cuts?)\b|non[- ]surgical"),
    "referral": rx(r"\breferred (out |elsewhere )?to\b|\brefers? (patients |cases )?(out |elsewhere )?to\b|\breferrals? to\b"
                   r"|transfer(red)? to|shifted to|send(s)? (patients )?to"),
    "future": rx(r"\b(is|are|being) planned|plans? to (start|open|set|launch|add|install)|upcoming|coming soon|\bproposed\b|under construction"
                 r"|will be (installed|started|set up|opened|launched|available|commissioned|added)|to be (started|set up|established|launched|opened|commissioned|installed)"
                 r"|in the pipeline"),
    "partner": rx(r"outsourc|(through|via|by) (a |an )?(partner|third[- ]party|external|tie[- ]?up)|tie[- ]?up with (?!.{0,20}(esic|cghs|insur|tpa|scheme))"),
    "parttime": rx(r"\bvisiting\b|\bon[- ]call\b|once a (week|month)|\bweekly\b|(mon|tues|wednes|thurs|fri|satur|sun)days? only"),
    "camp": rx(r"\bcamps?\b"),
    "past": rx(r"\b(shut|closed) down|discontinued|no longer|\bceased\b|\bused to\b|\bdefunct\b"),
    # extractor hedges: the LLM that built the record guessed ("MRI scanner (if applicable)")
    "hedge": rx(r"if applicable|\(if any\)|\bpossibly\b|\blikely\b|\bmay (have|be|offer|provide|include)\b|presumabl|not (specified|confirmed|clear)"
                r"|\bunclear\b|as reported by|reportedly|\bappears to\b|\bimplied\b|\bassumed\b|inferred"),
}
STAFF = rx(r"\bDr\.?\s|\bconsultant\b|surgeon\b|ologist\b|\bMCh\b|\bDNB\b|\bDM\b|\bMD\b|fellowship|\btrained\b|years of experience|\bearned\b|degree|graduat")
DIRECTORY = rx(r"\blisted\b|\branked?\b|\btop\b|\bbest\b|director(y|ies)|justdial|practo|hexahealth|lybrate|\breviews?\b|\brated\b|\bnear (me|you)\b")
QTY_ANY = rx(r"\d")

# A named other facility in the sentence: "... at S L Raheja Fortis Hospital, Mumbai".
FACILITY_NAME = re.compile(r"((?:[A-Z][\w.'&-]*\s+){1,6}(?:Hospitals?|Clinic|Centre|Center|Medical College|Institute|Nursing Home|Medicity))")


# Single-specialty facility names. A tertiary claim on such a record is either scoped to that specialty
# ("24x7 emergency" at a dental clinic) or merged in from another facility (an "Aravind Eye Hospital" record
# whose dialysis sentence describes a Delhi government hospital). Exempt names that also say general/multi.
SCOPE_NAME = rx(r"\beye\b|netra|nethra|nayan|ophthal|lasik|retina|dental|\bdent|teeth|tooth|smile|orthodont|\bivf\b|fertility|test tube"
                r"|\bskin\b|derma|\bhair\b|cosmetic|aesthetic|\bent\b|physio|rehab|homoeo|homeo|ayurved|unani|siddha|naturopath")
SCOPE_EXEMPT = rx(r"general|multi|super|medical college|institute of medical|nursing home|maternity|child|women|mother|medical cent")
SCOPE_OK = {"ivf": {"csection", "nicu"}}  # fertility/IVF centres often run maternity and NICU legitimately


def scope_conflict(name, ftype, service):
    n = name or ""
    if ftype == "dentist":
        return True
    if not SCOPE_NAME.search(n) or SCOPE_EXEMPT.search(n):
        return False
    if re.search(r"\bivf\b|fertility|test tube", n, re.I) and service in SCOPE_OK["ivf"]:
        return False
    return True


def is_list(s):
    """Enumeration sentence: 4+ separators (commas, semicolons, ampersands, ' and ')."""
    return len(re.findall(r",|;|\band\b|&|/", s)) >= 4
