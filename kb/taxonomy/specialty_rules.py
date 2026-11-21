"""Deterministic normalisation and ordered keyword rules for the specialties enum (step 1 of specialty_map.csv).

Labels: a service id from services.json; too_general (a broad specialty that contains taxonomy services but does not by
itself show any, e.g. internalMedicine, nephrology); out_of_scope (a real clinical specialty or procedure that no taxonomy
service covers, e.g. dentistry, IVF); not_a_service (academic subject, admin or non-clinical text).
A value maps to a service only when its words name that service, its unit, or its core procedure. First rule wins, so
specific rules sit above the broad ones (eyeTrauma... before trauma, dentalAnesthesia before anesthesia).
"""
from __future__ import annotations

import re

SPELL = [  # British/variant spellings -> one form, applied to the space-separated lowercase text
    (r"paediatr", "pediatr"), (r"anaesth", "anesth"), (r"gynaecolog", "gynecolog"), (r"orthopaed", "orthoped"),
    (r"haemat", "hemat"), (r"haemo", "hemo"), (r"oesophag", "esophag"), (r"tumour", "tumor"), (r"centre", "center"),
    (r"foetal|foeto", "fetal"), (r"caesar", "cesar"), (r"\bopthal|\bophtal", "ophthal"), (r"gynec", "gynec"),
    (r"\bperiondont", "periodont"), (r"\booculo", "oculo"), (r"\bobstretic", "obstetric"), (r"\bdieases?\b", "disease"),
]


def normalize(raw: str) -> str:
    """'gynecologyAndObstetrics' -> 'gynecology and obstetrics'; '  Nephrology & Dialysis' -> 'nephrology and dialysis'."""
    s = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", raw.strip())
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    for a, b in SPELL:
        s = re.sub(a, b, s)
    return re.sub(r"\s+", " ", s)


