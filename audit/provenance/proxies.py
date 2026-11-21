"""Contamination proxies used to test whether source class predicts bad records.

P1 pin_state_mismatch: stated state (normalized) not among the PIN directory states for the
   stated PIN.
P2 url_cross_state: a facility-page URL on justdial/practo/lybrate/hexahealth/medindia names a
   city (or, for medindia, a state) that resolves unambiguously to a different state than the
   record's stated state.
P3 foreign_name: a procedure/equipment/capability sentence names an institution
   ('X Hospital', 'X Medical College', ...) whose distinctive words do not appear in the
   record's own name.
"""
import re

from rapidfuzz import fuzz

from common import CANON_STATES, STATE_ALIASES, pincodes

# --- P2 ---------------------------------------------------------------------------------
CITY_ALIASES = {
    "bangalore": "bengaluru", "gurgaon": "gurugram", "bombay": "mumbai", "trivandrum":
    "thiruvananthapuram", "calicut": "kozhikode", "cochin": "ernakulam", "kochi": "ernakulam",
    "mysore": "mysuru", "baroda": "vadodara", "pondicherry": "puducherry", "vizag":
    "visakhapatnam", "allahabad": "prayagraj", "madras": "chennai", "calcutta": "kolkata",
    "poona": "pune", "trichy": "tiruchirappalli", "mangalore": "dakshinakannada", "belgaum":
    "belagavi", "hubli": "dharwad", "navimumbai": "thane", "newdelhi": "delhi", "noida":
    "gautambuddhanagar", "greaternoida": "gautambuddhanagar", "mohali": "sahibzadaajitsinghnagar",
    "aurangabad": "aurangabad", "ahmednagar": "ahmednagar", "gulbarga": "kalaburagi",
    "bellary": "ballari", "shimoga": "shivamogga", "tumkur": "tumakuru", "bijapur": "vijayapura",
    "secunderabad": "hyderabad", "thane": "thane", "kalyan": "thane", "vasai": "palghar",
    "panvel": "raigad", "pimprichinchwad": "pune", "howrah": "howrah", "ghaziabad": "ghaziabad",
    "faridabad": "faridabad",
}
STATE_SLUGS = {re.sub(r"[^a-z]", "", s.lower()): s for s in CANON_STATES}
STATE_SLUGS.update({re.sub(r"[^a-z]", "", k.lower()): v for k, v in STATE_ALIASES.items()
                    if len(re.sub(r"[^a-z]", "", k)) > 3})
CITY_URL_HOSTS = ("justdial.com", "practo.com", "lybrate.com", "hexahealth.com")
NON_CITY_SLUGS = {"india", "amp", "doctor", "doctors", "hospital", "hospitals", "clinic",
                  "search", "national", "online", "all", "consult", "c", "p", "en"}


def _k(s):
    return re.sub(r"[^a-z]", "", str(s).lower())


def place_states():
    """place key -> set of states, from PIN directory district names and office names
    (office suffixes like ' H.O', ' S.O', ' B.O' removed)."""
    p = pincodes()
    p = p[p.statename != "NA"]
    out = {}
    for col in ("district", "officename"):
        names = p[col].str.replace(r"\s+(H\.?O|S\.?O|B\.?O|G\.?P\.?O)\.?$", "", regex=True)
        for n, s in zip(names, p.statename):
            out.setdefault(_k(n), set()).add(s)
    return out


def url_place(url):
    """(kind, key) parsed from a directory URL, or None. kind is 'city' or 'state'."""
    m = re.match(r"https?://(?:www\.|m\.)?([^/]+)/([^/?#]+)", url)
    if not m:
        return None
    h, seg = m.group(1).lower(), m.group(2)
    if h.endswith("medindia.net"):
        # /directories/hospitals/<name>-<city>-<state>-<id>.htm
        mm = re.search(r"-([a-z-]+)-(\d+)\.htm", url.lower())
        if mm:
            parts = mm.group(1).split("-")
            for n in (3, 2, 1):
                key = "".join(parts[-n:])
                if key in STATE_SLUGS:
                    return ("state", STATE_SLUGS[key])
        return None
    if not h.endswith(CITY_URL_HOSTS):
        return None
    key = _k(seg)
    if len(key) < 3 or key in NON_CITY_SLUGS:
        return None
    return ("city", CITY_ALIASES.get(key, key))


# --- P3 ---------------------------------------------------------------------------------
HEADS = (r"(?:Hospitals?|Medical College(?: (?:and|&) Hospital)?|Medical Cent(?:re|er)|"
         r"Nursing Home|Institute of Medical Sciences|Medical Mission|Infirmary)")
