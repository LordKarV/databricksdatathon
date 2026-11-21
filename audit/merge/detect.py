"""Sentence-level detectors for merged / contaminated claims.

For every claim sentence (procedure, equipment, capability, description) it extracts
  - facility-name mentions (capitalised phrase containing a facility keyword) and compares
    each with the record's own name: self, sibling (same brand, other branch), generic, foreign
  - place mentions (district / city / state from gazetteer.py) and compares them with the
    record's own location: same, other_district (same state), other_state
and assigns a context class to sentences with a foreign mention: credential, relation, direct.

Output: out/sentences_flagged.parquet (one row per sentence) and out/records_flagged.parquet.
Run: /Users/karthikvattem/projects/datathon/.venv/bin/python detect.py
"""
import os, re
import pandas as pd
from rapidfuzz import fuzz
import common, gazetteer

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

KW = (r"(?:Hospitals?|Medical\s+College|Medical\s+Cent(?:re|er)s?|Medical\s+Institute|Nursing\s+Homes?|"
      r"Clinics?|Poly\s?clinic|Institute|Health\s+Cent(?:re|er)|Healthcare|Health\s+Care|Dispensary|"
      r"Infirmary|Sanatorium|Medicity|AIIMS|PGIMER|JIPMER|Medical\s+University|College\s+of\s+Nursing|Nursing\s+College)")
CAPW = r"(?:[A-Z][A-Za-z0-9.'\-]*|[A-Z]{2,})"
MENTION = re.compile(
    r"((?:" + CAPW + r"\s+(?:(?:of|and|&|for|the|de)\s+)?){0,6}" + KW +
    r"(?:\s+(?:of|for|and|&)\s+(?:" + CAPW + r"\s*){1,5})?)"
    r"(?:\s*,?\s+(" + CAPW + r"(?:\s+" + CAPW + r")?))?")

GENERIC = set("""hospital hospitals clinic clinics polyclinic poly multi speciality specialty specialities
specialties super superspeciality superspecialty multispeciality multispecialty care centre center centres
centers medical college institute institutes research health healthcare the of and for de pvt ltd private
limited nursing home homes general government govt district civil sub divisional primary community maternity
children childrens child eye dental ent heart cancer kidney ortho orthopaedic orthopedic women womens mother
trust charitable foundation sciences science memorial mission new old city main unit branch dr dr. doctor
neuro cardiac surgical surgery day diagnostic diagnostics laboratory lab pathology skin hair ivf fertility
infertility test tube baby rural urban national state referral railway esi esic cghs services service our
this its at in a an all ayurveda ayurvedic homoeopathic homeopathy dispensary infirmary sanatorium medicity
tertiary teaching hi tech hitech advanced cashless network empanelled listed partner affiliated associated
gastroenterology gynecology gynaecology obstetrics obstetric paediatric pediatric pediatrics paediatrics urology
nephrology oncology cardiology neurology dermatology physiotherapy homoeopathy ophthalmic ophthalmology
orthopaedics orthopedics psychiatric psychiatry mental rehabilitation physician physicians surgeon surgeons
gynecologist dentist dentists top best listed corporate accredited nabh nabl insurance among coordinates
located leading famous renowned premier largest biggest well known one first only near from by under with
is as on to it his her their spine joint bone ortho laser vision skin cosmetic plastic trauma emergency
critical accident maternity cardio uro gastro liver lung chest tb tuberculosis leprosy veterinary pet animal
super-speciality multi-speciality multi-specialty super-specialty family wellness medicine medicines clinical
dialysis imaging scan scans radiology physio daycare speciality's specialty's sri shri shree smt st saint
""".split())
STOP = {"of", "and", "the", "for", "de", "&"}
# directory / insurer / listing labels: a mention containing one of these is a label, not a facility
LABEL = re.compile(r"\b(Network|TPA|Empanell?ed|Practo|Justdial|Medindia|Lybrate|HexaHealth|Credihealth|"
                   r"Top|Best|Cashless|Insurance|PMJAY|CGHS|ECHS|Ayushman|Awards?|Consultants|Dept|Department)\b", re.I)
COMMON = set()  # filled in main(): words that are mostly written lowercase in this corpus


