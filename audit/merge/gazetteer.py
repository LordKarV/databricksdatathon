"""Place lexicon (district / city / state -> states, districts) and per-record own location.

Sources: india_post_pincode_directory (districts, states, PIN -> district/state) and the
facility table's own address_city values (a city enters the lexicon only if >= 3 records
use it and >= 80% of them sit in one PIN-derived state).
"""
import os, re
from collections import Counter, defaultdict
import pandas as pd

_ROOT = os.environ.get("DATATHON_ROOT", os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../..")))
_DATA = os.environ.get("DATATHON_DATA_ROOT", os.path.join(_ROOT, "data"))
PIN = os.path.join(_DATA, "raw/india_post_pincode_directory.parquet")

STATE_ALIASES = {
    "orissa": "odisha", "tamilnadu": "tamil nadu", "pondicherry": "puducherry",
    "jammu & kashmir": "jammu and kashmir", "nct of delhi": "delhi", "new delhi": "delhi",
    "chattisgarh": "chhattisgarh", "uttaranchal": "uttarakhand", "the dadra and nagar haveli and daman and diu": "dadra and nagar haveli and daman and diu",
}
CITY_ALIASES = {  # old / alternate name -> name that is in the lexicon
    "bangalore": "bengaluru", "bombay": "mumbai", "madras": "chennai", "calcutta": "kolkata",
    "gurgaon": "gurugram", "trivandrum": "thiruvananthapuram", "cochin": "kochi",
    "mysore": "mysuru", "vizag": "visakhapatnam", "baroda": "vadodara", "poona": "pune",
    "calicut": "kozhikode", "mangalore": "mangaluru", "belgaum": "belagavi", "hubli": "hubballi",
    "gulbarga": "kalaburagi", "trichy": "tiruchirappalli", "allahabad": "prayagraj",
    "benares": "varanasi", "banaras": "varanasi", "ahmadabad": "ahmedabad", "noida": "gautam buddha nagar",
}
# place names that are also common person names, deities, rivers or English words in this text
AMBIGUOUS = {
    "anand", "sagar", "puri", "dhar", "krishna", "mon", "nalanda", "vaishali", "hassan",
    "prakasam", "narmada", "tapi", "ganga", "aravalli", "arvalli", "dang", "central", "north",
    "south", "east", "west", "city", "banka", "gandhi", "raja", "ram", "salem", "sabarkantha",
    "sri", "shree", "jamui", "mahe", "na", "bishnupur", "kalimpong", "pratapgarh", "rohini",
    "lalitpur", "ganganagar", "amethi", "ayodhya", "basti", "kheda", "deoghar", "nagar",
    "nicobar", "leh", "khanna", "kalyan", "banga", "sri sathya sai", "north east", "sathya sai",
}


def norm(s):
    s = (s or "").lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_state(s):
    n = norm(s)
    return STATE_ALIASES.get(n, n)


def build(df):
    """Return (lex, own). lex: name -> {'states': set, 'districts': set, 'kind': str};
    own: DataFrame indexed by unique_id with own_states, own_districts, own_names."""
    p = pd.read_parquet(PIN, columns=["pincode", "district", "statename"])
    p = p[p.statename != "NA"]
    p["d"] = p.district.map(norm)
    p["s"] = p.statename.map(norm_state)
    lex = defaultdict(lambda: {"states": set(), "districts": set(), "kind": ""})
    for d, s in p[["d", "s"]].drop_duplicates().itertuples(index=False):
        lex[d]["states"].add(s); lex[d]["districts"].add(d); lex[d]["kind"] = "district"
        for alt in (d.replace(" urban", "").replace(" rural", ""),):
            if alt != d and alt:
                lex[alt]["states"].add(s); lex[alt]["districts"].add(d); lex[alt]["kind"] = "district"
    for s in set(p.s):
        lex[s]["states"].add(s); lex[s]["kind"] = "state"
    pin_mode = p.groupby("pincode").agg(d=("d", lambda x: Counter(x).most_common(1)[0][0]),
                                        s=("s", lambda x: Counter(x).most_common(1)[0][0]))
    pin_d, pin_s = pin_mode.d.to_dict(), pin_mode.s.to_dict()

    zp = pd.to_numeric(df.address_zipOrPostcode.str.extract(r"(\d{6})")[0], errors="coerce")
    rec = pd.DataFrame({"uid": df.unique_id.values, "city": df.address_city.map(norm).values,
                        "state": df.address_stateOrRegion.map(norm_state).values,
                        "pd": zp.map(pin_d).values, "ps": zp.map(pin_s).values})
    # city lexicon from facility rows: majority PIN state and district
    for city, g in rec.dropna(subset=["ps"]).groupby("city"):
        if len(city) < 3 or len(g) < 3 or city in lex:
            continue
        st, n = Counter(g.ps).most_common(1)[0]
        if n / len(g) >= 0.8:
            lex[city]["states"].add(st); lex[city]["kind"] = "city"
            lex[city]["districts"].update(x for x in g.pd if x)
    for a, b in CITY_ALIASES.items():
        if b in lex:
            lex[a] = {"states": set(lex[b]["states"]), "districts": set(lex[b]["districts"]), "kind": lex[b]["kind"]}
    for k in AMBIGUOUS:
        lex.pop(k, None)
    lex = dict(lex)

    own = {}
    for r in rec.itertuples(index=False):
        sts, ds, names = set(), set(), {r.city} if r.city else set()
        if r.state in lex and lex[r.state]["kind"] == "state":
            sts.add(r.state)
        elif r.state in lex:  # state field holds a city/district
            sts |= lex[r.state]["states"]; ds |= lex[r.state]["districts"]; names.add(r.state)
        if isinstance(r.ps, str):
            sts.add(r.ps); ds.add(r.pd)
        if r.city in lex:
            ds |= lex[r.city]["districts"]
            if lex[r.city]["kind"] != "state":
                sts |= lex[r.city]["states"]
        own[r.uid] = {"own_states": sts, "own_districts": ds, "own_names": names,
                      "claimed_state": r.state, "pin_state": r.ps}
    return lex, pd.DataFrame.from_dict(own, orient="index")


def place_regex(lex):
    names = sorted((k for k in lex if len(k) >= 4), key=len, reverse=True)
    # Title-case or upper-case match in the raw text; lowercase words are not taken as places
    pats = [r"\s+".join(w.capitalize() for w in n.split()) for n in names]
    return re.compile(r"\b(" + "|".join(pats) + r")\b", re.I), {n.replace(" ", ""): n for n in names}


LOCALITY_AFTER = re.compile(r"\s*(Colony|Nagar|Cross|Road|Rd|Layout|Street|Marg|Chowk|Gate|Circle|Bazar|Bazaar|Market|Park|Extension|Ext)\b")
PERSON_BEFORE = re.compile(r"(Dr\.?|Mr\.?|Mrs\.?|Ms\.?|Shri|Smt\.?)\s*(\w\.?\s*){0,3}$")


def find_places(text, rx):
    """Title-case place names, skipping locality names ('Jodhpur Cross Road') and person names."""
    out = []
    for m in rx.finditer(text):
        tok = m.group(1)
        if not tok[0].isupper():
            continue
        if LOCALITY_AFTER.match(text, m.end()) or PERSON_BEFORE.search(text[:m.start()]):
            continue
        out.append(norm(tok))
    return out
