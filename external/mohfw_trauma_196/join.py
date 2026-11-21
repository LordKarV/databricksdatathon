"""Join the 196 MoHFW trauma care facilities (TCFs) to the Virtue Foundation (VF) table.

Usage: python -I join.py TCF_CSV FACILITIES_PARQUET FACILITY_DISTRICT_PARQUET \
           PIN_PARQUET GRADES_PARQUET OUT_DIR

Matcher, per TCF:
  1. key tokens = TCF name tokens minus generic words (hospital, district, govt...).
  2. candidates = VF rows whose state (audit/geo district table, else raw state) equals
     the TCF state and whose name/city/address/district contains a key token
     (rapidfuzz ratio >= 88 per token).
  3. name score = token_set_ratio of the two names after abbreviation expansion with
     the shared location tokens removed (mean of token_set and token_sort); a VF name with its own distinctive token
     ("Shree Hospital, Satara", "District Hospital Hapur") is capped at EXTRA_CAP, and a
     VF name that is only the place name is dropped. A place hit found only in the
     PIN-derived district (not name/city/address) is also capped at EXTRA_CAP.
  4. accept best candidate with name score >= ACCEPT; 60..ACCEPT goes to a review file.
TCF coordinates are approximated as the median of India Post offices in the same state
whose district or office name equals a key token (good to a district, not a building).
"""
import json
import re
import sys
from math import asin, cos, radians, sin, sqrt

import pandas as pd
from rapidfuzz import fuzz

ACCEPT = 80
REVIEW = 60
TOKEN_HIT = 88
EXTRA_CAP = 70

ABBREV = {
    "govt": "government", "dist": "district", "distt": "district", "dh": "district hospital",
    "hos": "hospital", "hosp": "hospital", "gmch": "government medical college hospital",
    "gmc": "government medical college", "hqr": "headquarters", "hq": "headquarters",
    "sd": "sub divisional", "chc": "community health centre", "inst": "institute",
    "taluq": "taluk", "sdh": "sub district hospital", "mc": "medical college",
}
GENERIC = {
    "hospital", "hospitals", "district", "government", "civil", "general", "medical",
    "college", "and", "of", "the", "taluk", "sub", "divisional", "community", "health",
    "centre", "center", "area", "regional", "zonal", "headquarters", "head", "quarters",
    "institute", "sciences", "science", "memorial", "trauma", "sadar", "combined",
    "municipal", "new", "phc", "division", "dr", "shri", "sir", "pt", "level", "care",
}
STATE_ALIAS = {"orissa": "odisha", "tamilnadu": "tamil nadu", "jammu and kashmir": "jammu and kashmir",
               "the dadra and nagar haveli and daman and diu": "dadra and nagar haveli",
               "andaman and nicobar islands": "andaman and nicobar islands"}
TRAUMA_RE = re.compile(r"\btrauma|polytrauma|casualty|accident|emergency", re.I)


def norm(s):
    s = re.sub(r"[^a-z0-9 ]", " ", str(s).lower().replace("&", " and "))
    return " ".join(ABBREV.get(w, w) for w in s.split())


def norm_state(s):
    s = norm(s)
    return STATE_ALIAS.get(s, s)


def key_tokens(name):
    return [w for w in norm(name).split() if w not in GENERIC and len(w) >= 3]


def hav_km(a, b, c, d):
    a, b, c, d = map(radians, (a, b, c, d))
    h = sin((c - a) / 2) ** 2 + cos(a) * cos(c) * sin((d - b) / 2) ** 2
    return 2 * 6371 * asin(sqrt(h))


def tok_hit(tok, words):
    return any(fuzz.ratio(tok, w) >= TOKEN_HIT for w in words)


def load_vf(fac_path, dist_path):
    f = pd.read_parquet(fac_path)
    f = f[f.name.notna() & (f.name.str.strip() != "")]
    d = pd.read_parquet(dist_path)[["unique_id", "district", "dstate"]]
    f = f.merge(d, on="unique_id", how="left")
    f["state_n"] = f.dstate.fillna(f.address_stateOrRegion).map(norm_state)
    loc = f[["address_city", "address_line1", "address_line2", "address_line3"]]
    f["loc_words"] = (f.name.fillna("") + " " + loc.fillna("").astype(str).agg(" ".join, axis=1)).map(
        lambda s: set(norm(s).split()))
    # PIN-derived district is kept apart: it sometimes contradicts the stated city.
    f["dist_words"] = f.district.fillna("").map(lambda s: set(norm(s).split()))
    f["lat"] = pd.to_numeric(f.latitude, errors="coerce")
    f["lon"] = pd.to_numeric(f.longitude, errors="coerce")
    return f


def tcf_coords(t, pins):
    p = pins[pins.state_n == norm_state(t.state)]
    toks = key_tokens(t["name"])
    hit = p[p.district_n.isin(toks) | p.office_n.isin(toks)]
    if hit.empty:
        return None, None, 0
    return hit.lat.median(), hit.lon.median(), len(hit)


