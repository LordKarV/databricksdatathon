"""Export what the plan engine needs from derived/v1 (issue #42) into app/facts/out/facts.json.gz.

The app reads only that file at start-up (standard library, no pandas), the same pattern as the packs and the
website check. Every value is copied from derived/v1 unchanged; the only computed fields are joins (phone shared
counts, a source URL per record, prerequisites the grader did not find). When #11 publishes
derived/v2/facility_service_scores.parquet, its band / p / lo / hi are exported next to each pair and
engine.score() uses them; nothing else changes. Run from the repo root, after planner/export_v1.py (the claims it cites are copied, so route stops show quotes):
    .venv-app/bin/python app/facts/build.py
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import time
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
V1 = ROOT / "derived" / "v1"
V2 = ROOT / "derived" / "v2" / "facility_service_scores.parquet"
PLANNER = ROOT / "planner" / "out" / "planner_v1.json.gz"  # its cited claims ride along, so route stops show quotes
OUT = Path(__file__).resolve().parent / "out"
# app service id -> derived/v1 service name (cleaning/claims lexicon keys)
SERVICE_MAP = {"burn_care": "burns", "cardiac_surgery": "cardiac_surgery", "dialysis": "dialysis",
               "emergency_csection": "csection", "mri": "mri", "nicu": "nicu", "trauma_emergency": "trauma"}
V1_TO_APP = {v: k for k, v in SERVICE_MAP.items()}
MAX_EVIDENCE = 3
# Facilities the public standard expects to offer acute care (used only for the abstention "outside option").
PUBLIC_STANDARD = re.compile(r"\b(?:district hospital|sadar hospital|medical college|aiims"
                             r"|government (?:general )?hospital"
                             r"|civil hospital|general hospital|sub[- ]?divisional hospital|referral hospital)\b", re.I)


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


def facilities() -> tuple[pd.DataFrame, dict[str, int]]:
    loc = pd.read_parquet(V1 / "facility_location.parquet", columns=[
        "unique_id", "name", "address_city", "district", "state_final", "pin", "loc_lat", "loc_lon"])
    tr = pd.read_parquet(V1 / "record_trust.parquet", columns=[
        "unique_id", "display_phones", "trust_flags", "trust_reasons", "website_class", "trust_level"])
    ft = pd.read_parquet(V1 / "facility_trust.parquet", columns=[
        "unique_id", "existence_score", "location_score", "location_reason_codes", "drivers"])
    f = loc.merge(tr, on="unique_id").merge(ft, on="unique_id")
    f = f.dropna(subset=["loc_lat", "loc_lon"])
    f = f[f.trust_level != "exclude_review"].reset_index(drop=True)
    phones = [str(p[0]) if p is not None and len(p) else "" for p in f.display_phones]
    shared = Counter(str(x) for p in tr.display_phones if p is not None for x in set(p))
    f["phone_raw"] = phones
    f["phone_e164"] = [e164(p) for p in phones]
    f["phone_shared"] = [shared.get(p, 0) if p else 0 for p in phones]
    f["loc_rule"] = f.location_reason_codes.fillna("").str.split("|").map(
        lambda codes: next((c for c in codes if c.startswith("LOC_")), ""))

    urls = pd.read_parquet(V1 / "source_urls.parquet",
                           columns=["unique_id", "url", "source_class", "domain_reliability"])
    urls = urls[urls.url.str.match(r"https?://")]
    urls["k"] = (~urls.source_class.isin(["official", "official_like"])).astype(int)
    urls["depth"] = urls.url.str.replace(r"^https?://[^/]+/?", "", regex=True).str.len()
    best = urls.sort_values(["unique_id", "k", "depth", "domain_reliability"], ascending=[True, True, True, False])
    f["url"] = f.unique_id.map(best.drop_duplicates("unique_id").set_index("unique_id").url)
    f["public_standard"] = f.name.fillna("").str.contains(PUBLIC_STANDARD)
    return f, {u: i for i, u in enumerate(f.unique_id)}


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
    if V2.is_file():
        v2 = pd.read_parquet(V2, columns=["unique_id", "service_id", "band", "p", "lo", "hi"])
        v2["service"] = v2.service_id.map(lambda s: SERVICE_MAP.get(s, s))
        m = m.merge(v2.drop(columns="service_id").rename(columns={"p": "m_p", "lo": "m_lo", "hi": "m_hi",
                                                                  "band": "m_band"}), on=["unique_id", "service"],
                    how="left")
    out: dict[str, list] = {k: [] for k in SERVICE_MAP}
    cited: set[str] = set()
    for r in m.itertuples(index=False):
        ev = [c["claim_id"] for c in json.loads(r.cite_evidence or "[]")][: MAX_EVIDENCE * 3]
        cited.update(ev)
        missing = [c[4:] for c in pre_cols if isinstance(getattr(r, c), (bool,)) and getattr(r, c) is False]
        risks = [c[5:] for c in risk_cols if getattr(r, c) is True] + (["scope"] if r.scope_conflict else [])
        model = ([r.m_band, r.m_p, r.m_lo, r.m_hi] if "m_band" in m.columns and isinstance(r.m_band, str) else None)
        out[V1_TO_APP[r.service]].append([
            fidx[r.unique_id], r.grade, r.rule, r.status, round(r.score, 4), round(r.score_lo, 4),
            round(r.score_hi, 4), round(r.q_ev, 4), round(r.score_model, 4), ev, missing, risks,
            r.qty if isinstance(r.qty, str) else None, int(r.n_own_distinct), model])
    return out, cited


def planner_cited() -> set[str]:
    """Claim ids the multi-stop planner cites (#47). Build planner/export_v1.py first, or stops show ids only."""
    if not PLANNER.is_file():
        print("note: planner/out not built; route stops will carry claim ids without quotes")
        return set()
    with gzip.open(PLANNER, "rt", encoding="utf-8") as fh:
        caps = json.load(fh)["capabilities"]
    return {cid for c in caps.values() for ids in c["e"] for cid in ids}


def claims(ids: set[str]) -> dict[str, list]:
    c = pd.read_parquet(V1 / "claims.parquet", columns=["claim_id", "field", "text", "nonoffer", "attribution"])
    c = c[c.claim_id.isin(ids)]
    return {r.claim_id: [r.field, r.text, bool(r.nonoffer), r.attribution] for r in c.itertuples(index=False)}


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
    manifest = json.loads((V1 / "MANIFEST.json").read_text())
    facts = {
        "meta": {"as_of": manifest["build_date"], "source": "derived/v1",
                 "scores": "derived/v2 facility_service_scores" if V2.is_file() else
                 "interim: derived/v1 data_point_scores (likely only when verified true)",
                 "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        "rules": rules(),
        "fac": {"id": list(f.unique_id), "name": list(f.name), "city": col(f.address_city),
                "district": col(f.district), "state": col(f.state_final),
                "pin": [None if pd.isna(x) else int(x) for x in f.pin],
                "lat": col(f.loc_lat, 5), "lon": col(f.loc_lon, 5),
                "p_e": col(f.existence_score, 3), "p_l": col(f.location_score, 3), "loc_rule": list(f.loc_rule),
                "phone_e164": col(f.phone_e164), "phone_raw": list(f.phone_raw), "phone_shared": list(f.phone_shared),
                "flags": [list(x) if x is not None else [] for x in f.trust_flags],
                "reasons": [list(x) if x is not None else [] for x in f.trust_reasons],
                "website_own": list(f.website_class == "own"), "url": col(f.url),
                "public_standard": [bool(x) for x in f.public_standard]},
        "pairs": pr,
        "claims": claims(cited | planner_cited()),
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
