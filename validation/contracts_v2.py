"""Contract checks for derived/v2, the model fit (#11) output. They test the published shape, never the scores.

The contract (what the app, the packs and the notebook rely on):

derived/v2/facility_service_scores.parquet, one row per (unique_id, service_id):
  unique_id, service_id   key; service_id is one of the 36 kb/taxonomy/services.json ids
  p, lo, hi               all in [0, 1], lo <= hi. lo/hi are the Wilson 95% interval of the observed confirmed rate
                          among decided DEV pairs in p's score bin (model_card.json calibration_by_score_bin), so
                          every row of a bin carries that bin's lo/hi and p need not lie inside it
  p_location, p_exists    location and existence heads, in [0, 1]
  band                    LIKELY | CALL_FIRST | NO_SERVICE_TEXT | UNLIKELY (consumer mapping: derived/v2/README.md)
  base                    base + sum(contributions.points) / (20 / ln 2) == logit(p) to 1e-9 (MODEL_SPEC 5.4;
                          the shipped logit is logit(p), so no separate logit column)
  contributions           JSON string: list of {label, family, points, evidence_ids, card_phrase}, or the same
                          rows in a long table derived/v2/contributions.parquet keyed by (unique_id, service_id)
  operator                public | private | unknown
  model_version, as_of    non-null; one model_version, equal to model_card.json's
derived/v2/model_card.json: model_version and band thresholds under "band_thresholds" (or "thresholds"),
  for example {"likely": {"p": 0.7, "p_location": 0.7, "p_exists": 0.7}, "unlikely": {"p": 0.2}};
  flat t_L / t_U keys are read as the p thresholds. Only necessary conditions are tested (likely needs
  every likely threshold met; unlikely needs p <= the unlikely threshold unless band_reason says another rule
  decided or the row carries the c2 term, the C = 2 rule of MODEL_SPEC 3.4), because the band rule also uses
  evidence counts the table may not carry.
  A contribution is not_observable when it says so, or when every witness of its (unique_id, service, family)
  is not_observable; such a contribution must be 0.
derived/v2/witnesses.parquet: witness_id unique; observability present | absent | not_observable;
  sampled quotes are verbatim in their source; restricted lists (NABH, NMC, MoHFW trauma) appear only as
  per-facility facts.

Coverage: every usable facility (derived/v1/facility_location, 9,959) except the 12 exclude_review records
(derived/v1/record_trust) x 36 services; exclude_review records must not be scored at all.

Every check returns not_run, with the reason, while derived/v2 lacks facility_service_scores.parquet or
model_card.json, or a file cannot be read yet (still being written). Set CONTRACTS_V2_DIR to test another
directory. Self-test on a small synthetic directory:  .venv-viz/bin/python validation/contracts_v2.py --selftest
"""
from __future__ import annotations

import functools
import gzip
import json
import math
import os
import random
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path("/Users/karthikvattem/projects/datathon")
V1 = ROOT / "derived/v1"
SEED = 20261121
QUOTE_SAMPLE_PER_SOURCE = 40
BANDS = {"LIKELY", "CALL_FIRST", "NO_SERVICE_TEXT", "UNLIKELY"}
OPERATORS = {"public", "private", "unknown"}
OBSERVABILITY = {"present", "absent", "not_observable"}
TOL = 1e-9
PTS = 20.0 / math.log(2.0)  # points per logit unit on the card
# restricted licences: per-facility facts only (source_key in witnesses -> list file, name column)
RESTRICTED = {"nabh": (ROOT / "data/external/nabh_accredited/nabh_hco.parquet", "name"),
              "nmc": (ROOT / "data/external/nmc_colleges/nmc_colleges.parquet", "college_name"),
              "mohfw_tcf": (ROOT / "data/external/mohfw_trauma_196/tcf_196.csv", "name")}
