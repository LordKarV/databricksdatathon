"""Stable error codes with en and hi text for every API error (BE-T1, D-009).

Additive: a coded response keeps its old `detail`, `error` or `note` field unchanged and gains `code` (a key of
MESSAGES) and `message` {en, hi} beside it. Clients that read the old field keep working; ui2 reads `code`.
The Hindi is a draft that needs native review.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import HTTPException

# code -> (en, hi). `{state}` is filled in by payload(); every placeholder appears in both languages.
MESSAGES: dict[str, tuple[str, str]] = {
    # Request validation (pydantic 422). The location texts match ui2's place.outside_india and place.too_coarse.
    "location_outside_india": ("Your phone's location looks outside India. Type a PIN, district or town.",
                               "फ़ोन की लोकेशन भारत से बाहर दिख रही है। पिन कोड, ज़िला या कस्बे का नाम लिखें।"),
    "location_too_coarse": ("Your phone's location is too rough to use. Type a PIN, district or town.",
                            "फ़ोन की लोकेशन बहुत अंदाज़न है। पिन कोड, ज़िला या कस्बे का नाम लिखें।"),
    "location_invalid": ("Your phone's location could not be read. Type a PIN, district or town.",
                         "फ़ोन की लोकेशन पढ़ी नहीं जा सकी। पिन कोड, ज़िला या कस्बे का नाम लिखें।"),
    "text_too_long": ("Type up to 500 letters.", "500 अक्षर तक लिखें।"),
    "request_invalid": ("Something in the request was wrong. Go back and try again.",
                        "कुछ गड़बड़ हो गई। वापस जाकर फिर से कोशिश करें।"),
    # Every endpoint
    "unknown_service": ("Choose the care the patient needs from the tiles.", "मरीज़ को जो सेवा चाहिए, टाइल से चुनें।"),
    "facts_not_built": ("Hospital data is not ready on this server. In an emergency call 108.",
                        "इस सर्वर पर अस्पतालों का डेटा अभी तैयार नहीं है। इमरजेंसी में 108 पर फ़ोन करें।"),
    "internal": ("The server had a problem. Try again.", "सर्वर में दिक्कत आई। फिर से कोशिश करें।"),
    "not_found": ("This page or file was not found.", "यह पेज या फ़ाइल नहीं मिली।"),
    # /api/verify, /api/translate, /api/read-note
    "verify_not_set_up": ("Website check is not available on this server.",
                          "इस सर्वर पर वेबसाइट की जाँच उपलब्ध नहीं है।"),
    "translate_unknown_claim": ("Translation not available for this line.", "इस लाइन का अनुवाद उपलब्ध नहीं है।"),
    "note_model_unavailable": ("Could not read the note now. Pick a service.", "अभी पर्ची नहीं पढ़ी जा सकी। सेवा चुनें।"),
    "note_no_service": ("We could not tell the service from the note. Pick a service.",
                        "पर्ची से सेवा का पता नहीं चला। सेवा चुनें।"),
    # /api/transcribe
    "voice_failed": ("Voice input is not working on this server now. Use your keyboard's mic to speak.",
                     "इस सर्वर पर अभी आवाज़ से लिखना काम नहीं कर रहा। कीबोर्ड के माइक से बोलें।"),
    "voice_loading": ("Voice input is getting ready. Try again in a minute, or type.",
                      "आवाज़ से लिखना तैयार हो रहा है। एक मिनट बाद फिर कोशिश करें, या लिखें।"),
    "voice_bad_type": ("The recording could not be read. Speak again, or type.",
                       "रिकॉर्डिंग पढ़ी नहीं जा सकी। फिर से बोलें, या लिखें।"),
    "voice_unreadable": ("The recording could not be read. Try again.", "रिकॉर्डिंग पढ़ी नहीं जा सकी। फिर से कोशिश करें।"),
    "voice_too_big": ("The recording is too big. Speak for up to 15 seconds.", "रिकॉर्डिंग बहुत बड़ी है। 15 सेकंड तक बोलें।"),
    "voice_too_long": ("The recording is too long. Speak for up to 15 seconds.",
                       "रिकॉर्डिंग बहुत लंबी है। 15 सेकंड तक बोलें।"),
    # /api/outcome
    "outcome_unknown_service": ("This report names a service we do not know. It was not saved.",
                                "इस रिपोर्ट की सेवा हमारी सूची में नहीं है। रिपोर्ट सेव नहीं हुई।"),
    "outcome_not_listed": ("This hospital is not listed for this service. The report was not saved.",
                           "यह अस्पताल इस सेवा के लिए सूची में नहीं है। रिपोर्ट सेव नहीं हुई।"),
    "outcome_bad_kind": ("This answer does not fit this kind of report. It was not saved.",
                         "यह जवाब इस तरह की रिपोर्ट से मेल नहीं खाता। रिपोर्ट सेव नहीं हुई।"),
    "outcome_bad_reason": ("A reason can only go with a no or a turn-away. The report was not saved.",
                           "कारण सिर्फ़ 'नहीं' या 'लौटा दिया' वाले जवाब के साथ दिया जा सकता है। रिपोर्ट सेव नहीं हुई।"),
    "outcome_bad_wait": ("A wait can only go with a visit report. The report was not saved.",
                         "इंतज़ार का समय सिर्फ़ अस्पताल जाने वाली रिपोर्ट के साथ दिया जा सकता है। रिपोर्ट सेव नहीं हुई।"),
    "outcome_rate_limited": ("You already reported this hospital for this service in the last 24 hours.",
                             "आप पिछले 24 घंटे में इस अस्पताल और सेवा की रिपोर्ट दे चुके हैं।"),
    # The reports store (/api/outcome, /api/outcomes/summary, /api/pulse)
    "store_not_set_up": ("Field reports are not set up on this server.",
                         "इस सर्वर पर फ़ील्ड रिपोर्ट की सुविधा चालू नहीं है।"),
    "store_failed": ("The reports store did not answer just now. Try again later.",
                     "रिपोर्ट का रिकॉर्ड अभी जवाब नहीं दे रहा। थोड़ी देर बाद फिर कोशिश करें।"),
    # /api/pulse
    "pulse_need_where": ("Choose a district.", "ज़िला चुनें।"),
    "pulse_unknown_district": ("We have no district by that name.", "इस नाम का ज़िला हमारे डेटा में नहीं है।"),
    "pulse_no_district_for_point": ("We could not tell the district for this place. Choose one.",
                                    "इस जगह का ज़िला पता नहीं चला। ज़िला चुनें।"),
    "pulse_unknown_service": ("Choose a service from the list.", "सूची से सेवा चुनें।"),
    "pulse_demo_missing": ("Area counts are not available now.", "इलाके के आँकड़े अभी उपलब्ध नहीं हैं।"),
    # Page data, packs and places
    "how_not_built": ("This page is not available now.", "यह पेज अभी उपलब्ध नहीं है।"),
    "stories_not_built": ("This page is not available now.", "यह पेज अभी उपलब्ध नहीं है।"),
    "packs_not_built": ("Offline data is not available from this server.",
                        "इस सर्वर से बिना इंटरनेट वाला डेटा नहीं मिल सकता।"),
    "pack_no_state": ("Offline data for {state} is not available.", "{state} का बिना इंटरनेट वाला डेटा उपलब्ध नहीं है।"),
    "place_not_found": ("We could not find that place. Type a 6-digit PIN, or a district or town name.",
                        "यह जगह नहीं मिली। 6 अंकों का पिन कोड, या ज़िले या कस्बे का नाम लिखें।"),
}

LOCATION_FIELDS = frozenset({"lat", "lon", "accuracy_m"})
LOCATION_PATHS = frozenset({"/api/plan", "/api/recommend", "/api/place"})
_BOUND_TYPES = frozenset({"greater_than_equal", "less_than_equal", "greater_than", "less_than"})


def payload(code: str, **fmt: str) -> dict[str, Any]:
    """{code, message: {en, hi}} to merge beside a response's existing fields."""
    en, hi = MESSAGES[code]
    return {"code": code, "message": {"en": en.format(**fmt), "hi": hi.format(**fmt)}}


