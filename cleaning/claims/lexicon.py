"""Service synonym lists, sentence cues and the quantity extractor used by build_claims.py.

Starts from the audited specs in audit/claims/services.py (imported read-only) and applies the
verifier's fixes as new dicts (the audit module is not modified). Every pattern is a Python `re`
pattern without DuckDB/RE2-only syntax; Java regex (Spark `rlike`, `regexp_extract`) accepts the
same constructs (\\b, lookahead, lookbehind), with case-insensitivity written as a leading (?i).
"""
import os, re, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../audit/claims"))
import services as base  # noqa: E402

I = re.I
rx = base.rx
norm_spec = base.norm_spec

OT = base.OT
S0 = base.SERVICES

# Fixes, each traced to a verifier finding (audit/claims/verify):
#  mri      core '\bMRI' matched Mrityunjay/Mrinal -> trailing boundary; vendor words only count inside MRI sentences
#  csection BEmONC / 'emergency obstetric care' / 'operative vaginal delivery' are not caesarean -> moved to related
#  icu      pediatric ICU / PICU stripped like NICU
#  trauma   ambulance-only lines excluded; CT prerequisite unchanged
#  cardiac  glaucoma valve surgery and neurovascular bypass excluded
#  dialysis 'dialysis facility/centre' no longer satisfies the unit prerequisite (it is the claim itself)
SERVICES = {
    **S0,
    "dialysis": {**S0["dialysis"],
                 "prereqs": {"nephrology": S0["dialysis"]["prereqs"]["nephrology"],
                             "dialysis_unit_or_machine": (rx(r"dialy\w* (machine|station|chair|bed)s?|(machine|station|chair|bed)s? (for|of) (haemo|hemo)?dialy"
                                                             r"|\bRO (water|plant|system)|reverse osmosis|fresenius|nipro|b\.? ?braun|\bCRRT\b"
                                                             r"|ha?emodialysis machine"), set())}},
    "csection": {**S0["csection"],
                 "core": rx(r"caesar|cesar|c-? ?section|\bLSCS\b|lower segment|\bCEmONC\b|comprehensive emergency obstetric"),
                 "related": rx(S0["csection"]["related"].pattern + r"|emergency obstetric|\bB?EmON?C\b|obstetric emergenc|operative (vaginal )?deliver")},
    "mri": {**S0["mri"],
            "core": rx(r"\bMRIs?\b|magnetic resonance|\bMRA\b|\bMR (scan|imaging|angio)"),
            # scanner evidence must sit in an MRI sentence (checked in build_claims.prereq_hits)
            "prereqs": {"mri_scanner": (rx(r"(MRI|magnetic resonance)\s*(scanner|machine|system|unit|suite|equipment)"
                                           r"|\d(\.\d)?\s*-?\s*T(esla)?\b|\btesla\b|\bsiemens\b|\bphilips\b|\bGE\b|magnetom|\bsigna\b|ingenia|achieva|open MRI"),
                                        set())},
            "prereq_scope": {"mri_scanner": "same_service_sentence"}},
    "cardiac_surgery": {**S0["cardiac_surgery"],
                        "exclude": rx(S0["cardiac_surgery"]["exclude"].pattern + r"|glaucoma|trabeculectomy|neurovascular|neuro[- ]?vascular bypass")},
    "trauma": {**S0["trauma"],
               "exclude": rx(S0["trauma"]["exclude"].pattern + r"|^(?!.*(emergency (department|room|ward|unit)|casualty|trauma)).*ambulance")},
    "icu": {**S0["icu"]},
    # hand check E2: post-burn reconstruction and contracture release are plastic surgery, not acute burn care
    "burns": {**S0["burns"], "exclude": rx(S0["burns"]["exclude"].pattern + r"|post[- ]?burns?|burns? (scar|contracture|reconstruct)")},
}
TRAUMA_EXPLICIT = rx(r"\btrauma|polytrauma|casualty|accident")  # audit claims-10: most 'trauma' hits are generic 24x7 emergency
ICU_STRIP = rx(base.ICU_STRIP.pattern + r"|p(a)?ediatric icu|\bPICU\b|paediatric critical care|pediatric critical care")


def scope_conflict(name, ftype, service):
    """audit scope rule with word-boundary fixes (siddha matched Siddharth, nayan matched Kamalnayan)."""
    n = name or ""
    if ftype == "dentist":
        return True
    pat = base.SCOPE_NAME.pattern.replace("siddha", r"\bsiddha\b").replace("nayan", r"\bnayan\b")
    if not re.search(pat, n, I) or base.SCOPE_EXEMPT.search(n):
        return False
    if re.search(r"\bivf\b|fertility|test tube", n, I) and service in base.SCOPE_OK["ivf"]:
        return False
    if service in ("burns", "trauma") and re.search(r"plastic|aesthetic|ortho|rehab", n, I):
        return False
    return True


# Non-offer cues: audit v2 (34/40 right on a fresh sample) plus verifier edits:
# a bare 'planned' cue added, the bare 'may be' hedge removed. 'partner' renamed third_party:
# it means "available through someone else", shown as such, not as "not offered".
CUES = {**{k: v for k, v in base.CUES.items() if k not in ("partner", "hedge")},
        "future": rx(base.CUES["future"].pattern + r"|\bplanned\b"),
        # hand check D7: 'are used to diagnose' fired the audit's bare 'used to'
        "past": rx(r"\b(shut|closed) down|discontinued|no longer|\bceased\b|\bused to (be|have|offer|provide|run|perform)\b|\bdefunct\b"),
        "third_party": base.CUES["partner"],
        "hedge": rx(base.CUES["hedge"].pattern.replace(r"|\bmay (have|be|offer|provide|include)\b", r"|\bmay (have|offer|provide|include)\b"))}