RESTRICTED_MAX_SHARE = 0.5  # more than half of a list's entries in v2 counts as a wholesale copy
RESTRICTED_NAME_HITS = 20  # an id-less v2 file naming this many list entries counts as a copy
LIST_FILES = {  # source_key -> files whose text holds the quoted list entry
    "nabh": ["data/external/nabh_accredited/nabh_hco.parquet", "data/external/nabh_accredited/nabh_hco_specialty.parquet"],
    "nmc": ["data/external/nmc_colleges/nmc_colleges.parquet", "data/external/nmc_colleges/nmc_courses.parquet"],
    "eraktkosh": ["data/external/eraktkosh_blood_centres/erk_centres.parquet"],
    "laqshya": ["data/external/laqshya_master/laqshya.parquet", "data/external/laqshya_master/laqshya_facilities.parquet"],
    "mohfw_tcf": ["data/external/mohfw_trauma_196/tcf_196.csv"],
    "pmndp_goa": ["data/external/pmndp_counts_and_state_lists/goa_pmndp_centres_2020.csv"],
    "osm": ["kb/opendata/osm_health_facilities.parquet", "kb/opendata/wikidata_medical_facilities.parquet"],
    "iphs": ["kb/taxonomy/services.json"],
}
CLAIM_ID = re.compile(r"^[0-9a-f]{8}:(proc|capa|equi|desc):\d+$")


def v2_dir() -> Path:
    return Path(os.environ.get("CONTRACTS_V2_DIR", ROOT / "derived/v2"))


def result(name: str, status: str, metric, threshold, detail: str, examples=()) -> dict:
    return {"name": name, "status": status, "metric": metric, "threshold": threshold, "detail": detail,
            "examples": [str(x) for x in list(examples)[:5]]}


class NotReady(Exception):
    """derived/v2 is absent, incomplete or still being written."""


@functools.lru_cache(maxsize=None)
def scores() -> pd.DataFrame:
    d = v2_dir()
    missing = [f for f in ("facility_service_scores.parquet", "model_card.json") if not (d / f).is_file()]
    if missing:
        raise NotReady(f"{d} has no {', '.join(missing)} yet (#11 has not published)")
    try:
        return pq.read_table(d / "facility_service_scores.parquet").to_pandas()
    except Exception as e:  # a half-written file
        raise NotReady(f"facility_service_scores.parquet unreadable ({type(e).__name__}: {e}); still being written?")


@functools.lru_cache(maxsize=None)
def card() -> dict:
    scores()
    try:
        return json.loads((v2_dir() / "model_card.json").read_text())
    except ValueError as e:
        raise NotReady(f"model_card.json does not parse ({e}); still being written?")


@functools.lru_cache(maxsize=None)
def witnesses() -> pd.DataFrame:
    scores()
    p = v2_dir() / "witnesses.parquet"
    if not p.is_file():
        raise NotReady(f"{p} absent")
    try:
        return pq.read_table(p).to_pandas()
    except Exception as e:
        raise NotReady(f"witnesses.parquet unreadable ({type(e).__name__}: {e})")


@functools.lru_cache(maxsize=None)
def contributions() -> pd.DataFrame:
    """Long form: one row per (unique_id, service_id, term) with points and evidence_ids."""
    d, s = v2_dir(), scores()
    if "contributions" in s.columns:
        cols = {k: [] for k in ("unique_id", "service_id", "term", "family", "points", "evidence_ids")}
        for u, v, js in zip(s.unique_id, s.service_id, s.contributions):
            for it in json.loads(js):
                cols["unique_id"].append(u)
                cols["service_id"].append(v)
                cols["term"].append(it.get("label"))
                cols["family"].append(it.get("family"))
                cols["points"].append(float(it["points"]))
                cols["evidence_ids"].append(list(it.get("evidence_ids") or []))
        return pd.DataFrame(cols)
    p = d / "contributions.parquet"
    if not p.is_file():
        raise NotReady("no contributions column in facility_service_scores and no contributions.parquet")
    return pd.read_parquet(p)


@functools.lru_cache(maxsize=None)
def service_ids() -> frozenset:
    s = json.loads((ROOT / "kb/taxonomy/services.json").read_text())
    return frozenset(sv["id"] for cat in s["categories"] for sv in cat["services"])


@functools.lru_cache(maxsize=None)
def usable_ids() -> frozenset:
    return frozenset(pd.read_parquet(V1 / "facility_location.parquet", columns=["unique_id"]).unique_id)