# (pattern, label, confidence, prereq_for). prereq_for: services whose clinical prerequisites this value can satisfy.
RULES: list[tuple[str, str, float, str]] = [
    # explicit exclusions that would otherwise hit a service rule below
    (r"pain (medicine|management)|^pain|chronic pain|osteoporo|vertebroplast", "out_of_scope", 0.9, ""),
    (r"automation|analy[sz]er|stroke rehab|rhinoplast|facial plastic|aesthetic plastic|cosmetic", "out_of_scope", 0.9, ""),  # v1.1 review
    (r"non ?interventional cardiolog", "too_general", 0.85, "cath_lab_angioplasty;cardiac_surgery;stemi_thrombolysis"),  # v1.1 review: hit rule 'interventional cardiolog'
    (r"placenta|abruption|\bpph\b|postpartum hemorrhage|eclampsia|obstetric emergenc", "too_general", 0.8, "emergency_csection"),  # v1.1 review
    (r"\bdent|odont|\boral\b|maxillo|\bomfs\b|tooth|teeth|denture|implantolog|\bsmile\b|\btmj\b|orthognath|craniofacial|cleft", "out_of_scope", 0.95, ""),
    (r"cardiothoracic radiolog|cardiothoracic imaging|breast imaging|neuroradiolog|pediatric radiolog", "too_general", 0.85, "ct_scan;mri;ultrasound"),
    (r"cardiac anesth|cardiovascular anesth", "too_general", 0.85, "cardiac_surgery"),
    (r"obstetric anesth", "too_general", 0.85, "emergency_csection"),
    (r"ocular oncolog|oculoplast|retinoblast", "out_of_scope", 0.9, ""),
    # services
    (r"dialy", "dialysis", 0.95, ""),
    (r"(kidney|renal) transplant", "kidney_transplant", 0.95, ""),
    (r"cardiac surg|heart surg|cardiothoracic|cardio thoracic|cardiovascular (and thoracic )?surg|\bctvs\b|\bcvts\b|heart transplant|cardiac surgeon|congenital heart surg", "cardiac_surgery", 0.95, ""),
    (r"interventional cardiolog|cath lab|catheteri[sz]ation|angioplast|transradial|coronary interven|structural heart", "cath_lab_angioplasty", 0.9, ""),
    (r"eye (trauma|emergenc|injur)|ocular trauma|emergency eye|retinal detachment", "eye_emergency", 0.9, ""),
    (r"cataract|phaco|anterior segment", "cataract_surgery", 0.9, ""),
    (r"\bburns?\b", "burn_care", 0.9, ""),
    (r"fracture|orthopedic trauma|trauma and (orthoped|joint)|orthoped\w* and trauma|limb replant", "orthopaedic_trauma_surgery", 0.9, ""),
    (r"maxillofacial trauma|facial trauma", "out_of_scope", 0.9, ""),
    (r"pediatric (critical|intensive)|\bpicu\b", "picu", 0.9, ""),
    (r"\bnicu\b|\bsncu\b|neonatal (intensive|critical)|newborn intensive", "nicu", 0.9, ""),
    (r"critical care|intensive care|\bicu\b|intensivist", "icu", 0.85, ""),
    (r"ventilat|respiratory failure|\bards\b", "ventilator_support", 0.85, ""),
    (r"neuro ?vascular surg|cerebrovascular surg", "neurosurgery", 0.9, ""),  # v1.1 review: was stroke_care
    (r"stroke|vascular neurolog|neuro ?intervention|neurovascular|endovascular neuro", "stroke_care", 0.85, ""),
    (r"neuro ?surg|brain surg|skull base|craniotom", "neurosurgery", 0.95, ""),
    # v1.1: spine is an attribute of neurosurgery and orthopaedics, not a service (review issue 11)
    (r"^(?!.*(rehab|injury|anesth|pain|physio|tubercul|stimulat)).*\bspin(e|al)\b", "too_general", 0.8, "neurosurgery;orthopaedic_trauma_surgery"),
    # v1.1: trauma_emergency split into trauma_care and emergency_24x7 (review issue 2)
    (r"polytrauma|\btrauma\b|traumatolog|accident (and )?trauma|accident trauma", "trauma_care", 0.85, ""),
    (r"emergency medicine|accident (and )?emergency|accident emergency|casualty|emergency (care|services?|department|room)|^emergency$|pediatric emergency", "emergency_24x7", 0.85, ""),
    (r"radiation oncolog|radiotherap|radiation therap|radiosurg|brachytherap|cyber ?knife|gamma knife", "radiotherapy", 0.95, ""),
    (r"medical oncolog|chemotherap|hemato ?oncolog|pediatric (hematology )?oncolog|\bcar t\b|bone marrow transplant|\bbmt\b", "chemotherapy", 0.85, ""),
    (r"surgical oncolog|onco ?surg|mastectomy|cancer surg|oncologic(al)? surg|tumor surg|(gynecolog\w*|\buro\w*|orthoped\w*|breast|head and neck|\bgi\b|thoracic|musculoskeletal) oncolog", "surgical_oncology", 0.85, ""),
    (r"^(\w+ ){0,3}cancers?( clinic| care| treatment)?$", "too_general", 0.8, "chemotherapy;radiotherapy;surgical_oncology"),  # v1.1: '<site> cancer'
    (r"transfusion|blood bank|blood cent|immunohematolog|apheresis", "blood_bank", 0.9, ""),
    (r"\bct\b|computed tomograph", "ct_scan", 0.9, ""),
    (r"\bmri\b|magnetic resonance", "mri", 0.9, ""),
    (r"ultraso|sonograph|\busg\b|doppler", "ultrasound", 0.9, ""),
    (r"cesarean|c section|\blscs\b|emergency obstetric|\bcemonc\b", "emergency_csection", 0.9, ""),
    (r"addiction|substance (use|abuse)|alcohol|detox", "de_addiction", 0.85, ""),
    (r"psychiatr", "psychiatric_care", 0.85, ""),
    (r"neonat|newborn", "too_general", 0.85, "nicu"),
    (r"maternal fetal|fetal (and )?maternal|feto ?maternal|fetal medicine|perinatolog|perinatal medicine|high risk (pregnan|obstet)", "high_risk_pregnancy", 0.85, ""),
    (r"obstetrics and maternity|maternity|labor and delivery|labour and delivery|childbirth|midwi|birthing|normal delivery|pregnancy care|antenatal|prenatal care", "institutional_delivery", 0.75, ""),
    (r"obstetric|\bobg|\bob gyn|gynecologist and obstetrician", "too_general", 0.9, "emergency_csection;institutional_delivery;high_risk_pregnancy"),
    (r"tubercul|\btb\b|\bdots\b", "tb_care", 0.85, ""),
    (r"\bhiv\b|\baids\b|antiretroviral", "hiv_art", 0.85, ""),
    (r"snake|venom", "snakebite_antivenom", 0.85, ""),
    (r"rabies|animal bite|dog bite", "anti_rabies", 0.85, ""),
    # broad specialties that contain taxonomy services
    (r"^(internal|general|family|sports internal|geriatrics internal) medicine$|^medicine$|^general (practice|physician)|physician$|^internal medicine", "too_general", 0.9, ""),
    (r"^general surg", "too_general", 0.85, "trauma_care"),
    (r"laparoscop|minimal(ly)? (access|invasive) surg", "too_general", 0.85, ""),  # v1.1: laparoscopy is elective, not a trauma prerequisite
    (r"^pediatric(s| care| medicine)?$|^child (care|health)$|^pediatrics and neonatology$|pediatrician", "too_general", 0.85, "nicu;picu;paediatric_inpatient"),
    (r"anesth", "too_general", 0.85, "emergency_csection;icu;cardiac_surgery;neurosurgery"),
    (r"^(diagnostic )?radiolog|^imaging|radiology and imaging|interventional radiolog|^radiodiagnos", "too_general", 0.85, "ct_scan;mri;ultrasound"),
    (r"cardiolog|cardiac sciences|^cardiac|heart care", "too_general", 0.85, "cath_lab_angioplasty;cardiac_surgery;stemi_thrombolysis"),
    (r"nephrolog|renal (science|medicine)|kidney care", "too_general", 0.85, "dialysis;kidney_transplant"),
    (r"^neurolog|pediatric neurolog|child neurolog", "too_general", 0.8, "stroke_care"),  # v1.1: neurologists do not operate
    (r"neurosciences?$|^neuro$|brain injury", "too_general", 0.8, "stroke_care;neurosurgery"),
    (r"^oncolog|^cancer( care| treatment)?$|^oncology$", "too_general", 0.8, "chemotherapy;radiotherapy;surgical_oncology"),
    (r"^orthoped(ic|ics)( surgery| surgeon)?$|^orthopedist|^bone and joint$|^orthopedics and", "too_general", 0.8, "orthopaedic_trauma_surgery"),
    (r"pulmonolog|pulmonary|respiratory medicine|chest", "too_general", 0.8, "ventilator_support;tb_care"),
    (r"transplant", "too_general", 0.8, "kidney_transplant"),
    (r"plastic|^reconstructive surg", "too_general", 0.8, "burn_care"),
    (r"^ophthalmolog(y|ist)$|^eye( care| hospital| surgery)?$", "too_general", 0.85, "cataract_surgery;eye_emergency"),
    (r"infectious disease|^infectious|infection", "too_general", 0.8, "tb_care;hiv_art"),
    (r"hematolog", "too_general", 0.8, "blood_bank;chemotherapy"),
    (r"toxicolog|poison", "too_general", 0.8, "snakebite_antivenom;emergency_24x7"),
    (r"^gynecolog|gynecology$", "out_of_scope", 0.85, ""),
    # clinical specialties outside the taxonomy
    (r"derma|\bskin\b|\bhair\b|cosmet|aesthetic|trichol|venereol|leprosy|\bnail\b", "out_of_scope", 0.9, ""),
    (r"ophthal|retina|vitreo|cornea|glaucoma|uvea|uveitis|strabism|refractive|lasik|kerato|squint|low vision|optometr|\beye\b|ocular|orbit", "out_of_scope", 0.9, ""),
    (r"otolaryng|\bent\b|rhinolog|laryngolog|otolog|audiolog|cochlear|head and neck|\bear\b|\bnose\b|throat|sinus", "out_of_scope", 0.9, ""),
    (r"gastro|hepat|liver|\bgi\b|colorectal|procto|bariatric|pancrea|endoscop|digestive|foregut|\banal\b|rectal|piles|hernia", "out_of_scope", 0.9, ""),
    (r"endocrin|diabet|thyroid|metabolic", "out_of_scope", 0.9, ""),
    (r"rheumat|arthritis|lupus", "out_of_scope", 0.9, ""),
    (r"\burolog", "out_of_scope", 0.9, "kidney_transplant"),  # v1.1: urologist is a transplant prerequisite
    (r"androlog|\burogyn|genitourinary|endourolog|prostate|kidney stone|neuro urolog", "out_of_scope", 0.9, ""),
    (r"fertil|\bivf\b|reproductive|embryolog|\biui\b|test tube", "out_of_scope", 0.9, ""),
    (r"physio|rehab|physical medicine|\bpmr\b|occupational therapy|speech|prosthetic|orthotic|amputee|spinal cord injury", "out_of_scope", 0.9, ""),
    (r"pain|sleep|geriatric|elder|palliative|hospice|supportive care", "out_of_scope", 0.9, ""),
    (r"vascular surg|varicose|vein|pediatric surg|breast|thoracic surg|hand (and|or|surg)|upper extremit|peripheral nerve|microsurg|foot and ankle|podiatr|spine|joint|arthroscop|knee|hip|shoulder|sports", "out_of_scope", 0.85, ""),
    (r"allerg|immunolog|genetic|genomic|nutrition|dietet|diet\b|obesity|wellness|lifestyle|preventive|vaccin|immuni[sz]ation|travel medicine", "out_of_scope", 0.85, ""),
    (r"ayurved|homeo|homoeo|unani|siddha|naturopath|yoga|panchakarma|acupunct|swasthavritta|alternative medicine|integrative|ayush", "out_of_scope", 0.9, ""),
    (r"psycholog|counsel|behavio|autism|developmental|learning disab|cognitive", "out_of_scope", 0.85, ""),
    (r"patholog", "out_of_scope", 0.85, "surgical_oncology;chemotherapy"),  # v1.1: histopathology
    (r"microbiolog|biochem|laborator|\blab\b|cytolog|serolog|hematopathol|diagnostics?$|molecular|nuclear medicine|\bpet\b", "out_of_scope", 0.85, ""),
    (r"gynecolog|menopaus|family planning|contracept|adolescent|women'?s health|\bpcos\b|pelvic", "out_of_scope", 0.85, ""),
    (r"robotic surg|day care surg|surgery$|surgeon$", "out_of_scope", 0.6, ""),
    (r"^(public health|epidemiolog|pharmacolog|community medicine|forensic|anatomy|physiology|medical education|research|administration|hospital administration|management)", "not_a_service", 0.9, ""),
    (r"kriya sarira|rachana|dravyaguna|rasa shastra|samhita|padartha|roga nidan|agad tantra", "not_a_service", 0.9, ""),
]
COMPILED = [(re.compile(p), lab, conf, pre) for p, lab, conf, pre in RULES]


