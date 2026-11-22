"""Build step: planner inputs from model v2 (derived/v2), so the app can plan without pandas.

Writes planner/out/planner_v2.json.gz (git-ignored: it holds facility data):
  facilities    id, name, lat, lon, town, district, state, flags. Only facilities v2 scores, so the 12
                exclude_review records are gone (common/eligibility.py, applied by the v2 export), and no
                dental or eye clinic (validation H2, #86: none of the pathways is theirs to serve).
  capabilities  per capability tag: facility indexes, p, band and up to 3 evidence claim ids
  pins          PIN centroids with their state (hill-road travel constants are chosen by state)

Probabilities
- A tag with a v2_service in kb/pathways/capabilities.json: the v2 p of that (facility, service).
  Only LIKELY (band L) and CALL_FIRST (band C) pairs carry a p. NO_SERVICE_TEXT and UNLIKELY pairs
  are never a stop (store.py gives them p 0); the NO_SERVICE_TEXT facility indexes are listed under
  "n", so a route can name the nearer facility a phone "yes" would bring in.
- A tag without one (the support tags v2 does not score: operating theatre, ECG, laboratory, ...):
  the record's own offer sentences that name it (evidence_words). One sentence TEXT_ONE_P, two or more
  TEXT_TWO_P (band T); none NO_MENTION_P. These three numbers are assumptions, not fitted.
Evidence (both kinds) is only the record's own offer sentences: not another facility's, not a non-offer,
plan, camp, staff or list sentence (validation H3), and not a sentence that names a doctor (#86).

Run: uv run --no-project --with pandas --with pyarrow python planner/export_v2.py   (about 15 s)
"""
import gzip
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "app")]

import pandas as pd  # noqa: E402

from facts.redact import redact_names  # noqa: E402

# DATATHON_ROOT moves the data root (where derived/ lives); PLANNER_OUT the output folder
DATA_ROOT = Path(os.environ.get("DATATHON_ROOT") or ROOT)
V1, V2 = DATA_ROOT / "derived" / "v1", DATA_ROOT / "derived" / "v2"
CAPS = ROOT / "kb" / "pathways" / "capabilities.json"
OUT = Path(os.environ.get("PLANNER_OUT") or Path(__file__).resolve().parent / "out") / "planner_v2.json.gz"

OFFERED = {"LIKELY": "L", "CALL_FIRST": "C"}
TEXT_ONE_P, TEXT_TWO_P, NO_MENTION_P = 0.7, 0.78, 0.02  # assumptions: a text mention of a support tag
MAX_EVIDENCE = 3
EVIDENCE_ROLES = ("offer", "unit_or_equipment", "quantity")  # claim_atoms roles that state the record's own offer
# Plans, camps and outreach are not an offer (H3): "plans to launch a blood bank", "free eye camp".
NOT_AN_OFFER = re.compile(r"\b(?:plans?|planning|planned|propos\w*|upcoming|soon|future|will be|to be (?:started|set up|"
                          r"launched|introduced)|under construction|camps?|outreach)\b", re.I)
DENTAL = re.compile(r"dental|dentist|orthodont|\bteeth\b", re.I)
EYE = re.compile(r"\beye\b|netra|nethra|ophthalm|\bvision\b|lasik|retina", re.I)
# a name with one of these is a general or multi-specialty hospital even when it says dental or eye
GENERAL = re.compile(r"heart|cardi|multi|general|trauma|ortho(?!dont)|maternity|child|super ?speciality|medical college"
                     r"|district|sadar|civil|government|govt", re.I)


def specialty_only(name, type_id):
    """True for a dental or eye clinic: no pathway stage (trauma, C-section, STEMI, burns, newborn,
    snakebite, dialysis) is theirs to serve, whatever its text says (H2; eye hospital as cath lab, #86)."""
    n = name or ""
    return (type_id == "dentist" or bool(DENTAL.search(n)) or bool(EYE.search(n))) and not GENERAL.search(n)


def _pattern(words):
    """Case-insensitive whole-word match; short all-caps tokens (ICU, OT, CT) stay case-sensitive."""
    strict = [w for w in words if w.isupper() and len(w) <= 5]
    loose = [w for w in words if w not in strict]
    parts = []
    if loose:
        parts.append(r"(?i:\b(?:" + "|".join(re.escape(w) for w in loose) + r")\b)")
    if strict:
        parts.append(r"\b(?:" + "|".join(re.escape(w) for w in strict) + r")\b")
    return re.compile("|".join(parts))


def _str(x):
    return x if isinstance(x, str) and x.strip() else None


def facilities(scored):
    f = pd.read_parquet(V1 / "facility_location.parquet",
                        columns=["unique_id", "name", "address_city", "district", "state_final", "loc_lat", "loc_lon", "loc_conf"])
    a = pd.read_parquet(V2 / "facility_attributes.parquet", columns=["unique_id", "facilityTypeId"])
    f = f.dropna(subset=["loc_lat", "loc_lon"]).merge(a, on="unique_id", how="left")
    f = f[f.unique_id.isin(scored)]
    spec = [specialty_only(n, t) for n, t in zip(f.name, f.facilityTypeId)]
    print(f"facilities: {len(f)} scored by v2, {sum(spec)} dental or eye clinics left out")
    f = f[[not s for s in spec]]
    return [{"id": r.unique_id, "name": r.name, "lat": round(float(r.loc_lat), 5), "lon": round(float(r.loc_lon), 5),
             "town": _str(r.address_city), "district": _str(r.district), "state": _str(r.state_final),
             "flags": [] if r.loc_conf == "high" else [f"location confidence is {r.loc_conf}: confirm the address by phone"]}
            for r in f.itertuples(index=False)]


