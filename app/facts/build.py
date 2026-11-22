"""Export what the plan engine needs from derived/v1 (issue #42) into app/facts/out/facts.json.gz.

The app reads only that file at start-up (standard library, no pandas), the same pattern as the packs and the
website check. Every value is copied from derived/v1 unchanged; the only computed fields are joins (phone shared
counts, a source URL per record, prerequisites the grader did not find). When #11 publishes
derived/v2/facility_service_scores.parquet, its band / p / lo / hi are exported next to each pair and
engine.score() uses them; nothing else changes. Run from the repo root, after planner/export_v1.py
(the claims the planner cites are copied, so route stops show quotes):
    .venv-app/bin/python app/facts/build.py
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import re
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from common.eligibility import (  # noqa: E402, RUF100
    eligible_facilities,
    groups,
    report,
    same_site_groups,
    to_sites,
)

V1 = ROOT / "derived" / "v1"
V2 = ROOT / "derived" / "v2" / "facility_service_scores.parquet"
MODEL_CARD = ROOT / "derived" / "v2" / "model_card.json"
ATTRS = ROOT / "derived" / "v2" / "facility_attributes.parquet"  # operator: public / private / unknown (#86 action 5)
OPERATORS = {"public", "private"}
# derived/v2 bands to the app's three (lead, #2): CALL_FIRST and NO_SERVICE_TEXT both read "Not verified".
V2_BAND = {"LIKELY": "likely", "CALL_FIRST": "not_verified", "NO_SERVICE_TEXT": "not_verified", "UNLIKELY": "unlikely"}
MIN_V2_COVERAGE = 0.9  # per app service, the share of offered pairs v2 scores; below it the build fails (#84 review)
PLANNER = ROOT / "planner" / "out" / "planner_v1.json.gz"  # its cited claims ride along, so route stops show quotes
OUT = Path(__file__).resolve().parent / "out"
# app service id -> derived/v1 service name (cleaning/claims lexicon keys)
SERVICE_MAP = {"burn_care": "burns", "cardiac_surgery": "cardiac_surgery", "dialysis": "dialysis",
               "emergency_csection": "csection", "mri": "mri", "nicu": "nicu", "trauma_emergency": "trauma"}
V1_TO_APP = {v: k for k, v in SERVICE_MAP.items()}
# kb/taxonomy service ids (derived/v2) where they differ from the app's ids (#82 H4). Without this alias v2's
# trauma_care rows fail the join and trauma silently keeps the interim scores.
APP_TO_TAXONOMY = {"trauma_emergency": "trauma_care"}
TAXONOMY_TO_V1 = {APP_TO_TAXONOMY.get(a, a): v1 for a, v1 in SERVICE_MAP.items()}
MAX_EVIDENCE = 3
# Facilities the public standard expects to offer acute care (used only for the abstention "outside option").
PUBLIC_STANDARD = re.compile(r"\b(?:district hospital|sadar hospital|medical college|aiims"
                             r"|government (?:general )?hospital"
                             r"|civil hospital|general hospital|sub[- ]?divisional hospital|referral hospital)\b", re.I)


URL_KIND_RANK = {"about": 0, "list": 1, "unverified": 2}
FAR_KM = 25  # a source page about a place farther than this from the facility is flagged


def _places() -> dict[str, list[tuple[float, float]]]:
    g = pd.read_parquet(V1 / "place_gazetteer.parquet", columns=["name", "lat", "lon"]).dropna()
    out: dict[str, list[tuple[float, float]]] = {}
    for n, la, lo in zip(g.name, g.lat, g.lon, strict=True):
        out.setdefault(n, []).append((la, lo))
    return out


_PLACES: dict[str, list[tuple[float, float]]] | None = None


def wiki_place(url: object, lat: object, lon: object) -> list | None:
    """[place, km] when the source is a Wikipedia article about a place (place_gazetteer) far from the facility.

    The nearest gazetteer entry of that name is used, so the distance is a lower bound.
    """
    global _PLACES
    m = re.match(r"https?://[a-z]+\.wikipedia\.org/wiki/([^?#]+)", str(url or ""))
    if not m or lat is None or pd.isna(lat):
        return None
    title = unquote(m.group(1)).replace("_", " ").split(",")[0].strip()
    if _PLACES is None:
        _PLACES = _places()
    pts = _PLACES.get(title.lower())
    if not pts:
        return None
    km = min(haversine(float(lat), float(lon), a, b) for a, b in pts)
    return [title, round(km)] if km > FAR_KM else None


def haversine(la1: float, lo1: float, la2: float, lo2: float) -> float:
    p1, p2 = math.radians(la1), math.radians(la2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(a))


def e164(raw: str) -> str | None:
    d = re.sub(r"[\s\-().]", "", str(raw or ""))
    if re.fullmatch(r"[6-9]\d{9}|[1-9]\d{9}", d):
        return "+91" + d
    if re.fullmatch(r"0[1-9]\d{9}", d):
        return "+91" + d[1:]
    if re.fullmatch(r"\+91[1-9]\d{9}", d):
        return d
    return None


def col(series: pd.Series, nd: int | None = None) -> list:
    if nd is not None:
        return [None if pd.isna(x) else round(float(x), nd) for x in series]
    return [None if (not isinstance(x, (list, tuple)) and pd.isna(x)) else x for x in series]


def as_list(x: object) -> list:
    """A parquet list cell as a list; None or NaN (no trust row) as []."""
    return list(x) if isinstance(x, (list, tuple, np.ndarray)) else []


def facilities() -> tuple[pd.DataFrame, dict[str, int]]:
    loc = pd.read_parquet(V1 / "facility_location.parquet", columns=[
        "unique_id", "name", "address_city", "district", "state_final", "pin", "loc_lat", "loc_lon"])
    tr = pd.read_parquet(V1 / "record_trust.parquet", columns=[
        "unique_id", "display_phones", "trust_flags", "trust_reasons", "website_class", "trust_level"])
    ft = pd.read_parquet(V1 / "facility_trust.parquet", columns=[
        "unique_id", "existence_score", "location_score", "location_reason_codes", "drivers"])
    # Left merges: a record with no trust row is "unassessed" and kept (common/eligibility.py).
    f = loc.merge(tr, on="unique_id", how="left").merge(ft, on="unique_id", how="left")
    keep, counts = eligible_facilities(f)
    report("facts.facilities", counts)
    f = f[keep].reset_index(drop=True)
    phones = [str(p[0]) if len(as_list(p)) else "" for p in f.display_phones]
    shared = Counter(str(x) for p in tr.display_phones if p is not None for x in set(p))
    f["phone_raw"] = phones
    f["phone_e164"] = [e164(p) for p in phones]
    f["phone_shared"] = [shared.get(p, 0) if p else 0 for p in phones]
    f["loc_rule"] = f.location_reason_codes.fillna("").str.split("|").map(
        lambda codes: next((c for c in codes if c.startswith("LOC_")), ""))

    urls = pd.read_parquet(V1 / "source_urls.parquet",
                           columns=["unique_id", "url", "source_class", "domain_reliability", "url_kind"])
    urls = urls[urls.url.str.match(r"https?://")]
    urls["k"] = (~urls.source_class.isin(["official", "official_like"])).astype(int)
    # A page about this facility (url_kind from audit/provenance/q1_sources.py) before a list or an unchecked page
    # (#86): the shortest-path rule alone picked e.g. a Wikipedia page about another town.
    urls["kind_rank"] = urls.url_kind.map(URL_KIND_RANK).fillna(len(URL_KIND_RANK))
    urls["depth"] = urls.url.str.replace(r"^https?://[^/]+/?", "", regex=True).str.len()
    best = urls.sort_values(["unique_id", "k", "kind_rank", "depth", "domain_reliability"],
                            ascending=[True, True, True, True, False])
    best = best.drop_duplicates("unique_id").set_index("unique_id")
    f["url"] = f.unique_id.map(best.url)
    f["url_kind"] = f.unique_id.map(best.url_kind)
    f["url_place"] = [wiki_place(u, la, lo) if k != "about" else None
                      for u, k, la, lo in zip(f.url, f.url_kind, f.loc_lat, f.loc_lon, strict=True)]
    f["public_standard"] = f.name.fillna("").str.contains(PUBLIC_STANDARD)
    f["operator"] = operators(f.unique_id)
    return f, {u: i for i, u in enumerate(f.unique_id)}


def operators(ids: pd.Series) -> list[str]:
    """public / private from derived/v2 facility_attributes; "unknown" when absent, so the page shows no label."""
    if not ATTRS.is_file():
        return ["unknown"] * len(ids)
    op = pd.read_parquet(ATTRS, columns=["unique_id", "operator"]).drop_duplicates("unique_id").set_index("unique_id")
    return [x if x in OPERATORS else "unknown" for x in ids.map(op.operator)]


def v2_only(m: pd.DataFrame) -> pd.DataFrame:
    """Keep only pairs v2 scored, so one screen never mixes two scoring systems (#84 review). Prints the coverage per
    app service and fails below MIN_V2_COVERAGE: a bad join would otherwise drop most options without a sound."""
    cov = m.assign(scored=m.m_band.notna()).groupby("service").scored.mean()
    for svc, share in cov.items():
        print(f"facts.v2_coverage {V1_TO_APP[svc]}: {share:.1%}")
    low = cov[cov < MIN_V2_COVERAGE]
    if len(low):
        raise SystemExit(f"derived/v2 scores too few pairs for {sorted(V1_TO_APP[s] for s in low.index)}: check the "
                         "service join (TAXONOMY_TO_V1) before publishing")
    return m[m.m_band.notna()]


def pairs(fidx: dict[str, int]) -> tuple[dict[str, list], set[str]]:
    dps = pd.read_parquet(V1 / "data_point_scores.parquet", columns=[
        "dp_type", "unique_id", "service", "score", "score_lo", "score_hi", "status", "rule", "q_ev", "score_model"])
    dps = dps[dps.dp_type == "service_claim"].drop(columns="dp_type")
    g = pd.read_parquet(V1 / "grades.parquet")
    pre_cols = [c for c in g.columns if c.startswith("pre_")]
    risk_cols = [c for c in g.columns if c.startswith("risk_")]
    g = g[["unique_id", "service", "grade", "n_own_distinct", "cite_evidence", "qty", "scope_conflict",
           *pre_cols, *risk_cols]]
    m = dps.merge(g, on=["unique_id", "service"], how="inner")
    m = m[m.service.isin(V1_TO_APP) & m.unique_id.isin(fidx)]
    # Duplicate listings of one site become one facility (#78): the canonical record, with every member's evidence.
    loc = pd.read_parquet(V1 / "facility_location.parquet", columns=["unique_id", "loc_lat", "loc_lon"])
    sites, counts = same_site_groups(groups(), loc[loc.unique_id.isin(fidx)])
    report("facts.same_site_groups", counts)
    ev_of = {(u, s): [c["claim_id"] for c in json.loads(e or "[]")]
             for u, s, e in zip(m.unique_id, m.service, m.cite_evidence, strict=True)}
    m, counts = to_sites(m, sites)
    report("facts.duplicates", counts)
    if V2.is_file():
        v2 = pd.read_parquet(V2, columns=["unique_id", "service_id", "band", "p", "lo", "hi"])
        v2["service"] = v2.service_id.map(TAXONOMY_TO_V1)
        v2 = v2.dropna(subset=["service"])  # the other taxonomy services have no app tile yet
        bad = set(v2.band.str.upper()) - set(V2_BAND)
        if bad:
            raise SystemExit(f"derived/v2 has bands the app does not map: {sorted(bad)}")
        m = m.merge(v2.drop(columns="service_id").rename(columns={"p": "m_p", "lo": "m_lo", "hi": "m_hi",
                                                                  "band": "m_band"}), on=["unique_id", "service"],
                    how="left")
        m = v2_only(m)
    out: dict[str, list] = {k: [] for k in SERVICE_MAP}
    cited: set[str] = set()
    for r in m.itertuples(index=False):
        ev = list(dict.fromkeys(c for u in r.members for c in ev_of[(u, r.service)]))[: MAX_EVIDENCE * 3]
        cited.update(ev)
        missing = [c[4:] for c in pre_cols if isinstance(getattr(r, c), (bool,)) and getattr(r, c) is False]
        risks = [c[5:] for c in risk_cols if getattr(r, c) is True] + (["scope"] if r.scope_conflict else [])
        model = ([V2_BAND[r.m_band.upper()], r.m_p, r.m_lo, r.m_hi, r.m_band.upper()]
                 if "m_band" in m.columns and isinstance(r.m_band, str) else None)
        out[V1_TO_APP[r.service]].append([
            fidx[r.unique_id], r.grade, r.rule, r.status, round(r.score, 4), round(r.score_lo, 4),
            round(r.score_hi, 4), round(r.q_ev, 4), round(r.score_model, 4), ev, missing, risks,
            r.qty if isinstance(r.qty, str) else None, int(r.n_own_distinct), model, int(r.listings)])
    return out, cited


def planner_cited() -> set[str]:
    """Claim ids the multi-stop planner cites (#47). Build planner/export_v1.py first, or stops show ids only."""
    if not PLANNER.is_file():
        print("note: planner/out not built; route stops will carry claim ids without quotes")
        return set()
    with gzip.open(PLANNER, "rt", encoding="utf-8") as fh:
        caps = json.load(fh)["capabilities"]
    return {cid for c in caps.values() for ids in c["e"] for cid in ids}


# Sentence-level warnings the claims pipeline already computed (cleaning/claims), copied per cited sentence (#86).
CUE_FLAGS = {"cue_third_party": "third_party", "cue_hedge": "hedge", "cue_parttime": "parttime",
             "cue_camp": "camp", "cue_future": "future", "cue_past": "past"}
FLAG_COLS = ["attribution", "foreign_names", "places_other_district", "places_other_state", *CUE_FLAGS]


def claim_flags(r: object) -> list[list]:
    """[[code, detail]] for one claims.parquet row; detail is a place or facility name, or None."""
    out: list[list] = []
    if r.attribution == "ambiguous":
        out.append(["ambiguous", None])
    if r.foreign_names:
        out.append(["foreign", None])
    for col_, code in (("places_other_district", "other_district"), ("places_other_state", "other_state")):
        if getattr(r, col_):
            out.append([code, str(getattr(r, col_)).split("|")[0].strip().title()])
    out += [[code, None] for c, code in CUE_FLAGS.items() if getattr(r, c)]
    return out


def claims(ids: set[str]) -> tuple[dict[str, list], dict[str, list]]:
    c = pd.read_parquet(V1 / "claims.parquet", columns=["claim_id", "field", "text", "nonoffer", *FLAG_COLS])
    c = c[c.claim_id.isin(ids)]
    for k in ("foreign_names", "places_other_district", "places_other_state"):
        c[k] = c[k].fillna("")
    rows = {r.claim_id: [r.field, r.text, bool(r.nonoffer), r.attribution] for r in c.itertuples(index=False)}
    flags = {r.claim_id: f for r in c.itertuples(index=False) if (f := claim_flags(r))}
    return rows, flags


def track_bins(path: Path | None = None) -> list[dict]:
    """Three-outcome track record per score bin from derived/v2/model_card.json (#63, #82 H2); [] until published.

    Expected shape: {"calibration": {"bins": [{"lo", "hi", "n", "k_confirmed", "k_contradicted", "k_no_info",
    "split"}, ...]}}. A bin missing any count is dropped rather than shown with a made-up zero.
    """
    path = path or MODEL_CARD
    if not path.is_file():
        return []
    bins = json.loads(path.read_text()).get("calibration", {}).get("bins", [])
    keys = ("lo", "hi", "n", "k_confirmed", "k_contradicted", "k_no_info")
    return [{k: b[k] for k in (*keys, "split") if k in b} | {"split": b.get("split", "dev")}
            for b in bins if all(isinstance(b.get(k), (int, float)) for k in keys)]


def rules() -> dict[str, dict]:
    e = pd.read_parquet(V1 / "evidence_rules.parquet")
    return {r.rule: {"n": int(r.handcheck_true + r.handcheck_false + r.dev_true + r.dev_false),
                     "k_confirmed": int(r.handcheck_true + r.dev_true),
                     "k_contradicted": int(r.handcheck_false + r.dev_false), "q_ev": round(float(r.q_ev), 4),
                     "citation": r.citation} for r in e.itertuples(index=False)}


def pins() -> dict[str, list]:
    p = pd.read_parquet(V1 / "pin_gazetteer.parquet", columns=["pin", "state", "district", "lat", "lon"])
    p = p.dropna(subset=["lat", "lon", "district"])
    return {"pin": [int(x) for x in p.pin], "lat": col(p.lat, 5), "lon": col(p.lon, 5),
            "district": list(p.district), "state": list(p.state)}


def main() -> None:
    t0 = time.time()
    f, fidx = facilities()
    pr, cited = pairs(fidx)
    claim_rows, claim_fl = claims(cited | planner_cited())
    manifest = json.loads((V1 / "MANIFEST.json").read_text())
    facts = {
        "meta": {"as_of": manifest["build_date"], "source": "derived/v1",
                 "scores": "derived/v2 facility_service_scores" if V2.is_file() else
                 "interim: derived/v1 data_point_scores (likely only when verified true)",
                 "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        "rules": rules(),
        "track_bins": track_bins(),
        "fac": {"id": list(f.unique_id), "name": list(f.name), "city": col(f.address_city),
                "district": col(f.district), "state": col(f.state_final),
                "pin": [None if pd.isna(x) else int(x) for x in f.pin],
                "lat": col(f.loc_lat, 5), "lon": col(f.loc_lon, 5),
                "p_e": col(f.existence_score, 3), "p_l": col(f.location_score, 3), "loc_rule": list(f.loc_rule),
                "phone_e164": col(f.phone_e164), "phone_raw": list(f.phone_raw), "phone_shared": list(f.phone_shared),
                "flags": [as_list(x) for x in f.trust_flags],
                "reasons": [as_list(x) for x in f.trust_reasons],
                "website_own": list(f.website_class == "own"), "url": col(f.url),
                "url_kind": col(f.url_kind), "url_place": list(f.url_place),
                "public_standard": [bool(x) for x in f.public_standard], "operator": list(f.operator)},
        "pairs": pr,
        "claims": claim_rows,
        "claim_flags": claim_fl,
        "pins": pins(),
    }
    # The hash covers the data only (not built_at), so model_hash changes only when the data does.
    content = {k: v for k, v in facts.items() if k != "meta"} | {"meta": {**facts["meta"], "built_at": None}}
    facts_hash = hashlib.sha256(json.dumps(content, separators=(",", ":"), sort_keys=True).encode()).hexdigest()[:12]
    raw = json.dumps(facts, separators=(",", ":"), ensure_ascii=False).encode()
    OUT.mkdir(exist_ok=True)
    (OUT / "facts.json.gz").write_bytes(gzip.compress(raw, 6))
    (OUT / "facts.sha").write_text(facts_hash + "\n")
    n_pairs = sum(len(v) for v in pr.values())
    print(f"{len(f)} facilities, {n_pairs} pairs, {len(facts['claims'])} claims, {len(facts['pins']['pin'])} PINs; "
          f"{len(raw) / 1e6:.1f} MB raw, {(OUT / 'facts.json.gz').stat().st_size / 1e6:.1f} MB gz; "
          f"{time.time() - t0:.1f} s; sha {facts_hash}")


if __name__ == "__main__":
    main()