NAME_RX = re.compile(r"((?:(?:[A-Z][\w\.'’&-]*|of|and|&)\s+){1,6}" + HEADS + r")\b")
GENERIC = set("""
top best leading multi multispeciality multispecialty speciality specialty super superspeciality
network star health government govt general district civil private public sub divisional
referral teaching partner empanelled affiliated associated acquired operates has is at the in a
an our its this other many several nearby cashless major corporate charitable tertiary secondary
primary rural community and of hospital hospitals medical college centre center nursing home
institute sciences mission infirmary care city new eye heart cancer maternity women womens
children childrens child mother dental kidney cardiac neuro ortho orthopaedic multi-speciality
mental psychiatric veterinary ayurvedic ayurveda homeopathic homoeopathic unani state central
railway military army esi esic cghs municipal corporation trust research memorial hi-tech
hitech modern advanced global life lifeline sri shri shree st saint holy family people peoples
also offers provides performs listed located near reputed renowned premier famous well known
leprosy tb chest trauma accident emergency fertility ivf skin cosmetic plastic surgical
surgery diagnostic diagnostics clinic clinics day daycare one stop first aid unit units
apex tertiary-care partnered collaborated tie-up tie tied ties with from to for by as
gynecology gynaecology obstetrics ent physician critical ayush homoeopathy homeopathy hours
on-site onsite site started founded established part three two four five related public
utilities certified coronavirus covid treatment more nearby near
""".split())
# sentences that name another institution for a legitimate reason: staff education or
# employment, teaching affiliation, ownership history, partnerships, landmarks
AFFILIATION_RX = re.compile(
    r"\b(MBBS|MD|MS|MDS|BDS|BHMS|BAMS|DNB|DM|MCh|FRCS|MRCP|degree|fellowship|holds|trained|"
    r"training|graduat\w*|alumn\w*|formerly|former|previously|consultant|professor|head of|"
    r"worked|works at|working|served as|affiliat\w*|teaching hospital|attached|annex\w*|"
    r"acquir\w*|merged|partner\w*|collaborat\w*|tie-?up|associated with|unit of|part of|"
    r"run by|managed by|owned by|sister|branch|near|opposite|behind|next to|beside|landmark|"
    r"km from|referred|refer)\b", re.I)
# a phrase containing any of these is a ranking, listing, insurance or award label, not a name
LISTING_MARKERS = set("""
top best list lists listed network networks accredited accreditation nabh nabl empanelled
empanelment ppn tpa recognition recognised recognized insurance ergo star latlong medindia
medindia's practo justdial lybrate hours first award awarded category directory cashless
approved panel insurer scheme pmjay ayushman cghs echs
""".split())


def institution_mentions(text):
    return [m.group(1).strip() for m in NAME_RX.finditer(text)]


def words(s):
    s = (s or "").lower().replace("'s", "").replace("’s", "")
    return re.findall(r"[a-z]+", s)


def distinctive_tokens(phrase):
    toks = words(phrase)
    if any(t in LISTING_MARKERS for t in toks):
        return []
    return [t for t in toks if len(t) >= 3 and t not in GENERIC]


def is_foreign(phrase, own_name, own_place_keys):
    """True when the institution phrase names a facility other than the record itself.
    Own-place words (city, district) do not count as distinctive: 'Barpeta Civil Hospital' in
    a Barpeta record is treated as local, not foreign."""
    own = words(own_name)
    dt = [t for t in distinctive_tokens(phrase) if t not in own_place_keys]
    if not dt:
        return False
    if fuzz.partial_ratio("".join(dt), "".join(own)) >= 90:  # 'Carespot' vs 'Care Spot'
        return False
    for t in dt:
        if any(fuzz.ratio(t, o) >= 85 for o in own):
            return False
    # acronym of own name, e.g. FAAMCH for Fakhruddin Ali Ahmed Medical College & Hospital
    acro = "".join(o[0] for o in own if o not in ("of", "and", "the"))
    if any(len(t) >= 3 and t in acro for t in dt):
        return False
    return True


if __name__ == "__main__":
    assert url_place("https://www.justdial.com/Kolhapur/Rainbow-x") == ("city", "kolhapur")
    assert url_place("https://www.medindia.net/directories/hospitals/rahat-clinic-jalgaon-"
                     "maharashtra-71969.htm") == ("state", "MAHARASHTRA")
    assert url_place("https://www.practo.com/bangalore/clinic/x") == ("city", "bengaluru")
    m = institution_mentions("Dialysis is offered at S L Raheja Fortis Hospital, Mumbai")
    assert m and is_foreign(m[0], "Wockhardt Hospital Nagpur", {"nagpur"}), m
    m = institution_mentions("Patients were referred to Fakhruddin Ali Ahmed Medical College "
                             "and Hospital (FAAMCH)")
    assert m and not is_foreign(m[0], "Fakhruddin Ali Ahmed Medical College & Hospital",
                                {"barpeta"}), m
    assert not is_foreign("Top Hospitals", "X Clinic", set())
    assert not is_foreign("Sher-i-Kashmir Institute of Medical Sciences",
                          "Sher-I-Kashmir Institute of Medical Sciences", set())
    assert not is_foreign("Carespot Nursing Home", "Care Spot Nursing Home Care", set())
    assert not is_foreign("HDFC ERGO Network Hospital", "Century Hospital", set())
    assert is_foreign("Kamal Hospital", "Kamat Hospital", set())
    print("proxies.py self-check ok")