class Coded(HTTPException):
    """An HTTPException whose JSON body gains `code` and `message` beside the usual `detail`."""

    def __init__(self, code: str, status_code: int, detail: Any = None) -> None:
        if code not in MESSAGES:
            raise KeyError(code)
        super().__init__(status_code, detail)
        self.code = code


class Invalid(ValueError):
    """A ValueError with a code, for bad input found below the endpoint (outcomes, pulse); answered with 422."""

    def __init__(self, code: str, message: str) -> None:
        if code not in MESSAGES:
            raise KeyError(code)
        super().__init__(message)
        self.code = code


def _field(loc: Sequence[Any]) -> str | None:
    # ("body", "lat") from the JSON body, ("query", "lat") from /api/recommend
    return loc[1] if len(loc) == 2 and loc[0] in ("body", "query") and isinstance(loc[1], str) else None


def validation_code(path: str, errs: Sequence[dict[str, Any]]) -> str:
    """The code for a pydantic 422: a location code on the point endpoints when the point itself is wrong."""
    by_field = [(_field(e.get("loc", ())), e.get("type")) for e in errs]
    loc_errs = [(f, t) for f, t in by_field if f in LOCATION_FIELDS]
    if path in LOCATION_PATHS and loc_errs:
        if any(f in ("lat", "lon") and t in _BOUND_TYPES for f, t in loc_errs):
            return "location_outside_india"  # a point outside India's box wins over a rough fix of it
        if any(f == "accuracy_m" and t in ("less_than_equal", "less_than") for f, t in loc_errs):
            return "location_too_coarse"
        return "location_invalid"  # missing, not a number, NaN, or a negative accuracy
    if path == "/api/parse" and any(f == "text" and t == "string_too_long" for f, t in by_field):
        return "text_too_long"
    return "request_invalid"
