"""Offline path (danger words + lexicon, no model) on 120 written utterances: 40 Devanagari, 40 Hinglish, 40 English.

The Devanagari set mixes clean sentences with speech-to-text style spellings; four are the faster-whisper "small"
transcripts from app_design/feasibility/voice_language/out/asr_small.json (H1, H2, H6, H7). Expected services follow
kb/taxonomy (postpartum bleeding routes to emergency_csection). The team wrote the utterances, the phrases and the
fuzzy threshold, so these numbers are optimistic; they are not a field test.

Correct = the offline path names exactly the expected service (or nothing when none is expected); 95% Wilson
interval. Measured 2026-11-21:
                   before (HEAD: exact match)   after (Hindi phrases + folding + fuzzy 0.86)
  Devanagari       11/40 0.28 [0.16, 0.43]      40/40 1.00 [0.91, 1.00]
  Hinglish         23/40 0.57 [0.42, 0.71]      40/40 1.00 [0.91, 1.00]
  English          26/40 0.65 [0.50, 0.78]      28/40 0.70 [0.55, 0.82]   (English phrases were not the task)
  all              60/120 0.50 [0.41, 0.59]     108/120 0.90 [0.83, 0.94]
Danger: all 13 danger utterances reach the danger card after (before: 2 Devanagari ones missed, the ASR spelling
खुन and the unmarked नही); no utterance without danger words raises it.
The first pass (phrases written before this set existed) scored 105/120. Fixes from its misses and from the
existing tests: "gir gaya" (fell) left trauma because "garam paani gir gaya" is a burn; postpartum bleeding phrases
joined the C-section service as the taxonomy routes them; "newborn" left nicu (it sent test_inputs' model-fallback
sentence to the lexicon); bachcha/baccha/bacha fold together; romanised phrases no longer fuzzy-match ("jana"
matched "jalna"). So 108 is partly fitted to this set. EVERYDAY below holds 20 sentences that must match nothing.
Fuzzy threshold sweep (all / wrong service / false danger): 0.78 to 0.82: 108/0/2, 0.84 to 0.88: 108/0/0,
0.90: 106/0/0, exact only: 105/0/0. 0.86 sits in the middle of the zero-false-danger plateau.
Real ASR transcripts (faster-whisper small, forced Hindi): H1, H2, H6, H7 route correctly; G1 (a Hinglish speaker,
CER 0.84) does not ("कुन साव" for "khoon saaf" scores 0.83).
Run `python app/tests/test_hindi_lexicon.py` to print the after table.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inputs import understand as u  # noqa: E402, RUF100

D, T, B, N, M, C = "dialysis", "trauma_emergency", "burn_care", "nicu", "mri", "cardiac_surgery"
S = "emergency_csection"
# (text, expected service or None, danger expected)
DEVANAGARI = [
    ("मेरी माको हवते में 3 भार डायलेसिस करवाना परता है", D, False),
    ("मेरी माँ को हफ्ते में तीन बार डायलिसिस करवाना पड़ता है", D, False),
    ("पापा की किडनी फेल हो गई है", D, False),
    ("हर हफ्ते खुन साफ करवाने जाना पड़ता है", D, False),
    ("डायलीसिस कहाँ होता है पास में", D, False),
    ("गुरदे खराब हैं डॉक्टर ने मशीन बोला", D, False),
    ("गर्भवति है, बचा उलता है, दर्द शुरो हो गया है", S, False),
    ("डॉक्टर ने कहा ऑपरेशन से डिलीवरी होगी", S, False),
    ("सिजेरियन करना पड़ेगा बड़े अस्पताल जाओ", S, False),
    ("बच्चा आडा है नॉर्मल नहीं होगा", S, False),
    ("सिझेरियन के लिए रेफर किया है", S, False),
    ("डिलेवरी में दिक्कत है दर्द बहुत है", S, False),
    ("नवजात बच्चा बहुत कमजोर है", N, False),
    ("बच्चा समय से पहले पैदा हुआ है वजन कम है", N, False),
    ("बच्चे को पिलिया है और दूध नहीं पी रहा", N, False),
    ("नया बच्चा कमज़ोर पैदा हुआ", N, False),
    ("बचे को शीशे वाली मशीन में रखना है", N, False),
    ("सातवे महीने में पैदा हुआ बच्चा", N, False),
    ("प्रक्सी तक्कर प्र की हदी तुट गई बहुत खुन बह रहा है", T, True),
    ("ट्रक से टक्कर, पैर की हड्डी टूट गई, बहुत खून बह रहा है", T, True),
    ("छत से गिर गया सिर में चोट है", T, False),
    ("बाइक का एक्सिडेंट हुआ है", T, False),
    ("हाथ की हड्डी टूटी लगती है", T, False),
    ("पेड से गिरा पैर टुट गया", T, False),
    ("गया सिलिंदर पटा, चेहरा और हात जल गय.", B, False),
    ("गैस सिलेंडर फटा, चेहरा और हाथ जल गए", B, False),
    ("बच्चे पर गरम पानी गिर गया", B, False),
    ("आग में झुलस गई है", B, False),
    ("करंट लगा है हाथ काला पड़ गया", B, False),
    ("तेजाब से जला है", B, False),
    ("सिर का एमआरआई करवाना है", M, False),
    ("एम आर आई कहाँ सस्ता होता है", M, False),
    ("डॉक्टर ने MRI लिखा है", M, False),
    ("बच्चे के दिल में छेद है ऑपरेशन करवाना है", C, False),
    ("पिताजी का बाईपास होना है", C, False),
    ("दिल का वाल्व बदलना है", C, False),
    ("बेहोश हो गया है जवाब नहीं दे रहा", None, True),
    ("बच्चा सांस नही ले रहा", None, True),
    ("डिलीवरी के बाद बहुत खून जा रहा है", S, True),
    ("सांप ने काटा है पैर पर", None, True),
]
HINGLISH = [
    ("meri maa ko hafte mein teen baar khoon saaf karwana padta hai", D, False),
    ("papa ka dialisis karwana hai", D, False),
    ("kidney kharab hai doctor ne machine lagane bola", D, False),
    ("gurde fail ho gaye hain", D, False),
    ("dyalisis center kahan hai", D, False),
    ("khun saf karne wali machine chahiye", D, False),
    ("bachcha ulta hai dard shuru ho gaya", S, False),
    ("operation se delivery hogi doctor bole", S, False),
    ("sizerian karna padega", S, False),
    ("normal delivery nahi ho payegi", S, False),
    ("baccha aada hai pet mein", S, False),
    ("c section ke liye bada hospital", S, False),
    ("navjat bachcha kamzor hai", N, False),
    ("bacha samay se pehle hua hai", N, False),
    ("baby ko piliya hai bahut", N, False),
    ("kam vajan ka baccha hai 1 kilo", N, False),
    ("bachche ko sheeshe ki machine mein rakhna hai", N, False),
    ("premature baby hai saat mahine ka", N, False),
    ("road pe accident ho gaya", T, False),
    ("chhat se gir gaya sar pe chot", T, False),
    ("haddi toot gayi pair ki", T, False),
    ("bike se gira haath tut gaya", T, False),
    ("truck ki takkar hui hai", T, False),
    ("exident hua hai jaldi batao", T, False),
    ("haath jal gaya chai se", B, False),
    ("garam paani gir gaya bachche par", B, False),
    ("aag se jhulas gaya", B, False),
    ("current laga hai khet mein", B, False),
    ("cylinder phata aur jal gaye", B, False),
    ("tezaab se jala hai chehra", B, False),
    ("sar ka mri karana hai", M, False),
    ("MRI kitne ka hota hai", M, False),
    ("badi machine wali jaanch karwani hai", M, False),
    ("dil ka operation karwana hai", C, False),
    ("bypass surgery kahan hoti hai", C, False),
    ("bachche ke dil mein ched hai", C, False),
    ("behosh pada hai", None, True),
    ("saans nahi aa rahi bachche ko", None, True),
    ("bahut khoon beh raha hai", None, True),
    ("seene mein dard ho raha hai", None, True),
]
ENGLISH = [
    ("My father needs dialysis three times a week, his kidneys have failed", D, False),
    ("kidney failure patient needs haemodialysis", D, False),
    ("where can I get dialysis near me", D, False),
    ("renal failure, needs blood cleaning machine", D, False),
    ("dialysis session twice weekly", D, False),
    ("her kidneys stopped working", D, False),
    ("emergency c-section needed", S, False),
    ("baby is breech and labour has started", S, False),
    ("obstructed labour, needs caesarean", S, False),
    ("doctor said LSCS", S, False),
    ("transverse lie, refer for operation", S, False),
    ("cesarean delivery hospital", S, False),
    ("premature baby, very small", N, False),
    ("newborn is very weak and not feeding", N, False),
    ("low birth weight baby needs NICU", N, False),
    ("baby has jaundice after birth", N, False),
    ("SNCU referral for newborn", N, False),
    ("baby needs incubator", N, False),
    ("road accident near the market", T, False),
    ("fell from the roof, head injury", T, False),
    ("leg fracture after a fall", T, False),
    ("motorbike crash, broken arm", T, False),
    ("trauma centre needed for accident victim", T, False),
    ("hit by a truck", T, False),
    ("burns on the face and hands", B, False),
    ("hot oil fell on her arm", B, False),
    ("child burned by boiling water", B, False),
    ("electric shock burn", B, False),
    ("acid attack victim", B, False),
    ("burn unit nearest", B, False),
    ("MRI scan of the brain", M, False),
    ("need an MRI for back pain", M, False),
    ("where is the nearest MRI", M, False),
    ("valve replacement surgery", C, False),
    ("heart surgery for a child", C, False),
    ("bypass surgery needed", C, False),
    ("hole in the heart of my baby", C, False),
    ("he is unconscious and not responding", None, True),
    ("heavy bleeding after delivery", S, True),
    ("snake bite on the leg", None, True),
]
SETS = {"devanagari": DEVANAGARI, "hinglish": HINGLISH, "english": ENGLISH}
ALL = [row for rows in SETS.values() for row in rows]


def offline(mod, text: str) -> tuple[str | None, bool]:
    """(service, danger) from danger words and the lexicon alone; no model call."""
    hits = mod.lexicon_hits(text)
    danger = mod.danger_hit(text) is not None
    if danger:
        hits = {k: v for k, v in hits.items() if k not in mod.PLANNED}
    return (next(iter(hits)) if len(hits) == 1 else None), danger


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    p = k / n
    centre, half = p + z * z / (2 * n), z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - half) / (1 + z * z / n), (centre + half) / (1 + z * z / n)


def score(mod) -> dict[str, tuple[int, int]]:
    out = {name: (sum(offline(mod, t)[0] == want for t, want, _ in rows), len(rows)) for name, rows in SETS.items()}
    out["all"] = (sum(k for k, _ in out.values()), len(ALL))
    return out


def test_set_shape():
    assert [len(r) for r in SETS.values()] == [40, 40, 40]
    assert len({t for t, _, _ in ALL}) == 120


def test_offline_accuracy_after():
    s = score(u)
    k, n = s["all"]
    assert wilson(k, n)[0] >= 0.80, s  # measured 108/120, lower bound 0.83
    assert s["devanagari"][0] >= 38 and s["hinglish"][0] >= 38, s


@pytest.mark.parametrize("text,want,danger", [r for r in ALL if r[2]])
def test_danger_utterances_always_route_to_danger(text, want, danger):
    assert u.danger_hit(text), text
    r = u.parse_text(text)
    assert r["danger"] and r["service"] not in u.PLANNED


EVERYDAY = [  # no service and no danger words: the matcher must stay quiet
    "मैं बाज़ार जा रहा हूँ", "वो लोग घर चले गए", "बुखार और खांसी है", "पेट में दर्द है", "बच्चे को दस्त लग गए",
    "आज बहुत गर्मी है", "पानी गिर गया फर्श पर", "दवाई कहाँ मिलेगी", "टीका लगवाना है", "मेरी सास बीमार है",
    "ghar ja gaye sab", "wo chal gaya", "mujhe jana hai bazaar", "bukhar hai do din se", "pet mein dard hai",
    "khana kha liya", "dawai kahan milegi", "tika lagwana hai bachche ko", "fever and cough for two days",
    "where is the pharmacy",
]


@pytest.mark.parametrize("text", EVERYDAY)
def test_everyday_words_match_nothing(text):
    assert (u.lexicon_hits(text), u.danger_hit(text)) == ({}, None)


def test_no_false_danger_on_this_set():
    assert [t for t, _, d in ALL if not d and u.danger_hit(t)] == []


@pytest.mark.parametrize("raw,variant", [
    ("डायलिसिस", "डायलीसिस"), ("बच्चा उल्टा", "बचा उलता"), ("हड्डी टूट", "हड्डि टुट"), ("ज़हर", "जहर"),
    ("सांस नहीं", "साँस नही"), ("khoon saaf", "khun saf"), ("chhed", "ched"),
])
def test_fold_merges_asr_variants(raw, variant):
    assert u.fold(raw) == u.fold(variant)


def test_fuzzy_needs_length_and_threshold():
    assert u.fuzzy_ratio("डायलसिस", "डायलिसिस") >= u.FUZZY_MIN_RATIO
    assert "trauma_emergency" not in u.lexicon_hits("chota bachcha hai")  # word edges still hold
    assert u.lexicon_hits("jahan jana hai") == {}  # short words never fuzzy-match


if __name__ == "__main__":
    for name, (k, n) in score(u).items():
        lo, hi = wilson(k, n)
        print(f"{name:10} {k:3}/{n}  {k / n:.2f}  [{lo:.2f}, {hi:.2f}]")