@functools.lru_cache(maxsize=None)
def excluded_ids() -> frozenset:
    t = pd.read_parquet(V1 / "record_trust.parquet", columns=["unique_id", "trust_level"])
    return frozenset(t[t.trust_level == "exclude_review"].unique_id)


def guarded(fn):
    """not_run with the reason while derived/v2 is not published; never a crash or a false fail."""
    @functools.wraps(fn)
    def run() -> dict:
        try:
            return fn()
        except NotReady as e:
            return result(fn.__name__[6:], "not_run", "not run", "contract holds", f"skipped: {e}")
        except Exception as e:  # a crash is a broken contract, and must not stop the checks after it
            return result(fn.__name__[6:], "fail", f"crashed: {type(e).__name__}", "contract holds", str(e)[:300])
    return run


def need(cols: list[str]) -> list[str]:
    return [c for c in cols if c not in scores().columns]


# --------------------------------------------------------------------------------------------------- checks
@guarded
def check_v2_keys_unique() -> dict:
    s = scores()
    miss = need(["unique_id", "service_id"])
    if miss:
        return result("v2_keys_unique", "fail", f"missing {miss}", "key columns present", str(list(s.columns)))
    nul = s[["unique_id", "service_id"]].isna().any(axis=1)
    dup = s[s.duplicated(["unique_id", "service_id"], keep=False)]
    bad = int(nul.sum()) + len(dup)
    return result("v2_keys_unique", "fail" if bad else "pass",
                  f"{int(nul.sum())} null keys, {dup.drop_duplicates(['unique_id', 'service_id']).shape[0]} duplicated keys",
                  "0 and 0", f"{len(s)} rows", (dup.unique_id + ":" + dup.service_id).drop_duplicates().head(5))


@guarded
def check_v2_coverage() -> dict:
    s = scores()
    if need(["unique_id", "service_id"]):
        return result("v2_coverage", "fail", "missing key columns", "present", "")
    want_ids = usable_ids() - excluded_ids()
    got = set(zip(s.unique_id, s.service_id))
    unknown_svc = sorted(set(s.service_id) - service_ids())
    outside = sorted(set(s.unique_id) - usable_ids())
    expected = len(want_ids) * len(service_ids())
    missing = [(u, v) for u in sorted(want_ids) for v in sorted(service_ids()) if (u, v) not in got]
    bad = bool(unknown_svc or outside or missing)
    return result("v2_coverage", "fail" if bad else "pass",
                  f"{expected - len(missing)}/{expected} pairs; {len(unknown_svc)} unknown service ids; "
                  f"{len(outside)} ids outside the usable set", f"{len(want_ids)} facilities x {len(service_ids())} services",
                  f"usable {len(usable_ids())} minus {len(excluded_ids())} exclude_review",
                  [f"unknown service {x}" for x in unknown_svc[:2]] + [f"not usable {x}" for x in outside[:2]]
                  + [f"missing {u}:{v}" for u, v in missing[:3]])


@guarded
def check_v2_excluded_not_scored() -> dict:
    s = scores()
    hit = sorted(set(s.unique_id) & excluded_ids())
    return result("v2_excluded_not_scored", "fail" if hit else "pass", f"{len(hit)} of {len(excluded_ids())} scored",
                  "0", "exclude_review (veterinary) records must not be scored (validation INT-01)", hit)


