"""Minimal self-check for the mention classifier. Run: ../../.venv/bin/python test_detect.py"""
import detect as d

lex = {"mumbai": {"states": {"maharashtra"}, "districts": {"mumbai"}, "kind": "district"},
       "nagpur": {"states": {"maharashtra"}, "districts": {"nagpur"}, "kind": "district"},
       "ludhiana": {"states": {"punjab"}, "districts": {"ludhiana"}, "kind": "district"},
       "mohali": {"states": {"punjab"}, "districts": {"sas nagar"}, "kind": "city"}}


def rec(name, districts, names):
    t = d.toks(name)
    return {"name_toks": t, "name_dist": [x for x in t if x not in d.GENERIC and len(x) > 1],
            "name_caps": set(), "own_states": {"punjab", "maharashtra"}, "own_districts": districts, "own_names": names}


wock = rec("Wockhardt Hospital Nagpur", {"nagpur"}, {"nagpur"})
assert d.classify_mention("S L Raheja Fortis Hospital", "Mumbai", wock, lex)[0] == "foreign"
assert d.classify_mention("Wockhardt Hospital", None, wock, lex)[0] == "self"
assert d.classify_mention("Top Hospitals In Nagpur", None, wock, lex)[0] == "generic"
fortis = rec("Fortis Hospital Mohali", {"sas nagar"}, {"mohali"})
assert d.classify_mention("Fortis Hospital", "Ludhiana", fortis, lex)[0] == "sibling"
batra = rec("Batra Hospital", {"ludhiana"}, {"ludhiana"})
assert d.classify_mention("Katra Hospital", None, batra, lex)[0] == "foreign"  # near-spelling is not self
print("ok")
