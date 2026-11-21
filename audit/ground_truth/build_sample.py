"""Build a stratified 36-pair (facility, service) ground-truth sample for web fact-checking.

Local only: reads the Parquet snapshot, no warehouse queries.
Run: /Users/karthikvattem/projects/datathon/.venv/bin/python build_sample.py
Writes sample.json and sample_stats.json next to this script.
"""
import json
import math
import random
import re
from collections import Counter
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz

SEED = 20261121
RAW = Path("/Users/karthikvattem/projects/datathon/data/raw")
OUT = Path(__file__).resolve().parent
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
FIELDS = ["procedure", "equipment", "capability", "description"]  # citeable sentence fields
STRONG_MAX_KM, SUSPECT_MIN_KM = 25.0, 50.0

# Service mention patterns (sentence level) and specialty enums that count as a mention.
SERVICES = {
    "dialysis": (r"\b(dialysis|ha?emodialysis|CAPD)\b", set()),
    "emergency_csection": (
        r"(\bc-?\s?section|ca?esarean|\bLSCS\b|emergency obstetric|obstetric emergenc|\bE?m?ONC\b|\bCEmONC\b|\bBEmONC\b)",
        set(),
    ),
    "nicu": (r"(\bNICU\b|neonatal intensive|neonatal ICU|newborn intensive|level\s*(II|III|2|3)\s*neonatal)", set()),
    "cardiac_surgery": (
        r"(cardiac surg|cardiothoracic|\bCTVS\b|\bCABG\b|(?<!gastric )bypass surgery|open[- ]heart|valve replacement|heart surgery)",
        {"cardiacSurgery", "cardiothoracicSurgery"},
    ),
    "mri": (r"(\bMRI\b|\bmagnetic resonance)", set()),
    "trauma_emergency": (
        r"(\btrauma\b|emergency (department|room|care|services?|medicine|unit|ward)|casualty|24\s*[x/*]\s*7 emergency|accident and emergency)",
        {"emergencyMedicine"},
    ),
}
# Clinical prerequisites that should co-occur with a real service (anywhere in the record).
PREREQS = {
    "dialysis": (r"(nephrolog|\bICU\b|intensive care|RO (water|plant))", {"nephrology", "pediatricNephrology"}),
    "emergency_csection": (
        r"(operation theat|\bOT\b|ana?esthe|blood bank|labou?r room|labou?r ward)",
        {"anesthesia", "anesthesiology"},
    ),
    "nicu": (
        r"(neonatolog|incubator|radiant warmer|phototherapy|ventilator|CPAP|paediatric|pediatric)",
        {"neonatologyPerinatalMedicine", "pediatrics", "pediatricCriticalCareMedicine"},
    ),
    "cardiac_surgery": (
        r"(cath(eterization)? lab|heart[- ]lung|perfusion|\bCCU\b|\bICCU\b|cardiac (ICU|intensive)|cardiac ana?esthe)",
        {"cardiology", "interventionalCardiology"},
    ),
    "mri": (r"(radiolog|\d(\.\d)?\s?(T|Tesla)\b|CT scan|\bCT\b)", {"radiology", "diagnosticRadiology"}),
    "trauma_emergency": (
        r"(\bICU\b|intensive care|blood bank|ambulance|neurosurg|orthopa?ed|\bCT\b)",
        {"criticalCareMedicine", "neurosurgery", "orthopedicSurgery"},
    ),
}
# Flagship chains / very well known institutions, excluded because they are too easy to verify.
FLAGSHIP = re.compile(
    r"\b(AIIMS|All India Institute|Apollo|Fortis|Max (Super|Hospital|Healthcare)|Manipal|Medanta|Narayana|"
    r"Kokilaben|Tata Memorial|Christian Medical College|CMC|PGIMER|Ruby Hall|Lilavati|Hinduja|Jaslok|Aster|"
    r"Sir Ganga Ram|Breach Candy|Amrita|NIMHANS|Gleneagles|Global Hospital|Yashoda|Columbia Asia|Sakra|Kauvery|"
    r"MIOT|Moolchand|BLK|Artemis|Paras|Jupiter|Nanavati|Bombay Hospital|Care Hospitals?|KIMS|Krishna Institute of Medical|Rainbow|Cloudnine|"
    r"Motherhood|Wockhardt|Sahyadri|Ramaiah|Sankara Nethralaya|Aravind|Safdarjung|JIPMER|SGPGI|Hiranandani|"
    r"Indraprastha|Medica|Rela|Sparsh|Ganga Medical|Dr\.? Mohan|Vasan|Lotus|Star Hospital)\b",
    re.I,
)
GENERIC_NAME = re.compile(
    r"^(city|civil|general|government|govt\.?|district|community health|primary health|sub[- ]?district|"
    r"multi ?speciality|super ?speciality|life ?care|care|new|sai|shree|shri|sri)\s*(hospital|clinic|centre|center)?$",
    re.I,
)
# Proper-noun facility names inside a claim sentence, e.g. "S L Raheja Fortis Hospital".
FAC_NAME = re.compile(
    r"((?:[A-Z][A-Za-z.&'-]+\s+){1,6}(?:Hospital|Hospitals|Medical College|Institute|Nursing Home|Clinic|"
    r"Medical Centre|Medical Center|Healthcare|Health Care))"
)
NAME_STOP = {"the", "hospital", "hospitals", "clinic", "and", "of", "medical", "centre", "center", "institute",
             "care", "health", "healthcare", "nursing", "home", "college", "research", "super", "speciality",
             "specialty", "multi", "multispeciality", "pvt", "ltd", "dr", "dr.", "sri", "shri", "shree",
             # generic department words: "Fertility Clinic" names a unit, not another facility
             "fertility", "eye", "dental", "children", "maternity", "cancer", "heart", "kidney", "general",
             "government", "govt", "district", "civil", "ivf", "women", "diagnostic", "superspeciality",
             "multispecialty", "private", "public", "rural", "urban", "city", "new", "best", "top", "our",
             "emergency", "menopausal", "menopause", "diabetes", "diabetic", "ortho", "orthopaedic", "orthopedic",
             "skin", "ent", "laser", "physiotherapy", "wellness", "trauma", "cardiac", "neuro", "spine", "liver",
             "mother", "child", "baby", "dialysis", "cardiology", "oncology", "pain", "sleep", "speciality",
             "outpatient", "day", "surgery", "bedded", "adolescent", "breast", "headquarters", "first", "premier", "leading", "largest", "only", "teaching", "preventive", "charitable", "infertility", "mission", "high", "risk", "well", "baby", "antenatal", "surgical", "dermatology", "pediatric", "paediatric", "psychiatric"}
