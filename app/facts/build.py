"""Export what the plan engine needs from derived/v1 (issue #42) into app/facts/out/facts.json.gz.

The app reads only that file at start-up (standard library, no pandas), the same pattern as the packs and the
website check. Every value is copied from derived/v1 unchanged; the only computed fields are joins (phone shared
counts, a source URL per record, prerequisites the grader did not find) and the shown name, which is
common/names.py display_name (no address tail; the raw name stays in derived/v1 and the website check).
When #11 publishes derived/v2/facility_service_scores.parquet, its band / p / lo / hi / p_location / p_exists are
exported next to each pair and engine.score() uses them, with the model's own ledger: its named terms in points, which
sum to the score (ledger() below; the plain words are in ledger_terms.py). The cards show the model's own P_L and P_E,
not the derived/v1 facility trust scores (#121). Run from the repo root, after planner/export_v2.py
(the claims the planner cites are copied, so route stops show quotes):
    .venv-app/bin/python app/facts/build.py
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
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
from common.names import display_name  # noqa: E402, RUF100
from common.typefit import fit_mask, kinds_by_id  # noqa: E402, RUF100

sys.path.insert(0, str(ROOT / "app"))
from facts.ledger_terms import NOT_OBSERVED, TERMS  # noqa: E402

# DATATHON_ROOT: the folder holding derived/v1, for example the Databricks volume that
# submission/00_rebuild_derived.ipynb writes to (#86 step 2; same variable as planner/data_v1.py). Default: this repo.
# derived/v2 (the frozen model) and planner/out always come from the repo; the rebuild does not remake them.
DATA_ROOT = Path(os.environ.get("DATATHON_ROOT") or ROOT)
V1 = DATA_ROOT / "derived" / "v1"
V2 = ROOT / "derived" / "v2" / "facility_service_scores.parquet"
MODEL_CARD = ROOT / "derived" / "v2" / "model_card.json"
ATTRS = ROOT / "derived" / "v2" / "facility_attributes.parquet"  # operator: public / private / unknown (#86 action 5)
OPERATORS = {"public", "private"}
# derived/v2 bands to the app's three (lead, #2): CALL_FIRST and NO_SERVICE_TEXT both read "Not verified".
V2_BAND = {"LIKELY": "likely", "CALL_FIRST": "not_verified", "NO_SERVICE_TEXT": "not_verified", "UNLIKELY": "unlikely"}
MIN_V2_COVERAGE = 0.9  # per app service, the share of offered pairs v2 scores; below it the build fails (#84 review)
PLANNER = ROOT / "planner" / "out" / "planner_v2.json.gz"  # its cited claims ride along, so route stops show quotes
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
# The "outside option" (#85 H2): a public facility whose level IPHS 2022 expects to offer the service, read from
# derived/v2 facility_features g_iphs_prior (> 0: essential, desirable or size dependent at that level; NaN when the
# facility is not public or its level is unknown). Per service, so a district hospital is never named for cardiac
# surgery. AYUSH and dental colleges match "medical college" in the level rule but offer none of these services.
FEATURES = ROOT / "derived" / "v2" / "facility_features.parquet"
WITNESSES = ROOT / "derived" / "v2" / "witnesses.parquet"
# derived/v2 ledger (README there): logit(p) = base + sum(points) / PDO. The app keeps its own scale, APP_SCALE points
# per logit unit (engine._pts, the field-report row), and ships tenths of a point.
PDO = 20 / math.log(2)
APP_SCALE = 10
CLAIM_ID = re.compile(r"[0-9a-f]{8}:[a-z]{4}:\d+")  # a derived/v1 claim id; v2 also cites lists, pages, record:name
NOT_ALLOPATHIC = re.compile(r"ayurved|homoeo|homeo|unani|siddha|\bayush\b|naturopath|yoga|dental", re.I)


URL_KIND_RANK = {"about": 0, "list": 1, "unverified": 2}
FAR_KM = 25  # a source page about a place farther than this from the facility is flagged
# Town vs map point (#140 2b, #117): the listed town (address_city, found in place_gazetteer within the record's state)
# more than TOWN_FAR_KM from the map point flags "town and map point disagree"; such a facility is never emergency
# option 1. Only gazetteer cities are used: post-office names repeat across a state (a "Chinchwad" office near
# Kolhapur flagged Chinchwad, Pune). A town not found, or spread wider than TOWN_SPREAD_KM, is not judged.
TOWN_FAR_KM = 100
TOWN_SPREAD_KM = 25
# Hand-checked location disputes (#117, #140): flagged whatever the gazetteer rule finds.
LOC_DISPUTED = {
    "7e420f3f-0cc7-4b8e-811d-7cb54fe1505b": "Sharda Hospital: address Greater Noida, map point in Chandauli",
}
SITE_CLASSES = {"official", "official_like"}  # a cited URL of these classes is the listed website (kb/crawl targets)
# BE-001 (#136): a site the crawl could not read is "unchecked", which says nothing against the facility; only positive
# evidence against the site makes it "unreliable". Neither is ever cited as a source.
SITE_STATUS = {"no_usable_page": "unchecked", "no_identity": "unreliable", "other_org": "unreliable"}


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
    if re.fullmatch(r"1800\d{6,8}", d):  # Indian toll-free: no E.164 form, but dialled as is from any phone in India
        return d
    return None


def town_far(f: pd.DataFrame) -> list[bool]:
    """Per record: its listed town is more than TOWN_FAR_KM from its map point, or it is in LOC_DISPUTED."""
    g = pd.read_parquet(V1 / "place_gazetteer.parquet", columns=["state", "name", "lat", "lon", "spread_km", "kind"])
    g = g[(g.kind == "city") & (g.spread_km <= TOWN_SPREAD_KM)].dropna(subset=["lat", "lon"])
    towns: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for st, n, la, lo in zip(g.state, g.name, g.lat, g.lon, strict=True):
        towns.setdefault((st, n), []).append((la, lo))
    out = []
    for u, city, st, la, lo in zip(f.unique_id, f.address_city, f.state_final, f.loc_lat, f.loc_lon, strict=True):
        key = (str(st).upper(), " ".join(str(city).lower().split()))
        pts = towns.get(key) if isinstance(city, str) and pd.notna(la) and pd.notna(lo) else None
        out.append(u in LOC_DISPUTED or bool(pts) and min(haversine(la, lo, a, b) for a, b in pts) > TOWN_FAR_KM)
    return out


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
    f["town_far"] = town_far(f)
    print(f"facts.town_far: {int(f.town_far.sum())} records whose listed town is more than {TOWN_FAR_KM} km from "
          f"the map point ({len(LOC_DISPUTED)} hand-checked)")

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
    f["url_site"] = f.unique_id.map(best.source_class).isin(SITE_CLASSES)
    f["site_flag"] = site_flags(f.unique_id, f.trust_flags)
    f["site_status"] = f.site_flag.map(SITE_STATUS)
    f["url_place"] = [wiki_place(u, la, lo) if k != "about" else None
                      for u, k, la, lo in zip(f.url, f.url_kind, f.loc_lat, f.loc_lon, strict=True)]
    f["public_standard"] = public_standard(f.unique_id, f.name)
    f["public_level"] = public_levels(f.unique_id)
    f["operator"] = operators(f.unique_id)
    return f, {u: i for i, u in enumerate(f.unique_id)}


def public_standard(ids: pd.Series, names: pd.Series) -> list[list[str]]:
    """Per facility, the app services the public standard (IPHS 2022) expects it to offer at its level; [] if none."""
    if not FEATURES.is_file():
        return [[] for _ in ids]
    tax = {APP_TO_TAXONOMY.get(a, a): a for a in SERVICE_MAP}
    g = pd.read_parquet(FEATURES, columns=["unique_id", "service", "g_iphs_prior"])
    g = g[g.service.isin(tax) & (g.g_iphs_prior > 0)]
    by = g.groupby("unique_id").service.agg(lambda s: sorted(tax[x] for x in s)).to_dict()
    return [[] if NOT_ALLOPATHIC.search(n or "") else by.get(u, []) for u, n in zip(ids, names, strict=True)]


def public_levels(ids: pd.Series) -> list[str]:
    """phc / chc / sdh / dh / mc from derived/v2 facility_attributes; "" when unknown."""
    if not ATTRS.is_file():
        return [""] * len(ids)
    lv = pd.read_parquet(ATTRS, columns=["unique_id", "facility_level"]).drop_duplicates("unique_id").set_index("unique_id")
    return [x if x in ("phc", "chc", "sdh", "dh", "mc") else "" for x in ids.map(lv.facility_level)]


def operators(ids: pd.Series) -> list[str]:
    """public / private from derived/v2 facility_attributes; "unknown" when absent, so the page shows no label."""
    if not ATTRS.is_file():
        return ["unknown"] * len(ids)
    op = pd.read_parquet(ATTRS, columns=["unique_id", "operator"]).drop_duplicates("unique_id").set_index("unique_id")
    return [x if x in OPERATORS else "unknown" for x in ids.map(op.operator)]


def _web_state(ids: pd.Series) -> pd.Series:
    """derived/v2 web_state per id: alive, dead or none (kb/crawl/sites.parquet, model/v2/assemble/build.py)."""
    ws = pd.read_parquet(ATTRS, columns=["unique_id", "web_state"]).drop_duplicates("unique_id")
    return ids.map(ws.set_index("unique_id").web_state)


def site_flags(ids: pd.Series, trust_flags: pd.Series) -> list[str | None]:
    """Why the listed website is not cited (#117 A), from existing crawl outputs; None when no reason is known.

    other_org: record_trust flag website_may_belong_to_other_org. no_usable_page: derived/v2 web_state "dead", i.e.
    no kb/crawl target of the record ended ok or ok_thin (dead, parked, spam, a redirect elsewhere, or blocked).
    no_identity: the site is live but no page names the facility, or it is a for-sale page (e_identity_conf 0).
    Display only: the frozen model reads the same crawl through its W-family terms and is not changed.
    SITE_STATUS maps each reason to its label: no_usable_page is unchecked, the other two are unreliable (BE-001).
    """
    other = [any(x == "website_may_belong_to_other_org" for x in as_list(t)) for t in trust_flags]
    if not (ATTRS.is_file() and FEATURES.is_file()):
        return ["other_org" if o else None for o in other]
    conf = pd.read_parquet(FEATURES, columns=["unique_id", "e_identity_conf"]).groupby("unique_id").e_identity_conf
    state, idc = _web_state(ids), ids.map(conf.max())
    return ["other_org" if o else "no_usable_page" if s == "dead" else "no_identity" if s == "alive" and c == 0
            else None for o, s, c in zip(other, state, idc, strict=True)]


def site_check(f: pd.DataFrame) -> dict:
    """Counts for the How page: facilities with a crawled website, and how many are flagged, by status and reason."""
    if not ATTRS.is_file():
        return {}
    flags, status = f.site_flag.dropna(), f.site_status.dropna()
    return {"n_with_site": int(_web_state(f.unique_id).isin(["alive", "dead"]).sum()), "n_flagged": len(flags),
            "n_unchecked": int((status == "unchecked").sum()), "n_unreliable": int((status == "unreliable").sum()),
            "by_reason": {k: int(v) for k, v in flags.value_counts().items()},
            "n_cited_site": int((f.site_flag.notna() & f.url_site).sum())}


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


def band_rule_violations(m: pd.DataFrame, card_path: Path | None = None) -> int:
    """LIKELY pairs whose exported p, P_L or P_E is below the model card's band_thresholds.likely (#121). The T >= 2
    term is not in the export, so it is not rechecked here."""
    card_path = card_path or MODEL_CARD
    if not card_path.is_file():
        return 0
    t = json.loads(card_path.read_text())["band_thresholds"]["likely"]
    lk = m[m.m_band.str.upper() == "LIKELY"]
    return int(((lk.m_p < t["p"]) | (lk.m_pl < t["p_location"]) | (lk.m_pe < t["p_exists"])).sum())


def check_band_rule(m: pd.DataFrame, card_path: Path | None = None) -> None:
    """Fail when a served LIKELY pair breaks the rule the How page states. The model is frozen, so a failure is a
    model or export issue to report, never something to re-band here."""
    n = band_rule_violations(m, card_path)
    if n:
        raise SystemExit(f"{n} derived/v2 LIKELY pairs break band_thresholds.likely in model_card.json: report it to "
                         "the model owner; do not re-band in the app")


def v2_terms(terms: pd.Series) -> tuple[set[str], dict[str, str]]:
    """(evidence ids that are app claims, family of each term label) over the served pairs' contributions.

    An id is an app claim when it is a derived/v1 claim and v2's witness quote for it is that claim's text or a clause
    of it (40 of about 30,600 are clauses), so the page never shows another sentence under the id. Specialty items
    (":spec:") are not v1 claims and are left out, as are list, website and standard ids.
    """
    parsed = [json.loads(c) for c in terms]
    ids = {e for ts in parsed for t in ts for e in t["evidence_ids"] if CLAIM_ID.fullmatch(e)}
    family = {t["label"]: t["family"] for ts in parsed for t in ts}
    text = pd.read_parquet(V1 / "claims.parquet", columns=["claim_id", "text"])
    text = text[text.claim_id.isin(ids)]
    w = pd.read_parquet(WITNESSES, columns=["evidence_id", "quote"], filters=[("observability", "==", "present")])
    quote = w[w.evidence_id.isin(ids)].drop_duplicates("evidence_id").set_index("evidence_id").quote
    same = {c for c, t in zip(text.claim_id, text.text, strict=True) if isinstance(quote.get(c), str) and quote[c] in t}
    print(f"facts.ledger_claims: {len(same)} of {len(ids)} cited claim ids are app claims")
    return same, family


def ledger(base: float, terms_json: str, p: float, same: set[str]) -> list[list]:
    """[[term, tenths of an app point, [app claim ids]], ...] for one pair: base first, terms with 0 points left out.

    Each row is APP_SCALE x its logit contribution. Rounding to tenths is spread by largest remainder, so the rows sum
    exactly to round(10 x APP_SCALE x logit(p)) and the total maps back to p within 0.0013.
    """
    terms = [t for t in json.loads(terms_json) if t["points"]]
    unnamed = {t["label"] for t in terms} - TERMS.keys()
    if unnamed:
        raise SystemExit(f"derived/v2 terms without plain words in app/facts/ledger_terms.py: {sorted(unnamed)}")
    exact = [10 * APP_SCALE * x for x in (base, *(t["points"] / PDO for t in terms))]
    if abs(sum(exact) / (10 * APP_SCALE) - math.log(p / (1 - p))) > 1e-6:
        raise SystemExit(f"derived/v2 ledger does not sum to logit(p) = logit({p}): {terms_json[:200]}")
    tenths = [math.floor(x) for x in exact]
    for k in sorted(range(len(exact)), key=lambda k: tenths[k] - exact[k])[: round(sum(exact)) - sum(tenths)]:
        tenths[k] += 1
    ids = [[], *([e for e in t["evidence_ids"] if e in same][:MAX_EVIDENCE] for t in terms)]
    return [[n, x, i] for n, x, i in zip(("base", *(t["label"] for t in terms)), tenths, ids, strict=True)]


def not_observed(m: pd.DataFrame) -> list[str]:
    """Per pair, the NOT_OBSERVED families derived/v2 cannot see (facility_features obs_<family>), e.g. "WO"."""
    fams = list(NOT_OBSERVED)
    ff = pd.read_parquet(FEATURES, columns=["unique_id", "service", *(f"obs_{f}" for f in fams)])
    ff["service"] = ff.service.map(TAXONOMY_TO_V1)
    ff = ff.dropna(subset=["service"]).set_index(["unique_id", "service"])
    obs = ff.reindex(pd.MultiIndex.from_arrays([m.unique_id, m.service]))
    return ["".join(f for f in fams if row[f"obs_{f}"] == "not_observable") for _, row in obs.iterrows()]


def pairs(fidx: dict[str, int]) -> tuple[dict[str, list], set[str], dict[str, list]]:
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
    m = type_fit(m)
    if V2.is_file():
        v2 = pd.read_parquet(V2, columns=["unique_id", "service_id", "band", "p", "lo", "hi", "p_location",
                                          "p_exists", "base", "contributions"])
        v2["service"] = v2.service_id.map(TAXONOMY_TO_V1)
        v2 = v2.dropna(subset=["service"])  # the other taxonomy services have no app tile yet
        bad = set(v2.band.str.upper()) - set(V2_BAND)
        if bad:
            raise SystemExit(f"derived/v2 has bands the app does not map: {sorted(bad)}")
        m = m.merge(v2.drop(columns="service_id").rename(columns={"p": "m_p", "lo": "m_lo", "hi": "m_hi",
                                                                  "band": "m_band", "p_location": "m_pl",
                                                                  "p_exists": "m_pe", "base": "m_base",
                                                                  "contributions": "m_terms"}),
                    on=["unique_id", "service"], how="left")
        m = v2_only(m)
        check_band_rule(m)
        m["not_observed"] = not_observed(m)
        same, family = v2_terms(m.m_terms)
    else:
        same, family = set(), {}
    out: dict[str, list] = {k: [] for k in SERVICE_MAP}
    cited: set[str] = set()
    for r in m.itertuples(index=False):
        ev = list(dict.fromkeys(c for u in r.members for c in ev_of[(u, r.service)]))[: MAX_EVIDENCE * 3]
        cited.update(ev)
        missing = [c[4:] for c in pre_cols if isinstance(getattr(r, c), (bool,)) and getattr(r, c) is False]
        risks = [c[5:] for c in risk_cols if getattr(r, c) is True] + (["scope"] if r.scope_conflict else [])
        # P_L and P_E are the model's own (derived/v2 p_location, p_exists): the values its LIKELY rule tested.
        model = ([V2_BAND[r.m_band.upper()], r.m_p, r.m_lo, r.m_hi, r.m_band.upper(), round(float(r.m_pl), 3),
                  round(float(r.m_pe), 3)]
                 if "m_band" in m.columns and isinstance(r.m_band, str) else None)
        led = ledger(r.m_base, r.m_terms, r.m_p, same) if model else None
        cited.update(c for *_, ids in led or [] for c in ids)
        out[V1_TO_APP[r.service]].append([
            fidx[r.unique_id], r.grade, r.rule, r.status, round(r.score, 4), round(r.score_lo, 4),
            round(r.score_hi, 4), round(r.q_ev, 4), round(r.score_model, 4), ev, missing, risks,
            r.qty if isinstance(r.qty, str) else None, int(r.n_own_distinct), model, int(r.listings),
            led, r.not_observed if model else ""])
    used = {"base": "base", **family}
    words = {"terms": {k: [used[k], *TERMS[k]] for k in sorted(used)},
             "not_observed": {k: list(v) for k, v in NOT_OBSERVED.items()}}
    return out, cited, words


def type_fit(m: pd.DataFrame) -> pd.DataFrame:
    """Drop pairs whose facility type cannot offer the service (#117 B, common/typefit.py, the planner's rule too):
    a dental, eye or AYUSH place is never an option. Read from the shown site's own name and type field."""
    loc = pd.read_parquet(V1 / "facility_location.parquet", columns=["unique_id", "name"])
    at = pd.read_parquet(ATTRS, columns=["unique_id", "facilityTypeId"]) if ATTRS.is_file() else loc[["unique_id"]]
    f = loc[loc.unique_id.isin(set(m.unique_id))].merge(at, on="unique_id", how="left")
    kinds = kinds_by_id(f.unique_id, f.name, f.facilityTypeId if "facilityTypeId" in f else [None] * len(f))
    keep, counts = fit_mask(m.unique_id, m.service.map(V1_TO_APP), kinds)
    report("facts.type_fit_left_out", counts)
    return m[keep]


def planner_cited() -> set[str]:
    """Claim ids the multi-stop planner cites (#47). Build planner/export_v2.py first, or stops show ids only."""
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

    Reads `calibration_by_score_bin`: p_min, p_max, n_decided, k_confirmed, k_contradicted, k_no_info (DEV pairs whose
    labeller searched and found nothing). n here is every checked pair: decided plus no information. Pairs never
    searched are not checks and are left out. A bin missing any count is dropped rather than shown with a made-up 0.
    """
    path = path or MODEL_CARD
    if not path.is_file():
        return []
    keys = ("p_min", "p_max", "n_decided", "k_confirmed", "k_contradicted", "k_no_info")
    return [{"lo": b["p_min"], "hi": b["p_max"], "n": b["n_decided"] + b["k_no_info"], "k_confirmed": b["k_confirmed"],
             "k_contradicted": b["k_contradicted"], "k_no_info": b["k_no_info"], "split": b.get("split", "dev")}
            for b in json.loads(path.read_text()).get("calibration_by_score_bin", [])
            if all(isinstance(b.get(k), (int, float)) for k in keys)]


def likely_threshold(path: Path | None = None) -> float | None:
    """t_L, the model's p threshold for LIKELY (model_card band_thresholds); None before v2 is published."""
    path = path or MODEL_CARD
    if not path.is_file():
        return None
    return json.loads(path.read_text()).get("band_thresholds", {}).get("likely", {}).get("p")


GOLD_V3 = ROOT / "model" / "gold" / "v3"
TEST_RESULTS = GOLD_V3 / "test_eval" / "results.json"
OPENING_LOG = GOLD_V3 / "OPENING_LOG.md"
TEST_LABELS_SHA = GOLD_V3 / "test_labels.sha256"


def opening_log(path: Path = OPENING_LOG) -> dict[str, str]:
    """The single 'opened' row of OPENING_LOG.md: its date and the two committed hashes. Fails on zero or two rows."""
    rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in path.read_text().splitlines()
            if ln.startswith("| opened ")]
    if len(rows) != 1:
        raise SystemExit(f"{path}: expected exactly one 'opened' row, found {len(rows)}")
    return {"opened": rows[0][1], "predictions_sha256": rows[0][3], "labels_sha256": rows[0][4]}


def sealed_test_record(card_path: Path | None = None, results_path: Path = TEST_RESULTS) -> dict | None:
    """The sealed gold v3 TEST record of the LIKELY band (#86, #66), from model/gold/v3/test_eval/results.json.

    None when the file is absent or the app does not serve the model the record is about (interim scores, or a
    model_version other than the one the TEST was run against). Fails when the opening log, the label commitment and
    the results disagree, or when the public-facility caveat the page shows stops being true.
    """
    card_path = card_path or MODEL_CARD
    if not (results_path.is_file() and card_path.is_file() and V2.is_file()):
        return None
    res, card = json.loads(results_path.read_text()), json.loads(card_path.read_text())
    if res["model_version"] != card.get("model_version"):
        return None
    log = opening_log()
    labels_full = next(ln.split()[0] for ln in TEST_LABELS_SHA.read_text().splitlines()
                       if ln.endswith(".full.canonical"))
    if log["predictions_sha256"] != res["test_predictions_sha256"] or log["labels_sha256"] != labels_full:
        raise SystemExit(f"{OPENING_LOG}: hashes differ from {results_path.name} or {TEST_LABELS_SHA.name}")
    lk, pub = res["headline_decided"]["LIKELY_confirmed"], res["by_operator_decided"]["public"]
    if pub["auroc_ci95"][0] > 0.5:
        raise SystemExit(f"{results_path}: public AUROC interval excludes 0.5; update the public caveat in app.js")
    rel = lambda p: str(p.relative_to(ROOT))  # noqa: E731
    return {"split": "test", "k": lk["k"], "n": lk["n"], "pct": round(100 * lk["rate"]),
            "lo_pct": round(100 * lk["ci95"][0]), "hi_pct": round(100 * lk["ci95"][1]),
            "public_n": pub["n"], "model_version": res["model_version"],
            "predictions_sha256": res["test_predictions_sha256"], "labels_sha256": labels_full,
            "opened": log["opened"], "source": rel(results_path), "log": rel(OPENING_LOG),
            "log_url": f"https://github.com/LordKarV/databricksdatathon/blob/dev/{rel(OPENING_LOG)}"}


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


# validation C4: many gazetteer PIN points sit in another district (PIN 847428, Darbhanga, is placed in Begusarai).
# The LGD join (external/lgd_district_polygons/join_test.py) puts every India Post office in its LGD district polygon;
# the file is git-ignored data, so without it the area view keeps each PIN's own district.
LGD_REL = Path("data") / "external" / "lgd_district_polygons" / "pin_lgd_district.parquet"
# DATA_ROOT first (a worktree or the Databricks volume holds the git-ignored data there), then the repo.
LGD_PINS = next((r / LGD_REL for r in (DATA_ROOT, ROOT) if (r / LGD_REL).is_file()), ROOT / LGD_REL)
NEAR_DEG = 0.01  # an office this close (lat + lon degrees, about 1 km) stands for the PIN point's own polygon


def pin_districts(p: dict[str, list]) -> dict[str, list[str]]:
    """{pin: [district, state]} where a PIN's point lies in another district than the gazetteer files it under: the
    LGD district of an office within NEAR_DEG of the point, in the gazetteer's spelling (the district most offices
    of that LGD polygon carry). Only disagreements are kept; a point with no office that close keeps its own."""
    if not LGD_PINS.is_file():
        return {}
    o = pd.read_parquet(LGD_PINS, columns=["pincode", "district", "statename", "latitude", "longitude", "dist_lgd"])
    o = o.assign(lat=pd.to_numeric(o.latitude, errors="coerce"), lon=pd.to_numeric(o.longitude, errors="coerce"))
    o = o.dropna(subset=["district", "statename", "lat", "lon", "dist_lgd"])
    o = o[o.dist_lgd > 0]
    name = o.groupby("dist_lgd")[["district", "statename"]].agg(lambda c: c.mode()[0])
    pt = pd.DataFrame({"pincode": p["pin"], "plat": p["lat"], "plon": p["lon"], "own": list(zip(p["district"], p["state"], strict=True))})
    m = o.merge(pt, on="pincode")
    m = m.assign(d=(m.lat - m.plat).abs() + (m.lon - m.plon).abs())
    m = m[m.d <= NEAR_DEG].sort_values("d").drop_duplicates("pincode")
    out = {}
    for pin, code, own in zip(m.pincode, m.dist_lgd, m.own, strict=True):
        where = tuple(name.loc[code])
        if where != own:
            out[str(pin)] = list(where)
    return out


PLACE_KINDS = ("city", "office")  # towns, then post office names (most villages have one)


def places() -> dict:
    """Town and post office names from place_gazetteer for the typed-place lookup (#121 bug 5), kept out of facts.

    Districts and PINs come from the PIN table already in facts.json.gz. One row per state and name; a town beats a
    post office of the same name. 0.001 degree (about 100 m) is finer than the plan's 0.01 degree rounding.
    """
    g = pd.read_parquet(V1 / "place_gazetteer.parquet", columns=["state", "name", "lat", "lon", "kind"])
    g = g[g.kind.isin(PLACE_KINDS)].dropna(subset=["name", "lat", "lon", "state"])
    g = g.assign(rank=g.kind.map(PLACE_KINDS.index)).sort_values(["state", "name", "rank"])
    g = g.drop_duplicates(["state", "name"])
    states = sorted(g.state.unique())
    s_idx = {s: i for i, s in enumerate(states)}
    return {"v": 1, "kinds": list(PLACE_KINDS), "states": states, "name": list(g.name),
            "s": [s_idx[x] for x in g.state], "k": [int(x) for x in g["rank"]],
            "lat": col(g.lat, 3), "lon": col(g.lon, 3)}


def scores_source() -> str:
    """Which scores the app serves, in words a judge reads on the How page and in the build log (#86 item 2)."""
    if not V2.is_file():
        return "interim v1 (v2 export not present)"
    card = json.loads(MODEL_CARD.read_text()) if MODEL_CARD.is_file() else {}
    return f"model v2 export, model_version {str(card.get('model_version', 'unknown'))[:12]}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT, help="output folder (default app/facts/out, which the app reads)")
    out = ap.parse_args().out
    t0 = time.time()
    f, fidx = facilities()
    pr, cited, ledger_words = pairs(fidx)
    claim_rows, claim_fl = claims(cited | planner_cited())
    manifest = json.loads((V1 / "MANIFEST.json").read_text())
    facts = {
        "meta": {"as_of": manifest["build_date"], "source": "derived/v1",
                 "data_root": "repo" if DATA_ROOT == ROOT else str(DATA_ROOT),
                 "scores": scores_source(),
                 "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        "rules": rules(),
        "track_bins": track_bins(),
        "likely_threshold": likely_threshold(),
        "test_record": sealed_test_record(),
        "site_check": site_check(f),
        "fac": {"id": list(f.unique_id), "name": [display_name(n) for n in f.name], "city": col(f.address_city),
                "district": col(f.district), "state": col(f.state_final),
                "pin": [None if pd.isna(x) else int(x) for x in f.pin],
                "lat": col(f.loc_lat, 5), "lon": col(f.loc_lon, 5), "town_far": [bool(x) for x in f.town_far],
                "p_e": col(f.existence_score, 3), "p_l": col(f.location_score, 3), "loc_rule": list(f.loc_rule),
                "phone_e164": col(f.phone_e164), "phone_raw": list(f.phone_raw), "phone_shared": list(f.phone_shared),
                "flags": [as_list(x) for x in f.trust_flags],
                "reasons": [as_list(x) for x in f.trust_reasons],
                "website_own": list(f.website_class == "own"), "url": col(f.url),
                "url_kind": col(f.url_kind), "url_place": list(f.url_place),
                "url_site": [bool(x) for x in f.url_site], "site_flag": col(f.site_flag),
                "site_status": col(f.site_status),
                "public_standard": list(f.public_standard), "public_level": list(f.public_level),
                "operator": list(f.operator)},
        "pairs": pr,
        "ledger": ledger_words,  # plain words for the pairs' ledger rows: {"terms": {term: [family, en, hi]}, ...}
        "claims": claim_rows,
        "claim_flags": claim_fl,
        "pins": pins(),
    }
    # The hash covers the data only (not built_at or where it was read from), so it changes only when the data does
    # and a rebuild of derived/v1 that matches the repo gives the same hash (#86 step 3).
    content = {k: v for k, v in facts.items() if k != "meta"} | {
        "meta": {**facts["meta"], "built_at": None, "data_root": None}}
    facts_hash = hashlib.sha256(json.dumps(content, separators=(",", ":"), sort_keys=True).encode()).hexdigest()[:12]
    raw = json.dumps(facts, separators=(",", ":"), ensure_ascii=False).encode()
    out.mkdir(parents=True, exist_ok=True)
    (out / "facts.json.gz").write_bytes(gzip.compress(raw, 6))
    (out / "facts.sha").write_text(facts_hash + "\n")
    # Outside facts.json and its hash: the file comes from git-ignored data, so a derived/v1 rebuild still matches.
    moved = pin_districts(facts["pins"])
    (out / "pin_districts.json").write_text(json.dumps(moved, separators=(",", ":")))
    print(f"pin districts: {len(moved)} PINs filed under another district than the one their point lies in"
          if moved else f"pin districts: {LGD_REL} not found under DATATHON_ROOT or the repo, area view uses each PIN's own district")
    pl = places()
    (out / "places.json.gz").write_bytes(gzip.compress(json.dumps(pl, separators=(",", ":")).encode(), 6))
    print(f"scores: {facts['meta']['scores']}")
    print(f"listed websites (#117 A): {facts['site_check']}")
    n_pairs = sum(len(v) for v in pr.values())
    print(f"{len(f)} facilities, {n_pairs} pairs, {len(facts['claims'])} claims, {len(facts['pins']['pin'])} PINs, "
          f"{len(pl['name'])} places (places.json.gz); "
          f"{len(raw) / 1e6:.1f} MB raw, {(out / 'facts.json.gz').stat().st_size / 1e6:.1f} MB gz; "
          f"{time.time() - t0:.1f} s; sha {facts_hash}")


if __name__ == "__main__":
    main()
