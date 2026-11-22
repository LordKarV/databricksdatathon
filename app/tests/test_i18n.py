"""UI2 strings (design/ui2/SPEC.md, language system): one strings file per language, one language on screen.

- en.json and hi.json have the same keys and no empty value;
- every key the page code asks for exists (th('...') / ts('...') in app/static/*.js);
- no inline bilingual span is left in the page code (the UI1 pattern `<span lang="hi">(...)</span>` next to English);
- Hindi uses the reviewed glossary spellings (kb/taxonomy/HINDI_GLOSSARY.md).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
EN = json.loads((STATIC / "i18n" / "en.json").read_text())
HI = json.loads((STATIC / "i18n" / "hi.json").read_text())


def test_same_keys_and_no_empty_value():
    en, hi = set(EN) - {"engine"}, set(HI) - {"engine", "langs"}  # langs: native names for the chooser
    assert en == hi, f"only in en: {sorted(en - hi)}; only in hi: {sorted(hi - en)}"
    assert not [k for k in en if not str(EN[k]).strip() or not str(HI[k]).strip()]


def test_slots_match_between_languages():
    slot = re.compile(r"\{(\w+)\}")
    bad = [k for k in EN if not k.startswith("_") and k != "engine"
           and sorted(slot.findall(EN[k])) != sorted(slot.findall(HI[k]))]
    assert not bad, f"slots differ: {bad}"


def test_every_key_the_code_uses_exists():
    used = set()
    for f in STATIC.glob("*.js"):
        used |= set(re.findall(r"\b(?:th|ts|T|t)\('([a-z0-9_]+\.[a-z0-9_.]*[a-z0-9_])'", f.read_text()))
    missing = sorted(k for k in used if k not in EN)
    assert not missing, f"keys used but not in en.json: {missing}"


def test_no_inline_bilingual_spans():
    hits = [f"{f.name}:{i}" for f in STATIC.glob("*.js") for i, line in enumerate(f.read_text().splitlines(), 1)
            if re.search(r'<span lang="hi">', line)]
    assert not hits, f"inline Hindi next to English: {hits}"


def test_glossary_spellings():
    text = json.dumps(HI, ensure_ascii=False)
    # glossary: हिन्दी (not हिंदी); nukta on फ़ and ज़; पर्ची for slip; आयुष्मान कार्ड for PM-JAY
    for wrong in ("हिंदी", "फोन", "मुफ्त", "ज्यादा", "जिला", "स्लिप", "पुष्टि नहीं", "आपात"):
        assert wrong not in text, f"not the glossary spelling: {wrong}"
    assert HI["band.likely"] == "संभावना ज़्यादा" and HI["band.not_verified"] == "पक्का नहीं"
    assert HI["band.unlikely"] == "संभावना कम" and HI["lang.name"] == "हिन्दी"