NEGATION = re.compile(r"\b(no|not|without|lacks?|unavailable|absence of|referred (externally|out|outside|elsewhere)|upcoming|under construction|proposed|planned)\b", re.I)


def is_null(v):
    return v is None or (isinstance(v, float) and math.isnan(v)) or str(v).strip().lower() in ("", "null", "[]", '[""]', "[null]")


def as_list(v):
    if is_null(v):
        return []
    try:
        x = json.loads(v)
    except (json.JSONDecodeError, TypeError):
        return [str(v)]
    if isinstance(x, list):
        return [str(i).strip() for i in x if i is not None and str(i).strip()]
    return [str(x)]


def haversine_km(a, b, c, d):
    r = math.radians
    h = math.sin(r(c - a) / 2) ** 2 + math.cos(r(a)) * math.cos(r(c)) * math.sin(r(d - b) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


CANON = {"andamanandnicobarislands", "andhrapradesh", "arunachalpradesh", "assam", "bihar", "chandigarh",
         "chhattisgarh", "delhi", "goa", "gujarat", "haryana", "himachalpradesh", "jammuandkashmir", "jharkhand",
         "karnataka", "kerala", "ladakh", "lakshadweep", "madhyapradesh", "maharashtra", "manipur", "meghalaya",
         "mizoram", "nagaland", "odisha", "puducherry", "punjab", "rajasthan", "sikkim", "tamilnadu", "telangana",
         "thedadraandnagarhavelianddamananddiu", "tripura", "uttarpradesh", "uttarakhand", "westbengal"}
STATE_ALIAS = {"orissa": "odisha", "pondicherry": "puducherry", "nctofdelhi": "delhi", "newdelhi": "delhi",
               "nctdelhi": "delhi", "westdelhi": "delhi", "eastdelhi": "delhi", "uttaranchal": "uttarakhand",
               "uttranchal": "uttarakhand", "uk": "uttarakhand", "jammukashmir": "jammuandkashmir",
               "jk": "jammuandkashmir", "up": "uttarpradesh", "uttarpradesh": "uttarpradesh", "mp": "madhyapradesh",
               "ts": "telangana", "gj": "gujarat", "mh": "maharashtra", "ms": "maharashtra",
               "chattisgarh": "chhattisgarh", "punjabregion": "punjab", "chandigarhut": "chandigarh",
               "dadraandnagarhaveli": "thedadraandnagarhavelianddamananddiu",
               "damananddiu": "thedadraandnagarhavelianddamananddiu",
               "dadraandnagarhavelianddamananddiu": "thedadraandnagarhavelianddamananddiu"}


def norm_state(s):
    """Canonical state key, or None when the field holds a city/district or several states."""
    if s is None or str(s).strip().upper() in ("", "NA", "NULL"):
        return None
    k = re.sub(r"[^a-z]", "", str(s).lower())
    k = STATE_ALIAS.get(k, k)
    if k in CANON:
        return k
    # "Ghaziabad, Uttar Pradesh" style: take the last comma part if it is a state.
    last = STATE_ALIAS.get(re.sub(r"[^a-z]", "", str(s).split(",")[-1].lower()), None)
    tail = re.sub(r"[^a-z]", "", str(s).split(",")[-1].lower())
    return last if last in CANON else (tail if tail in CANON and ";" not in str(s) else None)


def pin_table():
    p = pd.read_parquet(RAW / "india_post_pincode_directory.parquet")
    p["lat"] = pd.to_numeric(p["latitude"], errors="coerce")
    p["lon"] = pd.to_numeric(p["longitude"], errors="coerce")
    # Directory has some swapped / out-of-India coordinates; keep only points inside India's bounding box.
    ok = p["lat"].between(6, 38) & p["lon"].between(68, 98)
    cent = p[ok].groupby("pincode")[["lat", "lon"]].median()
    places = p.groupby("pincode").apply(
        lambda g: " | ".join(sorted(set(g["district"].astype(str)) | set(g["officename"].astype(str)))).lower())
    st = p.groupby("pincode")["statename"].agg(lambda s: Counter(s).most_common(1)[0][0])
    return cent, st, places


def own_tokens(name):
    return {t for t in re.findall(r"[a-z]+", name.lower()) if t not in NAME_STOP and len(t) > 2}


NAME_VOCAB = set()  # filled in main(): distinctive tokens used in any facility name in the dataset


def foreign_names(sentences, name, city):
    """Facility names in claim sentences that share no distinctive token with the record's own name.

    ponytail: regex + stoplist heuristic. To cut phrases like "Bedded Centrally Air Conditioned Hospital",
    every distinctive token must also occur in some facility name in the dataset. Misses real names whose
    words never appear in the dataset; upgrade path is a gazetteer of Indian facility names.
    """
    mine, out = own_tokens(name), []
    # Split on sentence ends so "...in Mumbai. The Hospital" is not read as one name.
    for s in (part for sent in sentences for part in re.split(r"(?<=[a-z]{2})\.\s+", sent)):
        for m in FAC_NAME.findall(s):
            m = m.strip()
            toks = own_tokens(m)
            initials = "".join(t[0] for t in re.findall(r"[a-z]+", m.lower()) if t in toks).upper()
            abbreviated = len(initials) >= 2 and initials in name.upper().split()  # "SCB" for Srirama Chandra Bhanja
            name_initials = "".join(w[0] for w in re.findall(r"[A-Za-z]+", name) if w.lower() not in ("of", "and", "the"))
            abbreviated = abbreviated or any(len(t) >= 3 and t.upper() in name_initials.upper() for t in toks)  # GAIMS
            if not toks or not toks <= NAME_VOCAB or toks & mine or abbreviated or fuzz.token_set_ratio(m.lower(), name.lower()) >= 80:
                continue
            if city and toks <= own_tokens(city) | {"government", "govt", "district", "general", "civil"}:
                continue
            out.append(m)
    return sorted(set(out))


def city_matches(city, places):
    """True if the stated city resembles the PIN's district or any post office name, None if unknown."""
    if is_null(city) or places is None:
        return None
    return fuzz.partial_ratio(str(city).lower(), places) >= 85


def analyse(row, svc, cent, pin_state, pin_places):
    pat, spec_mention = SERVICES[svc]
    ppat, spec_prereq = PREREQS[svc]
    rx, prx = re.compile(pat, re.I), re.compile(ppat, re.I)
    specs = set(as_list(row["specialties"]))
    claims, fields_hit = [], set()
    for f in FIELDS:
        items = as_list(row[f]) if f != "description" else ([] if is_null(row[f]) else [str(row[f])])
        for s in items:
            dup = any(c["field"] == f and c["text"].lower() == s.lower() for c in claims)
            if rx.search(s) and not NEGATION.search(s) and not dup:  # "Does not have ... heart surgery"
                claims.append({"field": f, "text": s})
                fields_hit.add(f)
    for sp in sorted(specs & spec_mention):
        claims.append({"field": "specialties", "text": sp})
        fields_hit.add("specialties")
    if not claims:
        return None
    all_text = " ".join(" ".join(as_list(row[f])) for f in FIELDS[:3]) + " " + str(row["description"] or "")
    # Prerequisite must be a different statement than the mention itself, so strip mention sentences.
    claim_texts = {c["text"] for c in claims}
    other_text = " ".join(
        s for f in FIELDS[:3] for s in as_list(row[f]) if s not in claim_texts
    ) + ("" if str(row["description"]) in claim_texts else " " + str(row["description"] or ""))
    prereq_hits = sorted({m.group(0) for m in prx.finditer(other_text)}) + sorted(specs & spec_prereq)

    pin = re.sub(r"\s", "", str(row["address_zipOrPostcode"] or "")).strip('"')
    pin_int = int(pin) if re.fullmatch(r"\d{6}", pin) else None
    dist = None
    if pin_int in cent.index and not pd.isna(row["latitude"]):
        c = cent.loc[pin_int]
        dist = haversine_km(row["latitude"], row["longitude"], c["lat"], c["lon"])
    pstate = pin_state.get(pin_int)
    stated_key, pin_key = norm_state(row["address_stateOrRegion"]), norm_state(pstate)
    state_match = None if stated_key is None or pin_key is None else stated_key == pin_key
    city_ok = city_matches(row["address_city"], pin_places.get(pin_int))
    foreign = foreign_names([c["text"] for c in claims if c["field"] != "specialties"], row["name"], row["address_city"])
    return dict(claims=claims, n_fields=len(fields_hit), n_claims=len(claims), prereq=prereq_hits, pin=pin,
                dist_km=None if dist is None else round(dist, 1), pin_state=pstate, state_match=state_match, city_ok=city_ok,
                foreign=foreign, all_text_len=len(all_text))


def stratum(a):
    geo_ok = (a["dist_km"] is not None and a["dist_km"] <= STRONG_MAX_KM and a["state_match"] is True
              and a["city_ok"] is not False)
    if a["foreign"] or (a["dist_km"] is not None and a["dist_km"] > SUSPECT_MIN_KM) or a["state_match"] is False:
        return "suspect"
    if geo_ok and a["n_fields"] >= 2 and a["prereq"]:
        return "strong"
    if geo_ok and a["n_claims"] == 1 and not a["prereq"]:
        return "weak"
    return None


def signals(a):
    parts = [f"fields={a['n_fields']}", f"mentions={a['n_claims']}",
             f"prereq={'|'.join(a['prereq'][:4]) or 'none'}",
             f"pin_centroid_km={a['dist_km']}", f"pin_state={a['pin_state']}", f"state_match={a['state_match']}", f"city_matches_pin={a['city_ok']}"]
    if a["foreign"]:
        parts.append("other_facility_named=" + "|".join(a["foreign"][:3]))
    return "; ".join(parts)


def self_check():
    assert norm_state("U.p.") == "uttarpradesh" and norm_state("Ghaziabad, Uttar Pradesh") == "uttarpradesh"
    assert norm_state("Thane") is None and norm_state("Orissa") == "odisha"
    assert abs(haversine_km(28.61, 77.21, 19.08, 72.88) - 1150) < 20  # Delhi to Mumbai
    assert re.search(SERVICES["emergency_csection"][0], "economic sections", re.I) is None
    assert NEGATION.search("Does not have departments for heart surgery")
    assert re.search(SERVICES["mri"][0], "Electromagnetic Resonance Therapy", re.I) is None


def spread_quotes(claims, k=4):
    """Up to k quotes, round-robin across fields so every field that carries the claim is shown."""
    by_field = {}
    for c in claims:
        by_field.setdefault(c["field"], []).append({"field": c["field"], "text": c["text"][:500]})
    out = []
    while len(out) < k and any(by_field.values()):
        for f in list(by_field):
            if by_field[f] and len(out) < k:
                out.append(by_field[f].pop(0))
    return out


def main():
    self_check()
    df = pd.read_parquet(RAW / "facilities.parquet")
    df = df[df["unique_id"].fillna("").str.match(UUID_RE) & (df["source"] == "kie")].copy()
    n_clean = len(df)
    name_counts = Counter(df["name"].str.lower().str.strip())
    distinct = df[
        df["name"].map(lambda n: name_counts[n.lower().strip()] == 1)
        & ~df["name"].map(lambda n: bool(FLAGSHIP.search(n)))
        & ~df["name"].str.strip().str.match(GENERIC_NAME)
        & (df["name"].str.split().str.len() >= 2)
    ]
    for n in df["name"]:
        NAME_VOCAB.update(own_tokens(n))
    cent, pin_state, pin_places = pin_table()
    pin_state, pin_places = pin_state.to_dict(), pin_places.to_dict()

    pools, stats = {}, {"clean_rows": n_clean, "distinctive_rows": len(distinct), "pools": {}}
    for svc in SERVICES:
        for _, row in distinct.iterrows():
            a = analyse(row, svc, cent, pin_state, pin_places)
            if a is None:
                continue
            s = stratum(a)
            if s:
                pools.setdefault((svc, s), []).append((row, a))
        for s in ("strong", "weak", "suspect"):
            stats["pools"][f"{svc}_{s}"] = len(pools.get((svc, s), []))

    rng = random.Random(SEED)
    used_ids, state_count, pairs = set(), Counter(), []
    for svc in SERVICES:
        for s in ("strong", "weak", "suspect"):
            pool = list(pools.get((svc, s), []))
            rng.shuffle(pool)
            picked = 0
            while picked < 2 and pool:
                # Least-used state first keeps the sample spread; shuffle order breaks ties.
                want_foreign = s == "suspect" and picked == 0
                pool.sort(key=lambda ra: (s == "suspect" and bool(ra[1]["foreign"]) != want_foreign,
                                          state_count[norm_state(ra[0]["address_stateOrRegion"]) or "unparsed"]))
                row, a = pool.pop(0)
                if row["unique_id"] in used_ids:
                    continue
                used_ids.add(row["unique_id"])
                state_count[norm_state(row["address_stateOrRegion"]) or "unparsed"] += 1
                picked += 1
                pairs.append({
                    "pair_id": f"{svc}_{s}_{picked}", "unique_id": row["unique_id"], "name": row["name"],
                    "city": row["address_city"], "state": row["address_stateOrRegion"], "pin": a["pin"],
                    "service": svc, "stratum": s,
                    "claim_quotes": spread_quotes(a["claims"]),
                    "website": None if is_null(row["officialWebsite"]) else row["officialWebsite"],
                    "source_urls": list(dict.fromkeys(as_list(row["source_urls"])))[:3], "signals": signals(a),
                })
    stats["pairs"] = len(pairs)
    stats["states_note"] = "state keys from norm_state(address_stateOrRegion); 'unparsed' = city or district in the state field"
    stats["states"] = len(state_count)
    stats["state_counts"] = dict(state_count.most_common())
    (OUT / "sample.json").write_text(json.dumps(pairs, indent=2, ensure_ascii=True))
    (OUT / "sample_stats.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