def common_words(texts):
    """Tokens written lowercase at least as often as capitalised (excluding sentence-initial)."""
    from collections import Counter
    lo, up = Counter(), Counter()
    for t in texts:
        for w in re.findall(r"[A-Za-z]+", t)[1:]:
            if w.islower():
                lo[w] += 1
            elif w[0].isupper() and not w.isupper():
                up[w.lower()] += 1
    return {w for w, n in lo.items() if n >= 5 and n >= up[w]}

CREDENTIAL = re.compile(  # case-insensitive; doctor training / other workplaces
    r"\b(MBBS|M\.?B\.?B\.?S|MD|M\.D\.|MS|DNB|BDS|MDS|DM|MCh|M\.Ch|FRCS|MRCP|DGO|DCH|DNB|degree|trained|training|"
    r"fellowship|residency|resident|graduated|graduate|alumn\w*|studied|completed|worked|formerly|previously|"
    r"ex-|Ex\b|former|experience|internship|qualified|qualification|post.?graduat\w*|served|consultant at|"
    r"visiting|also (?:consults|practices|practises|available)|practi[cs]es? at|attached to|diploma|"
    r"surgeon at|doctor at|physician at|consultant|dr\.?\s|head of|hod|professor|lecturer)\b", re.I)
ALIAS = re.compile(r"\b(formerly|earlier|previously|originally|also) (known|called|named)\b|\brenamed\b|\bnow (known|called)\b", re.I)
RELATION = re.compile(
    r"\b(refer\w*|affiliat\w*|associat\w*|tie.?up|partner\w*|collaborat\w*|empanel\w*|network|linked|sister|"
    r"unit of|part of|branch of|branches|managed by|run by|owned by|group|chain|subsidiary|acquired|"
    r"recogni[sz]ed by|accredited|attached|teaching hospital|transfer\w*|nearby|near|opposite|next to|"
    r"adjacent|behind|beside|close to|landmark)\b", re.I)


SUBUNIT_CTX = re.compile(r"\b(offer\w*|runs|operates|special|includes|including|dedicated|in-house|within|"
                         r"at the facility|department|unit|wing)\b", re.I)


def toks(s):
    return [t for t in re.split(r"[^a-z0-9]+", s.lower()) if t]


def initials(words):
    return "".join(w[0] for w in words if w and w not in STOP)


def classify_mention(mtext, place, rec, lex):
    """Return (label, distinctive tokens). label in self|sibling|generic|foreign."""
    if LABEL.search(mtext):
        return "generic", []
    mt = toks(mtext)
    dist = [t for t in mt if t not in GENERIC and t not in COMMON and not t.isdigit() and len(t) > 1]
    places_in = [t for t in dist if t in lex]
    brand = [t for t in dist if t not in lex]
    if place:
        pl = gazetteer.norm(place)
        if pl in lex:
            places_in.append(pl)
    if not dist:
        return "generic", dist
    rn = rec["name_toks"]
    rdist = rec["name_dist"]
    # acronym match either way (e.g. GMC vs Government Medical College)
    caps = [w for w in re.findall(r"\b[A-Z]{2,}\b", mtext)]
    ini = initials(rn)
    if any(len(c) >= 2 and (ini.startswith(c.lower()) or c.lower() in (ini, initials(rdist))) for c in caps) or \
       any(c.lower() == t for c in caps for t in rdist):
        brand_match = True
    elif rec["name_caps"] and any(initials(mt).startswith(c) for c in rec["name_caps"] if len(c) >= 3):
        brand_match = True
    else:
        brand_match = any(t in rdist or any(fuzz.ratio(t, r) >= 80 for r in rdist if len(r) > 3 and len(t) > 3 and r[0] == t[0])
                          for t in (brand or dist)) or \
            (bool(rdist) and (brand or dist)[0][0] == rdist[0][0] and fuzz.ratio("".join(brand or dist), "".join(rdist)) >= 88) or \
            (len("".join(brand)) >= 6 and fuzz.partial_ratio("".join(brand), "".join(rn)) >= 90)
    if not brand and places_in and not brand_match:
        # name made only of a place + generic words, e.g. "District Hospital Durg"
        own = rec["own_names"] | rec["own_districts"]
        if any(p in own or lex[p]["districts"] & rec["own_districts"] for p in places_in):
            return "self", dist
        return "foreign", dist
    if brand_match:
        own = rec["own_names"] | rec["own_districts"] | set(rdist)
        far = [p for p in places_in if p not in own and not (lex[p]["districts"] & rec["own_districts"])
               and lex[p]["kind"] != "state"]
        return ("sibling" if far else "self"), dist
    return "foreign", dist


