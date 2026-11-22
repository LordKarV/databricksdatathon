"""Cross-state place check for a single claim sentence.

A sentence that names a district, city or state belonging to a different state than the record
(for example "dialysis services at Aadhar Kidney And Dialysis Center in Madanapalle, Andhra Pradesh"
on a Pune record) is evidence the claim was copied from another facility's page.
Only cross-STATE mismatches are flagged: same-state neighbours are common and legitimate
(referral networks, branch lists), so they are not counted.
"""
import os, re
from collections import defaultdict
import duckdb

_ROOT = os.environ.get("DATATHON_ROOT", os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../..")))
_DATA = os.environ.get("DATATHON_DATA_ROOT", os.path.join(_ROOT, "data"))
R = os.path.join(_DATA, "raw") + "/"
STOP = {"north", "south", "east", "west", "central", "rural", "urban", "district", "city", "new", "nagar", "road",
        "medical", "hospital", "general", "civil"}
ALIASES = {  # common names not equal to an India Post district name
    "Bangalore": "KARNATAKA", "Bengaluru": "KARNATAKA", "Mysore": "KARNATAKA", "Mangalore": "KARNATAKA",
    "Bombay": "MAHARASHTRA", "Mumbai": "MAHARASHTRA", "Navi Mumbai": "MAHARASHTRA", "Calcutta": "WEST BENGAL",
    "Kolkata": "WEST BENGAL", "Madras": "TAMIL NADU", "Chennai": "TAMIL NADU", "Gurgaon": "HARYANA",
    "Gurugram": "HARYANA", "Trivandrum": "KERALA", "Cochin": "KERALA", "Kochi": "KERALA", "Vizag": "ANDHRA PRADESH",
    "Hyderabad": "TELANGANA", "Secunderabad": "TELANGANA", "Delhi": "DELHI", "New Delhi": "DELHI", "Noida": "UTTAR PRADESH",
    "Pondicherry": "PUDUCHERRY", "Orissa": "ODISHA", "Tamilnadu": "TAMIL NADU", "Uttaranchal": "UTTARAKHAND",
}
STATE_ALIASES = {"ORISSA": "ODISHA", "TAMILNADU": "TAMIL NADU", "PONDICHERRY": "PUDUCHERRY", "CHATTISGARH": "CHHATTISGARH",
                 "UP": "UTTAR PRADESH", "U.P": "UTTAR PRADESH", "U.P.": "UTTAR PRADESH", "JAMMU & KASHMIR": "JAMMU AND KASHMIR",
                 "PUNJAB REGION": "PUNJAB", "NCT OF DELHI": "DELHI"}


def _title(s):
    return " ".join(w.capitalize() for w in s.split())


def build_gazetteer():
    rows = duckdb.sql(f"select distinct upper(trim(district)) d, upper(trim(statename)) s from '{R}india_post_pincode_directory.parquet' where district is not null").fetchall()
    place2states = defaultdict(set)
    states = {s for _, s in rows if s and s != "NA"}
    for d, s in rows:
        if not s or s == "NA":
            continue
        base = re.sub(r"\s+(URBAN|RURAL|DISTRICT)$", "", d)
        for name in {d, base}:
            t = _title(name)
            if len(t) >= 5 and t.lower() not in STOP:
                place2states[t].add(s)
    for s in states:
        if len(s) >= 3 and not s.startswith("THE "):
            place2states[_title(s)].add(s)
    for a, s in ALIASES.items():
        place2states[a].add(s)
    names = sorted(place2states, key=len, reverse=True)
    # Locative context only ("in X", "at X", ", X") and not followed by a capitalised word: district names
    # double as personal and brand names (Krishna, Narmada, Anand, Nirmal, Vaishali, "Bombay Hospital").
    # Round-1 hand check without this context rule: 9 of 40 flags were real other-facility claims.
    rx = re.compile(r"(?:(?<=\bin )|(?<=\bat )|(?<=, ))(" + "|".join(re.escape(n) for n in names) + r")\b(?!\s+[A-Z(])")
    pin2state = dict(duckdb.sql(f"""select pincode, upper(mode(statename)) from '{R}india_post_pincode_directory.parquet'
                                   group by pincode""").fetchall())
    return rx, place2states, pin2state, states


RX, P2S, PIN2S, STATES = build_gazetteer()


def norm_state(s):
    if not s:
        return None
    u = re.sub(r"\s+", " ", str(s).strip().upper())
    u = STATE_ALIASES.get(u, u)
    return u if u in STATES else None


def record_states(state_field, city, pin):
    """All states the record could plausibly be in (from state text, city name, PIN)."""
    out = set()
    st = norm_state(state_field)
    if st:
        out.add(st)
    if city:
        out |= P2S.get(_title(str(city).strip()), set())
    if state_field and not st:  # state field sometimes holds a city ("Thane", "Mumbai")
        out |= P2S.get(_title(str(state_field).strip()), set())
    try:
        p = PIN2S.get(int(str(pin).strip()))
        if p:
            out.add(p)
    except (TypeError, ValueError):
        pass
    return out


def cross_state_places(sentence, rec_states):
    """Places in the sentence none of whose states is among the record's states."""
    if not rec_states:
        return []
    return sorted({m for m in RX.findall(sentence) if not (P2S[m] & rec_states)})


if __name__ == "__main__":
    rs = record_states("Maharashtra", "Nagpur", "400078")
    assert cross_state_places("Has 6 ventilators in Krishna ICU", record_states("Gujarat", "Ahmedabad", "380001")) == []
    assert cross_state_places("Offered at S L Raheja Fortis Hospital, Mumbai", rs) == []  # same state: not flagged
    assert cross_state_places("Dialysis at Aadhar Kidney Center in Madanapalle, Andhra Pradesh", record_states("Maharashtra", "Pune", "411001")) == ["Andhra Pradesh"]
    print("ok", len(P2S), "places")
