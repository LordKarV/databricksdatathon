"""Stub inputs for the planner from derived/v1, until the model (#11) publishes scores.

    store = V1Store()
    store.facilities()                       -> list of facility dicts for planner.plan
    store.capability_p(facility_id, cap)     -> (p, evidence_ids)

capability_p is the swap point: replace it with a function backed by
derived/v2/facility_service_scores.parquet and the planner does not change.

How the stub probability is made (this is a placeholder, not a fitted model):
- A capability that maps to a graded service (kb_status existing in capabilities.json): the
  service_claim score for that facility and service from data_point_scores.parquet; evidence ids
  are the claim ids cited by grades.parquet.
- A proposed capability: sentences of the facility's own record (not attributed to another
  facility, not a non-offer sentence) that contain one of the tag's evidence words.
    one matching sentence   -> the median service_claim score of 'weak' graded services
    two or more             -> the median service_claim score of 'moderate' graded services
  The two medians are read from the data at load, not hard-coded. Borrowing them assumes a keyword
  mention of a proposed tag is about as reliable as a weak or moderate graded claim; that has not
  been tested.
- No evidence at all: NO_MENTION_P.

Needs pandas and pyarrow. The planner core does not.
"""
import json
import os
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
# DATATHON_ROOT moves the data root (for example a Databricks Volume holding derived/v1); code stays in ROOT
DATA_ROOT = Path(os.environ.get("DATATHON_ROOT") or ROOT)
V1 = DATA_ROOT / "derived" / "v1"
CAPS = ROOT / "kb" / "pathways" / "capabilities.json"
NO_MENTION_P = 0.02   # assumption: chance a capability exists when the record never mentions it
MAX_EVIDENCE = 3


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


class V1Store:
    def __init__(self, v1=V1, caps_path=CAPS):
        self.v1 = Path(v1)
        self.caps = {c["id"]: c for c in json.loads(Path(caps_path).read_text())["capabilities"]}
        sc = pd.read_parquet(self.v1 / "data_point_scores.parquet", columns=["dp_type", "unique_id", "service", "score", "grade"],
                             filters=[("dp_type", "==", "service_claim")])
        self._svc = {(u, s): float(p) for u, s, p in zip(sc.unique_id, sc.service, sc.score)}
        self.p_one_sentence = float(sc[sc.grade == "weak"].score.median())
        self.p_two_sentences = float(sc[sc.grade == "moderate"].score.median())
        g = pd.read_parquet(self.v1 / "grades.parquet", columns=["unique_id", "service", "cite_evidence"])
        self._cite = {}
        for u, s, c in zip(g.unique_id, g.service, g.cite_evidence):
            try:
                self._cite[(u, s)] = [x["claim_id"] for x in json.loads(c or "[]")][:MAX_EVIDENCE]
            except (ValueError, TypeError, KeyError):
                self._cite[(u, s)] = []
        self._claims = None
        self._matches = {}

    def facilities(self):
        f = pd.read_parquet(self.v1 / "facility_location.parquet",
                            columns=["unique_id", "name", "address_city", "district", "state_final", "loc_lat", "loc_lon", "loc_conf"])
        f = f.dropna(subset=["loc_lat", "loc_lon"])
        out = []
        for r in f.itertuples(index=False):
            flags = [] if r.loc_conf == "high" else [f"location confidence is {r.loc_conf}: confirm the address by phone"]
            out.append({"id": r.unique_id, "name": r.name, "lat": float(r.loc_lat), "lon": float(r.loc_lon),
                        "town": r.address_city, "district": r.district, "state": r.state_final, "flags": flags})
        return out

    def _load_claims(self):
        if self._claims is None:
            c = pd.read_parquet(self.v1 / "claims.parquet", columns=["claim_id", "unique_id", "text", "attribution", "nonoffer"])
            self._claims = c[(c.attribution != "other_facility") & ~c.nonoffer.fillna(False)]
        return self._claims

    def _match(self, cap):
        if cap not in self._matches:
            c = self._load_claims()
            hit = c[c.text.str.contains(_pattern(self.caps[cap]["evidence_words"]), na=False)]
            self._matches[cap] = hit.groupby("unique_id").claim_id.agg(list).to_dict()
        return self._matches[cap]

    def capability_p(self, facility_id, capability):
        cap = self.caps[capability]
        if cap["kb_status"] == "existing":
            key = (facility_id, cap["kb_service"])
            if key not in self._svc:
                return NO_MENTION_P, []
            return self._svc[key], self._cite.get(key, [])
        ids = self._match(capability).get(facility_id, [])
        if not ids:
            return NO_MENTION_P, []
        return (self.p_one_sentence if len(ids) == 1 else self.p_two_sentences), ids[:MAX_EVIDENCE]

    def describe(self):
        return {"source": "derived/v1 stub (not the fitted model)", "no_mention_p": NO_MENTION_P,
                "p_one_matching_sentence": round(self.p_one_sentence, 3),
                "p_two_or_more_matching_sentences": round(self.p_two_sentences, 3),
                "existing_capabilities": "service_claim score from data_point_scores.parquet"}