def good_claims():
    """(own offer sentence ids, {(claim id, v2 service)} whose atom states an offer)."""
    c = pd.read_parquet(V1 / "claims.parquet", columns=["claim_id", "unique_id", "text", "attribution", "nonoffer"])
    c = c[(c.attribution != "other_facility") & ~c.nonoffer.fillna(False).astype(bool)]
    c = c[~c.text.fillna("").str.contains(NOT_AN_OFFER)]
    c = c[[redact_names(t) == t for t in c.text.fillna("")]]
    at = pd.read_parquet(V2 / "claim_atoms.parquet",
                         columns=["claim_id", "service", "role", "counts_as_own", "quarantine", "nonoffer_cue"])
    ok = at[at.role.isin(EVIDENCE_ROLES) & at.counts_as_own & ~at.quarantine & (at.nonoffer_cue.fillna("") == "")]
    return c, set(zip(ok.claim_id, ok.service))


def v2_rows(service, idx, own, atom_ok):
    s = pd.read_parquet(V2 / "facility_service_scores.parquet", columns=["unique_id", "band", "p", "contributions"],
                        filters=[("service_id", "==", service)])
    s = s[s.unique_id.isin(idx)]
    silent = sorted(idx[u] for u in s.unique_id[s.band == "NO_SERVICE_TEXT"])
    s = s[s.band.isin(OFFERED)]
    rows = []
    for u, b, p, contrib in zip(s.unique_id, s.band, s.p, s.contributions):
        ev = []
        for t in json.loads(contrib or "[]"):
            if t["family"] == "T":
                ev += [e for e in t["evidence_ids"] if e in own and (e, service) in atom_ok and e not in ev]
        rows.append((idx[u], round(float(p), 4), OFFERED[b], ev[:MAX_EVIDENCE]))
    return rows, silent


def text_rows(cap, idx, claims):  # -> (rows, []): a text tag has no NO_SERVICE_TEXT list
    hit = claims[claims.text.str.contains(_pattern(cap["evidence_words"]), na=False) & claims.unique_id.isin(idx)]
    out = []
    for u, g in hit.groupby("unique_id"):
        texts = g.drop_duplicates("text")  # echoed copies of one sentence count once
        out.append((idx[u], TEXT_ONE_P if len(texts) == 1 else TEXT_TWO_P, "T", list(texts.claim_id)[:MAX_EVIDENCE]))
    return out, []


def pins():
    g = pd.read_parquet(V1 / "pin_gazetteer.parquet", columns=["state", "lat", "lon"]).dropna()
    states = sorted(g.state.unique())
    code = {s: i for i, s in enumerate(states)}
    return {"states": states, "lat": [round(float(x), 3) for x in g.lat], "lon": [round(float(x), 3) for x in g.lon],
            "s": [code[s] for s in g.state]}


def main():
    caps = json.loads(CAPS.read_text())["capabilities"]
    scored = set(pd.read_parquet(V2 / "facility_service_scores.parquet", columns=["unique_id"]).unique_id)
    fac = facilities(scored)
    idx = {f["id"]: i for i, f in enumerate(fac)}
    claims, atom_ok = good_claims()
    own = set(claims.claim_id)
    out = {}
    for cap in caps:
        rows, silent = v2_rows(cap["v2_service"], idx, own, atom_ok) if cap["v2_service"] else text_rows(cap, idx, claims)
        rows = sorted(rows)
        out[cap["id"]] = {"source": f"derived/v2 {cap['v2_service']}" if cap["v2_service"] else "own offer sentences",
                          "i": [r[0] for r in rows], "p": [r[1] for r in rows], "b": [r[2] for r in rows],
                          "e": [r[3] for r in rows], "n": silent}
    card = json.loads((V2 / "model_card.json").read_text())
    doc = {"version": 2, "built_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "probabilities": {"source": "derived/v2 facility_service_scores (model v2)",
                             "model_version": card.get("model_version"),
                             "offered_bands": sorted(OFFERED), "not_offered": "NO_SERVICE_TEXT and UNLIKELY pairs (p 0)",
                             "text_tags": {"one_sentence_p": TEXT_ONE_P, "two_or_more_p": TEXT_TWO_P,
                                           "no_mention_p": NO_MENTION_P, "note": "assumptions, for tags v2 does not score"}},
           "no_mention_p": NO_MENTION_P,
           "facilities": {k: [f[k] for f in fac] for k in ("id", "name", "lat", "lon", "town", "district", "state", "flags")},
           "capabilities": out, "pins": pins()}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as fh:
        json.dump(doc, fh, separators=(",", ":"), allow_nan=False)
    print(f"wrote {OUT}: {len(fac)} facilities, {len(out)} capabilities, {OUT.stat().st_size / 1024:.0f} KB")
    for cap, c in out.items():
        print(f"  {cap:26s} {len(c['i']):5d} facilities  {c['source']}")


if __name__ == "__main__":
    main()