def place_relation(p, rec, lex):
    if p in rec["own_names"] or p in rec["own_districts"]:
        return "same"
    e = lex[p]
    if e["districts"] & rec["own_districts"]:
        return "same"
    if not rec["own_states"]:
        return "unknown"
    if not (e["states"] & rec["own_states"]):
        return "other_state"
    if e["kind"] == "state":
        return "same"
    return "other_district"


def main():
    df = common.load()
    lex, own = gazetteer.build(df)
    prx, _ = gazetteer.place_regex(lex)
    recs = {}
    for r in df.itertuples():
        nt = toks(r.name or "")
        o = own.loc[r.unique_id]
        recs[r.unique_id] = {
            "name_toks": nt,
            "name_dist": [t for t in nt if t not in GENERIC and len(t) > 1],
            "name_caps": {c.lower() for c in re.findall(r"\b[A-Z]{2,}\b", r.name or "")},
            "own_states": o.own_states, "own_districts": o.own_districts,
            "own_names": o.own_names | {t for t in nt if t in lex},
        }
    s = common.sentences(df)
    COMMON.update(common_words(s.text))
    print("common lowercase words", len(COMMON))
    rows = []
    for u, text in zip(s.unique_id, s.text):
        rec = recs[u]
        ments = []
        for m in MENTION.finditer(text):
            lab, dist = classify_mention(m.group(1), m.group(2), rec, lex)
            ments.append((m.group(0).strip(), lab))
        pls = [(p, place_relation(p, rec, lex)) for p in gazetteer.find_places(text, prx)]
        prel = {r for _, r in pls}
        fm = [t for t, l in ments if l == "foreign"]
        # an in-house specialty clinic ("IUI Clinic is offered") is a sub-unit, not another facility
        if fm and all(re.search(r"Clinics?$", t) for t in fm) and SUBUNIT_CTX.search(text) \
                and not ({"other_state", "other_district"} & prel):
            ments = [(t, "subunit" if l == "foreign" else l) for t, l in ments]
        labs = {l for _, l in ments}
        ctx = ""
        if "foreign" in labs or "sibling" in labs:
            ctx = ("alias" if ALIAS.search(text) else "credential" if CREDENTIAL.search(text)
                   else "relation" if RELATION.search(text) else "direct")
        rows.append({
            "foreign_names": "; ".join(t for t, l in ments if l == "foreign"),
            "sibling_names": "; ".join(t for t, l in ments if l == "sibling"),
            "self_names": "; ".join(t for t, l in ments if l == "self"),
            "other_mentions": "; ".join(f"{t} [{l}]" for t, l in ments if l in ("generic", "subunit")),
            "has_foreign": "foreign" in labs, "has_sibling": "sibling" in labs,
            "context": ctx,
            "places_other_state": "; ".join(p for p, r in pls if r == "other_state"),
            "places_other_district": "; ".join(p for p, r in pls if r == "other_district"),
            "has_other_state": "other_state" in prel, "has_other_district": "other_district" in prel,
        })
    out = pd.concat([s.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
    os.makedirs(OUT, exist_ok=True)
    out.to_parquet(os.path.join(OUT, "sentences_flagged.parquet"))
    agg = out.groupby("unique_id").agg(
        n_sent=("text", "size"), n_foreign=("has_foreign", "sum"), n_sibling=("has_sibling", "sum"),
        n_other_state=("has_other_state", "sum"), n_other_district=("has_other_district", "sum"),
        n_foreign_direct=("context", lambda x: (x == "direct").sum()),
    ).reset_index()
    agg = df[["unique_id", "name", "address_city", "address_stateOrRegion", "facilityTypeId"]].merge(agg, on="unique_id", how="left")
    agg.to_parquet(os.path.join(OUT, "records_flagged.parquet"))
    n = len(df)
    print("records", n, "sentences", len(out))
    for col in ["n_foreign", "n_sibling", "n_other_state", "n_other_district", "n_foreign_direct"]:
        print(f"{col}: records>=1 {int((agg[col] > 0).sum())}/{n}; sentences {int(agg[col].sum())}/{len(out)}")
    print(out[out.has_foreign].context.value_counts().to_dict())


if __name__ == "__main__":
    main()