@guarded
def check_v2_probabilities() -> dict:
    s = scores()
    cols = ["p", "lo", "hi", "p_location", "p_exists"]
    miss = need(cols)
    if miss:
        return result("v2_probabilities", "fail", f"missing {miss}", "all present", str(list(s.columns)))
    bad, ex = {}, []
    for c in cols:
        m = s[c].isna() | (s[c] < 0) | (s[c] > 1)
        if m.any():
            bad[c] = int(m.sum())
            ex += [f"{r.unique_id}:{r.service_id} {c}={getattr(r, c)}" for r in s[m].head(2).itertuples()]
    order = s.lo > s.hi + TOL
    if order.any():
        bad["lo<=hi"] = int(order.sum())
        ex += [f"{r.unique_id}:{r.service_id} lo={r.lo} hi={r.hi}" for r in s[order].head(2).itertuples()]
    bins = sorted(card().get("calibration_by_score_bin") or [], key=lambda r: r["p_min"])
    if not bins:
        bad["no calibration_by_score_bin in model_card.json"] = len(s)
    else:  # bin b holds p_min[b] <= p < p_min[b + 1], as the export assigns it
        b = np.digitize(s.p.to_numpy(), [r["p_min"] for r in bins] + [np.inf]) - 1
        w = np.array([r["wilson95"] for r in bins], float)[b.clip(0, len(bins) - 1)]
        off = (b < 0) | (b >= len(bins)) | ~(np.abs(s.lo.to_numpy() - w[:, 0]) <= TOL) | ~(np.abs(s.hi.to_numpy() - w[:, 1]) <= TOL)
        if off.any():
            bad["lo/hi != own score bin"] = int(off.sum())
            ex += [f"{r.unique_id}:{r.service_id} p={r.p} lo={r.lo} hi={r.hi}" for r in s[off].head(2).itertuples()]
    return result("v2_probabilities", "fail" if bad else "pass", f"{sum(bad.values())} bad cells {bad}",
                  "0 null or outside [0,1]; lo <= hi; lo/hi = the row's score-bin Wilson 95% in model_card.json",
                  f"{len(s)} rows x {cols}; {len(bins)} score bins; p outside [lo, hi] on "
                  f"{int(((s.p < s.lo) | (s.p > s.hi)).sum())} rows (allowed: lo/hi describe the bin)", ex)


@guarded
def check_v2_logit_identity() -> dict:
    s = scores()
    miss = need(["base", "p"])
    if miss:
        return result("v2_logit_identity", "fail", f"missing {miss}", "present", str(list(s.columns)))
    c = contributions()
    if "points" not in c.columns:
        return result("v2_logit_identity", "fail", "contributions have no points", "points present", str(list(c.columns)))
    tot = c.groupby(["unique_id", "service_id"]).points.sum().rename("sum_points")
    m = s[["unique_id", "service_id", "base", "p"]].merge(tot.reset_index(), how="left", on=["unique_id", "service_id"])
    m["sum_points"] = m.sum_points.fillna(0.0)
    m["logit"] = np.log(m.p) - np.log1p(-m.p)
    err = (m.base + m.sum_points / PTS - m.logit).abs()
    off = m[~(err <= TOL)]
    return result("v2_logit_identity", "fail" if len(off) else "pass",
                  f"{len(off)} of {len(m)} rows off by > {TOL}; max {err.max():.2e}",
                  f"|base + sum(points) / (20 / ln 2) - logit(p)| <= {TOL}", f"{len(c)} contribution rows",
                  [f"{r.unique_id}:{r.service_id} base {r.base} + {r.sum_points} pts != logit {r.logit}"
                   for r in off.head(5).itertuples()])


def _id_lists(c: pd.DataFrame) -> pd.Series | None:
    for col in ("evidence_ids", "cited_ids", "witness_ids", "cited_atom_ids"):
        if col in c.columns:
            return c[col]
    return None


@functools.lru_cache(maxsize=None)
def known_ids() -> tuple[frozenset, frozenset, dict]:
    claims = frozenset(pd.read_parquet(V1 / "claims.parquet", columns=["claim_id"]).claim_id)
    w = witnesses()
    wit = frozenset(w.witness_id) | frozenset(w.evidence_id.dropna())
    atoms = {}
    p = v2_dir() / "claim_atoms.parquet"
    if p.is_file():
        a = pd.read_parquet(p, columns=["atom_id", "claim_id"])
        atoms = dict(zip(a.atom_id, a.claim_id))
    return claims, wit, atoms