def match_one(t, vf):
    toks = key_tokens(t["name"])
    cand = vf[vf.state_n == norm_state(t.state)]
    out = []
    for _, v in cand.iterrows():
        shared = [k for k in toks if tok_hit(k, v.loc_words)]
        by_district_only = not shared
        if by_district_only:
            shared = [k for k in toks if tok_hit(k, v.dist_words)]
        if not shared:
            continue
        drop = lambda s: " ".join(w for w in norm(s).split() if not tok_hit(w, shared))
        a, b = drop(t["name"]), drop(v["name"])
        if not b:  # VF name is only the place name: no evidence it is this facility
            continue
        # Mean of set and sort ratios: set alone ignores "taluk" vs "medical college".
        score = (fuzz.token_set_ratio(a, b) + fuzz.token_sort_ratio(a, b)) / 2 if a else 50.0
        # A VF name carrying its own distinctive token (another town, a private brand,
        # initials like "R.R.") is a different facility unless the TCF name has it too.
        tcf_words = norm(t["name"]).split()
        extra = [w for w in norm(v["name"]).split() if w not in GENERIC and not tok_hit(w, tcf_words)]
        if extra or by_district_only:
            score = min(score, EXTRA_CAP)
        out.append((score, v.unique_id, ";".join(shared)))
    return sorted(out, reverse=True)


def vf_trauma_text(v):
    cols = ["specialties", "procedure", "equipment", "capability", "description"]
    txt = " ".join(str(v[c]) for c in cols if pd.notna(v[c]))
    hits = sorted({m.group(0).lower() for m in TRAUMA_RE.finditer(txt)})
    sent = next((s for c in cols if pd.notna(v[c]) for s in re.split(r'","|\. ', str(v[c]))
                 if TRAUMA_RE.search(s)), "")
    return ",".join(hits), sent.strip('[]"')[:200]


def main(tcf_csv, fac, dist, pin, grades, out_dir):
    tcf = pd.read_csv(tcf_csv)
    vf = load_vf(fac, dist).set_index("unique_id", drop=False)
    pins = pd.read_parquet(pin)
    pins = pins.assign(state_n=pins.statename.map(norm_state), district_n=pins.district.map(norm),
                       office_n=pins.officename.map(lambda s: norm(re.sub(r"\b(S\.?O|B\.?O|H\.?O)\b", "", s))),
                       lat=pd.to_numeric(pins.latitude, errors="coerce"),
                       lon=pd.to_numeric(pins.longitude, errors="coerce"))
    pins = pins[pins.lat.between(6, 38) & pins.lon.between(68, 98)]
    g = pd.read_parquet(grades)
    g = g[g.service == "trauma"].set_index("unique_id").grade

    rows, review = [], []
    for _, t in tcf.iterrows():
        lat, lon, npin = tcf_coords(t, pins)
        cands = match_one(t, vf)
        best = cands[0] if cands else None
        rec = dict(sno=t.sno, state=t.state, tcf_name=t["name"], level=t.level, status=t.brief_status,
                   tcf_lat=lat, tcf_lon=lon, tcf_pin_offices=npin, n_candidates=len(cands))
        if best and best[0] >= REVIEW:
            v = vf.loc[best[1]]
            km = hav_km(lat, lon, v.lat, v.lon) if lat is not None and pd.notna(v.lat) else None
            hits, sent = vf_trauma_text(v)
            rec.update(score=round(best[0]), vf_id=best[1], vf_name=v["name"], vf_city=v.address_city,
                       vf_operator=v.operatorTypeId, shared_tokens=best[2],
                       km_tcf_to_vf=None if km is None else round(km, 1),
                       vf_trauma_grade=g.get(best[1], "none"), vf_trauma_words=hits, vf_trauma_sentence=sent,
                       runner_up=cands[1][0] if len(cands) > 1 else None)
        (rows if best and best[0] >= ACCEPT else review if best and best[0] >= REVIEW else rows).append(rec)
    acc = pd.DataFrame([r for r in rows if r.get("score", 0) >= ACCEPT])
    allr = pd.DataFrame(rows + review)
    allr.to_csv(f"{out_dir}/tcf_vf_candidates.csv", index=False)
    acc.to_csv(f"{out_dir}/tcf_vf_matches.csv", index=False)
    stats = dict(
        tcf_rows=len(tcf), tcf_with_coords=int(allr.tcf_lat.notna().sum()),
        tcf_with_any_candidate=int((allr.n_candidates > 0).sum()),
        accepted=len(acc), review_band=len(review), match_rate=round(len(acc) / len(tcf), 3),
        accepted_by_vf_trauma_grade=acc.vf_trauma_grade.value_counts().to_dict() if len(acc) else {},
        accepted_with_trauma_words=int((acc.vf_trauma_words.fillna("") != "").sum()) if len(acc) else 0,
        accepted_operator=acc.vf_operator.value_counts(dropna=False).to_dict() if len(acc) else {},
        accepted_km_median=float(acc.km_tcf_to_vf.median()) if len(acc) else None,
        accepted_km_over_50=int((acc.km_tcf_to_vf > 50).sum()) if len(acc) else 0,
        vf_public_rows=int((vf.operatorTypeId == "public").sum()),
    )
    json.dump(stats, open(f"{out_dir}/join_stats.json", "w"), indent=1, default=str)
    print(json.dumps(stats, indent=1, default=str))


if __name__ == "__main__":
    main(*sys.argv[1:7])