def apply_rules(norm: str) -> tuple[str, float, str, int] | None:
    """(label, confidence, prereq_for, rule_index) of the first matching rule, or None."""
    for i, (rx, lab, conf, pre) in enumerate(COMPILED):
        if rx.search(norm):
            return lab, conf, pre, i
    return None


if __name__ == "__main__":
    def lab(s: str) -> str | None:
        r = apply_rules(normalize(s))
        return r[0] if r else None
    assert normalize("gynecologyAndObstetrics") == "gynecology and obstetrics"
    assert normalize(" Nephrology & Dialysis") == "nephrology and dialysis"
    assert normalize("TMJSurgery") == "tmj surgery"
    assert lab("nephrologyIncludingDialysis") == "dialysis"
    assert lab("eyeTraumaAndEmergencyEyeCare") == "eye_emergency"
    assert lab("dentalAnesthesia") == "out_of_scope"
    assert lab("burnAndTraumaPlasticSurgery") == "burn_care"
    assert lab("neonatologyPerinatalMedicine") == "too_general"
    assert lab("pediatricCriticalCareMedicine") == "picu"
    assert lab("criticalCareMedicine") == "icu"
    assert lab("internalMedicine") == "too_general" and lab("familyMedicine") == "too_general"
    assert lab("gynecologyAndObstetrics") == "too_general" and lab("gynecology") == "out_of_scope"
    assert lab("orthopedicTraumaAndFractureSurgery") == "orthopaedic_trauma_surgery"
    assert lab("craniomaxillofacialTraumaSurgery") == "out_of_scope"
    assert lab("pediatricHematologyOncology") == "chemotherapy"
    assert lab("radiationOncology") == "radiotherapy"
    assert lab("cardiothoracicRadiology") == "too_general"
    assert lab("spineNeurosurgery") == "neurosurgery"
    assert lab("emergencyMedicine") == "emergency_24x7" and lab("accidentAndEmergency") == "emergency_24x7"
    assert lab("accidentAndTrauma") == "trauma_care" and lab("polytrauma") == "trauma_care"
    assert lab("dentistry") == "out_of_scope" and lab("Non-Interventional Cardiology") == "too_general"
    assert lab("cardiacCatheterisation") == "cath_lab_angioplasty" and lab("strokeRehabilitation") == "out_of_scope"
    assert lab("neurovascularSurgery") == "neurosurgery" and lab("orthopedicSpineSurgery") == "too_general"
    assert lab("Prostate Cancer") == "too_general" and lab("Breast Cancer") == "too_general" and lab("swasthavritta") == "out_of_scope"
    assert lab("placentalAbruption") == "too_general" and lab("haematologyAutomation") == "out_of_scope"
    assert lab("maternalFetalMedicineOrPerinatology") == "high_risk_pregnancy"
    assert lab("SNAKE BITE TREATMENT") == "snakebite_antivenom"
    assert lab("perinatalAndReproductivePsychiatry") == "psychiatric_care"
    assert lab("traumaAndJointReplacement") == "orthopaedic_trauma_surgery"  # hand check of service labels
    assert lab("Osteoporosis & Osteoporotic Fracture") == "out_of_scope"
    assert lab("fetalAndMaternalMedicine") == "high_risk_pregnancy"
    print("specialty_rules self-check ok")