@guarded
def check_v2_evidence_ids_resolve() -> dict:
    c = contributions()
    ids = _id_lists(c)
    if ids is None:
        return result("v2_evidence_ids_resolve", "fail", "no evidence id column", "evidence_ids in contributions",
                      str(list(c.columns)))
    claims, wit, atoms = known_ids()
    flat = pd.Series([x for v in ids.dropna() for x in (list(v) if not isinstance(v, str) else [v])], dtype=object)
    uniq = set(flat)
    bad = sorted(x for x in uniq if x not in claims and x not in wit and atoms.get(x) not in claims)
    return result("v2_evidence_ids_resolve", "fail" if bad else "pass", f"{len(bad)} of {len(uniq)} distinct ids unresolved",
                  "0", f"{len(flat)} citations; resolve to derived/v1 claims.claim_id, a witnesses witness_id or "
                  "evidence_id, or a claim_atoms atom_id whose claim_id is in claims", bad)


def _thresholds() -> tuple[dict, dict] | None:
    t = card().get("band_thresholds") or card().get("thresholds")
    if not isinstance(t, dict):
        return None
    def side(key: str, flat: tuple[str, ...]) -> dict:
        v = t.get(key)
        if isinstance(v, dict):
            return {k: float(x) for k, x in v.items() if isinstance(x, (int, float))}
        for k in (key, *flat):
            if isinstance(t.get(k), (int, float)):
                return {"p": float(t[k])}
        return {}
    lik, unl = side("likely", ("t_L", "t_likely")), side("unlikely", ("t_U", "t_unlikely"))
    return (lik, unl) if lik or unl else None


@guarded
def check_v2_bands() -> dict:
    s = scores()
    if need(["band"]):
        return result("v2_bands", "fail", "no band column", "present", "")
    unknown = sorted(set(s.band.dropna()) - BANDS) + (["<null>"] if s.band.isna().any() else [])
    th = _thresholds()
    if th is None:
        return result("v2_bands", "fail", "model_card.json has no band thresholds", "band_thresholds present",
                      f"keys: {sorted(card())}; unknown bands {unknown}")
    lik, unl = th
    bad, ex = 0, []
    for col, t in lik.items():
        if col not in s.columns:
            ex.append(f"threshold column {col} not in table")
            continue
        m = (s.band == "LIKELY") & ~(s[col] >= t - TOL)
        bad += int(m.sum())
        ex += [f"LIKELY with {col}={getattr(r, col)} < {t}: {r.unique_id}:{r.service_id}" for r in s[m].head(2).itertuples()]
    n_c2 = 0
    if "p" in unl and "p" in s.columns:
        m = (s.band == "UNLIKELY") & ~(s.p <= unl["p"] + TOL)
        if "band_reason" in s.columns:  # another documented rule (e.g. counter-evidence) may decide unlikely
            m &= s.band_reason.fillna("").str.contains(r"\bp\b|p_s|threshold", case=False, regex=True) | s.band_reason.isna()
        if m.any():  # the C = 2 rule (MODEL_SPEC 3.4) shows as the c2 term in the row's contributions
            c = contributions()
            c2 = pd.MultiIndex.from_frame(c.loc[c.term == "c2", ["unique_id", "service_id"]])
            by_c2 = m & pd.MultiIndex.from_frame(s[["unique_id", "service_id"]]).isin(c2)
            n_c2, m = int(by_c2.sum()), m & ~by_c2
        bad += int(m.sum())
        ex += [f"UNLIKELY with p={r.p} > {unl['p']}: {r.unique_id}:{r.service_id}" for r in s[m].head(2).itertuples()]
    st = "fail" if bad or unknown else "pass"
    return result("v2_bands", st, f"{bad} rows break a threshold; unknown bands {unknown}",
                  f"LIKELY: all of {lik} met; UNLIKELY: p <= {unl.get('p')} or the c2 term",
                  f"band counts {s.band.value_counts(dropna=False).to_dict()}; {n_c2} UNLIKELY by the c2 rule; "
                  "necessary conditions only", ex)


