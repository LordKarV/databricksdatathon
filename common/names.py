"""Facility names for display: many scraped names carry the street address after a comma or a dash.

    display_name("Phular Superspeciality Hospital, Road No-02, Juran Chappra, Muzaffarpur - 842001")
    -> "Phular Superspeciality Hospital"

The name is cut at the first comma or spaced dash whose remainder holds a 6-digit PIN, a street word (Road, Rd,
Near, Nr, Opp, Sector, Plot) or a house number (746/1, No. 12, Shop No 1, or a part that starts with a number,
2nd included). A remainder with none of them stays, so "X Hospital & Research Centre, Patna" is unchanged. Only
the shown name changes: the raw name stays in derived/ and in the website check, where it is matched and cited.
A possessive the source title-cased ("Pawar'S Clinic") is shown as "Pawar's Clinic"; an all-caps name ("SAMAL'S")
keeps its case. Standard library only.
"""
import re

_SEP = re.compile(r",|\s-\s|[\u2013\u2014]")  # a hyphen needs spaces: Multi-Speciality, Radio- Diagnostic stay
_ADDRESS = re.compile(
    r"\b\d{6}\b"                                              # PIN code
    r"|\b(?:road|rd|near|nr|opp|opposite|sector|plot)\b"      # street words
    r"|\b\d+[a-z]?/\d+[a-z]?\b"                               # house number 746/1, 6/18f
    r"|\b(?:no|shop\s+no|door\s+no|h\.?\s?no)\b[.\-\s]*\d+"  # No. 12, Shop No 1, Shop No.-1
    r"|^\s*\d+(?:st|nd|rd|th)?\b",                             # remainder starts with a number (not 24x7, 3T MRI)
    re.IGNORECASE)
MIN_LEN = 3  # never cut a name down to almost nothing
_POSSESSIVE = re.compile(r"(?<=[a-z])(['\u2019])S\b")  # Pawar'S -> Pawar's; SAMAL'S has no lowercase before it


def display_name(raw):
    """raw without its address tail and with its possessive in lower case; raw itself when it is not a string."""
    if not isinstance(raw, str):
        return raw
    shown = raw
    for m in _SEP.finditer(raw):
        if _ADDRESS.search(raw[m.end():]):
            head = raw[:m.start()].rstrip(" ,-\u2013\u2014")
            shown = head if len(head) >= MIN_LEN else raw
            break
    return _POSSESSIVE.sub(r"\1s", shown)