NONOFFER = ["negation", "referral", "future", "past", "camp"]   # remove from positive evidence
WEAKENING = ["hedge", "third_party", "parttime"]                  # keep, but never 'specific'

# Sentence kinds. STAFF no longer fires on a bare 'Dr' (which also starts facility names).
STAFF = rx(r"\b(MBBS|MCh|M\.Ch|DNB|DM|FRCS|MRCP|fellowship|residency|trained (in|at|under)|training (in|at)|years of experience"
           r"|graduated|alumn\w*|formerly|previously|worked (at|as|in)|former\b|ex-)")
DIRECTORY = rx(r"\blisted (among|on|in|as|under)\b|\branked\b|\btop \d+\b|\bdirector(y|ies)\b|justdial|practo|hexahealth|lybrate"
               r"|\breviews?\b|\brated \d|\bnear (me|you)\b|\bcashless\b|\bempanel")
TEMPLATE = rx(r"\b911\b|patient portal|board[- ]certified")
RESEARCH = rx(r"\b(multi-?cent\w*|published|journal|cohort|retrospective|prospective|randomi[sz]ed|et al|consortium|cross-sectional"
              r"|case report|case series|we report|was conducted|were included|patients were|study period"
              r"|(?:study|trial) (?:was|enrolled|recruited|included|documented|population|site))\b")  # provenance RESEARCH_LANG, trimmed
is_list = base.is_list

# Quantities: number + unit noun. Guards: not part of 24x7 / 24/7, not a 4-digit year, not a model number
# ("Fresenius 4008S"). Tesla is checked against 0.2-7 T, counts against 1-5000.
QTY = re.compile(
    r"(?<![\w/×.:-])(\d{1,4}(?:,\d{3})?(?:\.\d)?)\s*\+?\s*-?\s*"
    r"(bed(?:ded|s)?|machines?|stations?|chairs?|slices?|slice|T(?:esla)?\b|tesla|ventilators?|incubators?|warmers?|cots?"
    r"|deliveries|births|surgeries|procedures|operations|sessions|cath ?labs?|operation theat\w*|OTs\b|doctors|specialists|consultants)",
    re.I)
UNIT = {"bed": "beds", "mac": "machines", "sta": "machines", "cha": "machines", "sli": "ct_slices", "t": "tesla", "tes": "tesla",
        "ven": "ventilators", "inc": "incubators", "war": "warmers", "cot": "beds", "del": "deliveries", "bir": "deliveries",
        "sur": "procedures", "pro": "procedures", "ope": "procedures_or_ot", "ses": "sessions", "cat": "cath_labs", "ots": "ots",
        "doc": "doctors", "spe": "doctors", "con": "doctors"}


def quantity(s):
    """First plausible (value, unit) in s, or (None, None)."""
    for m in QTY.finditer(s):
        num, word = m.group(1), m.group(2).lower()
        if s[m.end(1):m.end(1) + 1] in ("x", "×", "/") or re.fullmatch(r"(19|20)\d\d", num.replace(",", "")):
            continue
        v = float(num.replace(",", ""))
        key = "ope" if word.startswith("operation theat") else ("ots" if word == "ots" else ("t" if word == "t" else word[:3]))
        unit = UNIT.get(key)
        if unit is None:
            continue
        if unit == "procedures_or_ot":
            unit = "ots" if "theat" in word else "procedures"
        if unit == "tesla" and not (0.2 <= v <= 7):
            continue
        if unit != "tesla" and not (1 <= v <= 100000):
            continue
        return v, unit
    return None, None


if __name__ == "__main__":
    assert SERVICES["mri"]["core"].search("Mrityunjay Hospital") is None
    assert SERVICES["mri"]["core"].search("3T MRI scanner")
    assert not SERVICES["csection"]["core"].search("Provides emergency obstetric care")
    assert SERVICES["csection"]["core"].search("Performs LSCS")
    assert SERVICES["trauma"]["exclude"].search("24x7 ambulance service")
    assert not SERVICES["trauma"]["exclude"].search("24x7 emergency department with ambulance")
    assert SERVICES["cardiac_surgery"]["exclude"].search("trabeculectomy and valve surgeries for glaucoma")
    assert ICU_STRIP.search("Pediatric ICU with 6 beds")
    assert not CUES["past"].search("MRI is used to diagnose TB") and CUES["past"].search("used to offer dialysis")
    assert SERVICES["burns"]["exclude"].search("Performs post-burn reconstructions")
    assert quantity("10 bedded dialysis unit") == (10, "beds")
    assert quantity("3T MRI") == (3, "tesla")
    assert quantity("128-slice CT scanner") == (128, "ct_slices")
    assert quantity("24x7 emergency") == (None, None)
    assert quantity("Fresenius 4008S machines") == (None, None)
    assert quantity("started in 2010 with machines") == (None, None)
    assert not scope_conflict("Siddharth Hospital", "hospital", "icu")
    assert scope_conflict("Kashmir Eye Hospital", "hospital", "icu")
    assert CUES["future"].search("A cath lab is planned")
    assert not CUES["hedge"].search("This may be the best hospital")
    assert not STAFF.search("Dr. Ram Manohar Lohia Hospital offers dialysis")
    print("lexicon self-check ok")