@guarded
def check_v2_not_observable_zero() -> dict:
    c = contributions()
    w = witnesses()
    n_nob = "-"
    if "observability" in c.columns:
        m = c.observability == "not_observable"
    elif "family" in c.columns:
        ws = w[w.service != "*"]
        nob = ws.observability.eq("not_observable").groupby([ws.unique_id, ws.service, ws.family]).all()
        n_nob = int(nob.sum())
        m = pd.MultiIndex.from_frame(c[["unique_id", "service_id", "family"]]).isin(nob.index[nob.to_numpy()])
    else:
        return result("v2_not_observable_zero", "fail", "no observability or family", "present", str(list(c.columns)))
    hit = c[m & (c.points != 0)]
    unk = sorted(set(w.observability.dropna()) - OBSERVABILITY)
    return result("v2_not_observable_zero", "fail" if len(hit) or unk else "pass",
                  f"{len(hit)} of {int(m.sum())} not_observable contributions are non-zero; unknown observability {unk}",
                  "exactly 0", "a contribution is not_observable when it says so, or when every witness of its "
                  f"(unique_id, service, family) is; {n_nob} not_observable triples in witnesses",
                  [f"{r.unique_id}:{r.service_id} {getattr(r, 'term', '')} points={r.points}" for r in hit.head(5).itertuples()])


@guarded
def check_v2_operator() -> dict:
    s = scores()
    if need(["operator"]):
        return result("v2_operator", "fail", "no operator column", "present", "")
    bad = s.operator.isna() | ~s.operator.isin(OPERATORS)
    return result("v2_operator", "fail" if bad.any() else "pass", f"{int(bad.sum())} rows outside {sorted(OPERATORS)}", "0",
                  f"values {s.operator.value_counts(dropna=False).to_dict()}", s.operator[bad].astype(str).unique()[:5])


@guarded
def check_v2_model_version() -> dict:
    s = scores()
    miss = need(["model_version", "as_of"])
    if miss:
        return result("v2_model_version", "fail", f"missing {miss}", "present", str(list(s.columns)))
    vers = sorted(set(s.model_version.dropna().astype(str)))
    want = card().get("model_version")
    probs = []
    if s.model_version.isna().any() or s.as_of.isna().any():
        probs.append(f"{int(s.model_version.isna().sum())} null model_version, {int(s.as_of.isna().sum())} null as_of")
    if len(vers) != 1:
        probs.append(f"{len(vers)} distinct model_version values")
    if not want:
        probs.append("model_card.json has no model_version")
    elif vers and str(want) not in vers:
        probs.append(f"model_card {want} not in table {vers[:3]}")
    return result("v2_model_version", "fail" if probs else "pass", "; ".join(probs) or f"one version {vers[0]}",
                  "one non-null model_version equal to model_card.json", f"as_of max {s.as_of.max()}", probs)


# ---------------------------------------------------------------------------------------- witness quotes
@functools.lru_cache(maxsize=None)
def _claim_text() -> dict:
    c = pd.read_parquet(V1 / "claims.parquet", columns=["claim_id", "text"])
    return dict(zip(c.claim_id, c.text))


@functools.lru_cache(maxsize=None)
def _raw_text() -> dict:
    """unique_id -> every string field of the raw record, joined (the source of record: and :spec: quotes)."""
    raw = pd.read_parquet(ROOT / "data/raw/facilities.parquet")
    raw = raw.drop_duplicates("unique_id")
    return dict(zip(raw.unique_id, _join_rows(raw)))


def _join_rows(d: pd.DataFrame) -> pd.Series:
    """Each row's text cells joined by newlines (pandas 3 keeps NaN through astype(str), so fill first)."""
    t = d.select_dtypes(include=["object", "string"]).fillna("").astype(str)
    return t.agg("\n".join, axis=1) if len(t.columns) else pd.Series([""] * len(d), index=d.index)


@functools.lru_cache(maxsize=None)
def _file_text(rel: str) -> str:
    p = ROOT / rel
    if p.suffix == ".json":
        return p.read_text()
    d = pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p, dtype=str)
    return "\n".join(_join_rows(d))


