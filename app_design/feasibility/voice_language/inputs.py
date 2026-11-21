# 30 test inputs: (id, language, text, expected service, expected red flag or None if ambiguous).
# Written by the test author (not native speakers); see REPORT.md for that caveat.
SERVICES = ["dialysis", "csection", "nicu", "cardiac_surgery", "mri", "burns", "trauma", "icu", "other"]

CASES = [
    ("E1", "en", "My father needs dialysis three times a week, his kidneys have failed", "dialysis", False),
    ("E2", "en", "Wife is 38 weeks pregnant, baby is breech and labour pains started", "csection", True),
    ("E3", "en", "Newborn born at 32 weeks, very small, struggling to breathe", "nicu", True),
    ("E4", "en", "Doctor says my son needs bypass surgery, 3 blocked arteries", "cardiac_surgery", False),
    ("E5", "en", "Need MRI of lower back, pain going down the leg for 2 months", "mri", False),
    ("E6", "en", "Boiling oil fell on my arm, skin peeling off", "burns", True),
    ("E7", "en", "Bike accident on highway, head injury, bleeding, not responding", "trauma", True),
    ("E8", "en", "Grandmother on oxygen at home, breathing getting worse, needs ventilator", "icu", True),
    ("H1", "hi", "मेरी माँ को हफ्ते में तीन बार डायलिसिस करवाना पड़ता है", "dialysis", False),
    ("H2", "hi", "गर्भवती है, बच्चा उल्टा है, दर्द शुरू हो गया है", "csection", True),
    ("H3", "hi", "बच्चा समय से पहले पैदा हुआ, सांस नहीं ले पा रहा", "nicu", True),
    ("H4", "hi", "दिल का वाल्व बदलना है, डॉक्टर ने ऑपरेशन बोला है", "cardiac_surgery", False),
    ("H5", "hi", "सिर का एमआरआई करवाना है, बार बार चक्कर आते हैं", "mri", False),
    ("H6", "hi", "गैस सिलेंडर फटा, चेहरा और हाथ जल गए", "burns", True),
    ("H7", "hi", "ट्रक से टक्कर, पैर की हड्डी टूट गई, बहुत खून बह रहा है", "trauma", True),
    ("H8", "hi", "पिताजी बेहोश हैं, ऑक्सीजन कम है, आईसीयू चाहिए", "icu", True),
    ("G1", "hinglish", "meri maa ko hafte mein teen baar khoon saaf karwana padta hai", "dialysis", False),
    ("G2", "hinglish", "pregnant hai, bachcha ulta hai, dard shuru", "csection", True),
    ("G3", "hinglish", "jal gaya haath, chhaale pad gaye", "burns", None),
    ("G4", "hinglish", "bachche ka janam 7 mahine mein hua, peela pad gaya hai aur doodh nahi pee raha", "nicu", True),
    ("G5", "hinglish", "bete ke dil mein chhed hai, doctor ne operation bola hai", "cardiac_surgery", False),
    ("G6", "hinglish", "seedhi se gir gaye, sar mein chot lagi, ulti ho rahi hai", "trauma", True),
    ("G7", "hinglish", "teen din se bukhar hai aur sar dard", "other", False),
    ("G8", "hinglish", "ghutne ka MRI karwana hai, sasta kahan hoga", "mri", False),
    ("M1", "mr", "माझ्या वडिलांना आठवड्यातून दोनदा डायलिसिस करावे लागते", "dialysis", False),
    ("M2", "mr", "बायको गरोदर आहे, पाणी गेलं, बाळ आडवं आहे", "csection", True),
    ("M3", "mr", "बाळ कमी वजनाचं जन्मलं, श्वास घ्यायला त्रास होतोय", "nicu", True),
    ("M4", "mr", "स्टोव्हचा भडका उडाला, अंग भाजलं", "burns", True),
    ("M5", "mr", "अपघात झाला, डोक्याला मार लागला, शुद्ध नाही", "trauma", True),
    ("M6", "mr", "दाताचं दुखणं आहे, डेंटिस्ट हवा", "other", False),
]

assert len(CASES) == 30 and all(c[3] in SERVICES for c in CASES)

# Hard set, added after both models scored 30/30 on CASES: keyword distractors, an out-of-list
# emergency, and two languages the prompt only names generically (Bengali, Tamil).
# Expected service may be a tuple of acceptable answers.
HARD = [
    ("X1", "hinglish", "dialysis wale hospital mein MRI hoga kya? papa ka sar ka scan chahiye", "mri", False),
    ("X2", "hinglish", "pet mein pathri hai, kidney mein bahut dard", "other", None),
    ("X3", "hinglish", "bachcha 2 saal ka hai, garam doodh gir gaya poore pet aur chhati pe", "burns", True),
    ("X4", "hinglish", "seene mein tez dard, pasina aa raha hai, baayan haath sunn", ("other", "icu", "cardiac_surgery"), True),
    ("X5", "bn", "আমার বাবার সপ্তাহে দুবার ডায়ালাইসিস লাগে", "dialysis", False),
    ("X6", "ta", "குழந்தை குறைமாதத்தில் பிறந்தது, மூச்சு விட சிரமப்படுகிறது", "nicu", True),
]