@functools.lru_cache(maxsize=4096)
def _page(rel: str) -> dict:
    with gzip.open(ROOT / rel, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _haystack(r) -> tuple[str, str | None]:
    """(kind, text the quote must be a substring of), chosen from the witness's evidence id or source key."""
    eid, key = str(r.evidence_id or ""), str(r.source_key or "")
    if CLAIM_ID.match(eid) and eid in _claim_text():
        return "claims", _claim_text()[eid]
    if eid.startswith("data/crawl/pages/"):
        o = _page(eid)
        f = r.field if isinstance(r.field, str) and r.field in o else None
        return "crawl page", o[f] if f else "\n".join(str(v) for v in o.values() if isinstance(v, str))
    base = key.split(":")[0].replace("iphs_reading", "iphs")
    if base in LIST_FILES or eid.split(":")[0] in ("osm", "wikidata"):
        files = LIST_FILES["osm" if eid.split(":")[0] in ("osm", "wikidata") else base]
        return f"list {base}", "\n".join(_file_text(f) for f in files)
    return "raw record", _raw_text().get(r.unique_id)


@guarded
def check_v2_witness_quotes() -> dict:
    w = witnesses()
    unique = w.witness_id.is_unique
    q = w[w.quote.notna() & (w.quote.astype(str) != "")]
    rng = random.Random(SEED)
    rows = []
    for src, g in sorted(q.groupby(q.source.fillna("<none>")), key=lambda x: x[0]):
        idx = sorted(g.index)
        rows += rng.sample(idx, min(QUOTE_SAMPLE_PER_SOURCE, len(idx)))
    sample = q.loc[rows]
    miss, ws_only, k = [], 0, 0
    for r in sample.itertuples():
        kind, hay = _haystack(r)
        if hay is not None and r.quote in hay:
            k += 1
            continue
        if hay is not None and " ".join(r.quote.split()) in " ".join(hay.split()):
            ws_only += 1
        miss.append(f"{r.witness_id} [{kind}] {r.evidence_id}: {r.quote[:80]!r}")
    n = len(sample)
    lo, hi = wilson(k, n)
    strict = [m for m in miss if "[list " not in m]  # claims, crawl pages and raw records are copied verbatim
    st = "fail" if not unique or strict else "warn" if miss else "pass"
    return result("v2_witness_quotes", st, f"{k}/{n} verbatim (Wilson 95% {lo:.3f}-{hi:.3f})",
                  "every sampled quote verbatim; fail on a miss in claims, crawl pages or raw records (outside "
                  "lists may reformat an entry: warn), or if witness_id is not unique",
                  f"seed {SEED}, up to {QUOTE_SAMPLE_PER_SOURCE} per source over {q.source.nunique()} sources; "
                  f"{ws_only} misses differ only in whitespace; witness_id unique: {unique}", miss)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def _norm(x: str) -> str:
    return re.sub(r"\s+", " ", str(x)).strip().lower()


@guarded
def check_v2_restricted_lists() -> dict:
    w = witnesses()
    probs, notes = [], []
    for key, (path, col) in RESTRICTED.items():
        lst = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path, dtype=str)
        rows = w[w.source_key.astype(str).str.split(":").str[0] == key]
        orphan = int((~rows.unique_id.isin(usable_ids())).sum())
        share = rows.evidence_id.nunique() / max(len(lst), 1)
        notes.append(f"{key}: {len(rows)} rows, {rows.evidence_id.nunique()} entries of {len(lst)} ({share:.1%}), {orphan} not on a usable facility")
        if orphan:
            probs.append(f"{key}: {orphan} witness rows not tied to a usable facility")
        if share > RESTRICTED_MAX_SHARE:
            probs.append(f"{key}: {share:.1%} of the list present")
        names = {_norm(x) for x in lst[col].dropna() if len(_norm(x)) >= 8}
        for f in sorted(v2_dir().glob("*.parquet")):
            if f.name == "witnesses.parquet":
                continue
            schema = pq.read_schema(f)
            strcols = [n for n, t in zip(schema.names, schema.types) if "string" in str(t)]
            d = pd.read_parquet(f, columns=strcols + (["unique_id"] if "unique_id" in schema.names and "unique_id" not in strcols else []))
            if "unique_id" in d.columns:
                d = d[~d.unique_id.isin(usable_ids())]
            hits = {v for c in strcols if c != "unique_id" for v in map(_norm, d[c].dropna().unique()) if v in names}
            if len(hits) >= RESTRICTED_NAME_HITS:
                probs.append(f"{f.name}: {len(hits)} {key} entry names outside per-facility rows")
    return result("v2_restricted_lists", "fail" if probs else "pass", f"{len(probs)} problems", "per-facility facts only",
                  "; ".join(notes), probs)


CHECKS = [check_v2_keys_unique, check_v2_coverage, check_v2_excluded_not_scored, check_v2_probabilities,
          check_v2_logit_identity, check_v2_evidence_ids_resolve, check_v2_bands, check_v2_not_observable_zero,
          check_v2_operator, check_v2_model_version, check_v2_witness_quotes, check_v2_restricted_lists]


# --------------------------------------------------------------------------------------------- self-test
def selftest() -> None:
    """Synthetic derived/v2 in a temp dir: one clean pair, one broken in each way a check should catch."""
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="contracts_v2_"))
    os.environ["CONTRACTS_V2_DIR"] = str(tmp)
    for f in (scores, card, witnesses, contributions, known_ids):
        f.cache_clear()
    assert check_v2_keys_unique()["status"] == "not_run", "absent v2 must skip"
    c = pd.read_parquet(V1 / "claims.parquet", columns=["claim_id", "unique_id", "text"]).iloc[:2]
    uid, cid = c.unique_id.iloc[0], c.claim_id.iloc[0]
    wit = pd.DataFrame({"unique_id": [uid] * 3, "witness_id": ["w1", "w2", "w3"], "evidence_id": [cid, None, None],
                        "service": ["dialysis", "dialysis", "mri"], "family": ["T", "R", "R"],
                        "observability": ["present", "not_observable", "not_observable"],
                        "quote": [c.text.iloc[0], None, None], "source": ["provided dataset text", None, None],
                        "source_key": ["vf_text", None, None], "field": [None, None, None]})
    wit.to_parquet(tmp / "witnesses.parquet")
    item = lambda lab, fam, pts, ids: {"label": lab, "family": fam, "points": pts, "evidence_ids": ids}  # noqa: E731
    good = {"unique_id": uid, "service_id": "dialysis", "p": 0.5, "lo": 0.4, "hi": 0.6, "p_location": 0.9, "p_exists": 0.9,
            "band": "CALL_FIRST", "base": -1.0, "operator": "private", "model_version": "m1", "as_of": "2026-11-22",
            "contributions": json.dumps([item("t1", "T", PTS, [cid]), item("r_reader", "R", 0.0, ["w2"])])}
    # bad: lo/hi of the wrong bin (p > hi alone is allowed), points do not add up, an unresolved id, a non-zero
    # not_observable term, LIKELY with p_location below the gate, an unknown operator
    bad = {**good, "service_id": "mri", "p": 0.95, "hi": 0.9, "band": "LIKELY", "p_location": 0.5, "operator": "ngo",
           "contributions": json.dumps([item("t1", "T", 0.5, ["nope:1"]), item("r_reader", "R", 0.3, ["w2"])])}
    pd.DataFrame([good, bad, good]).to_parquet(tmp / "facility_service_scores.parquet")
    (tmp / "model_card.json").write_text(json.dumps({"model_version": "m1", "band_thresholds": {
        "likely": {"p": 0.7, "p_location": 0.7}, "unlikely": {"p": 0.2}}, "calibration_by_score_bin": [
        {"p_min": 0.0, "p_max": 0.6, "wilson95": [0.4, 0.6]}, {"p_min": 0.6, "p_max": 1.0, "wilson95": [0.8, 0.9]}]}))
    for f in (scores, card, witnesses, contributions, known_ids):
        f.cache_clear()
    got = {f.__name__[6:]: f()["status"] for f in CHECKS}
    want = {"v2_keys_unique": "fail", "v2_coverage": "fail", "v2_probabilities": "fail", "v2_logit_identity": "fail",
            "v2_evidence_ids_resolve": "fail", "v2_bands": "fail", "v2_not_observable_zero": "fail", "v2_operator": "fail",
            "v2_model_version": "pass", "v2_witness_quotes": "pass", "v2_excluded_not_scored": "pass"}
    for k, v in want.items():
        assert got[k] == v, f"{k}: got {got[k]}, want {v}"
    print("selftest ok:", got)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        for f in CHECKS:
            r = f()
            print(f"{r['status']:7} {r['name']}: {r['metric']} | {r['detail'][:160]}")
