"""Audit checks for claims, attribution and taxonomy mapping (validation/claims).

Every check_<name>() returns dict(name, status pass|warn|fail, metric, threshold, detail, examples).
Read-only on every data layer. Run all: /Users/karthikvattem/projects/datathon/.venv-viz/bin/python checks.py
Outputs (per-check JSON and the full result list) go to validation/claims/out/.

The raw-side reconstruction is written independently of cleaning/claims/build_claims.py: Python json and re instead
of DuckDB from_json / regexp, so a bug in either shows up as a disagreement. Hand-read samples are drawn by
samples.py (fixed seeds); my verdicts live in labels/*.csv and are scored here.
"""
from __future__ import annotations

import functools
import hashlib
import json
import math
import os
import re
import sys

import pandas as pd

ROOT = "/Users/karthikvattem/projects/datathon"
D = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(D, "out")
LAB = os.path.join(D, "labels")
RAW = f"{ROOT}/data/raw/facilities.parquet"
V1 = f"{ROOT}/derived/v1"
CLAIMS = f"{V1}/claims.parquet"
TAX = f"{ROOT}/kb/taxonomy"
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
ARRAY_FIELDS = ("procedure", "equipment", "capability")
RE2_SPACE = "\t\n\f\r "  # DuckDB/RE2 \s; Python's \s is wider, so it is spelled out
SENT_SPLIT = re.compile(r"([.!?])[\t\n\f\r ]+")


# ---------------------------------------------------------------- helpers

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (round(max(0.0, c - h), 3), round(min(1.0, c + h), 3))


def res(name, status, metric, threshold, detail, examples=None):
    return dict(name=name, status=status, metric=metric, threshold=threshold, detail=detail, examples=list(examples or [])[:5])


@functools.lru_cache(None)
def raw() -> pd.DataFrame:
    return pd.read_parquet(RAW)


@functools.lru_cache(None)
def claims() -> pd.DataFrame:
    return pd.read_parquet(CLAIMS)


@functools.lru_cache(None)
def base() -> pd.DataFrame:
    """kie rows with a UUID id, first copy of each id (the same row set build_claims.py keeps)."""
    r = raw()
    b = r[r.unique_id.astype(str).str.match(UUID.pattern) & (r.source == "kie")]
    return b.drop_duplicates("unique_id", keep="first")


def _items(j):
    """Decoded JSON array items, or None when the value is not a JSON array."""
    if j is None or (isinstance(j, float) and math.isnan(j)):
        return None
    try:
        v = json.loads(j)
    except (ValueError, TypeError):
        return None
    return v if isinstance(v, list) else None


@functools.lru_cache(None)
def expected() -> pd.DataFrame:
    """Independent reconstruction: one row per non-empty raw item / description sentence.
    raw_pos = position in the raw array (or sentence split), idx = rank among the kept items (build_claims semantics)."""
    rows = []
    for uid, *vals in base()[["unique_id", *ARRAY_FIELDS, "description"]].itertuples(index=False):
        for f, j in zip(ARRAY_FIELDS, vals[:3]):
            it = _items(j)
            if it is None:
                continue
            k = 0
            for pos, x in enumerate(it):
                if x is None:
                    continue
                s = x if isinstance(x, str) else json.dumps(x)
                t = s.strip(RE2_SPACE)
                if t:
                    rows.append((uid, f, k, pos, t, s))
                    k += 1
        d = vals[3]
        if isinstance(d, str) and d != "null":
            k = 0
            for pos, s in enumerate(SENT_SPLIT.sub("\\1\x1f", d).split("\x1f")):
                t = s.strip(RE2_SPACE)
                if t:
                    rows.append((uid, "description", k, pos, t, s))
                    k += 1
    return pd.DataFrame(rows, columns=["unique_id", "field", "idx", "raw_pos", "text", "raw_item"])


@functools.lru_cache(None)
def joined() -> pd.DataFrame:
    c = claims()[["claim_id", "unique_id", "field", "idx", "text"]]
    return c.merge(expected(), on=["unique_id", "field", "idx"], how="outer", suffixes=("", "_raw"), indicator=True)


# ---------------------------------------------------------------- exhaustive: claims vs raw

def check_claims_file_is_cleaning_copy():
    a = hashlib.sha256(open(CLAIMS, "rb").read()).hexdigest()
    b = hashlib.sha256(open(f"{ROOT}/cleaning/claims/out/claims.parquet", "rb").read()).hexdigest()
    man = json.load(open(f"{V1}/MANIFEST.json"))
    rows = man["tables"]["claims.parquet"]["rows"]
    ok = a == b and rows == len(claims())
    return res("claims_file_is_cleaning_copy", "pass" if ok else "fail", f"sha256 equal={a == b}; manifest rows {rows} vs {len(claims())}",
               "byte copy and row count equal", "derived/v1/claims.parquet must be the cleaning/claims output it says it copies", [a[:16]])


def check_claims_verbatim_at_index():
    """Every claim text equals the trimmed raw item at (unique_id, field, idx), idx counted over non-empty items."""
    j = joined()
    c = j[j._merge != "right_only"]
    no_raw = c[c._merge == "left_only"]
    mism = c[(c._merge == "both") & (c.text != c.text_raw)]
    bad = len(no_raw) + len(mism)
    ex = [f"{r.claim_id}: claims={r.text[:60]!r} raw={str(r.text_raw)[:60]!r}" for r in mism.head(3).itertuples()]
    ex += [f"{r.claim_id}: no raw item at this index" for r in no_raw.head(2).itertuples()]
    return res("claims_verbatim_at_index", "pass" if bad == 0 else "fail", f"{bad} / {len(c)} claims not verbatim at stated field and index",
               "0", f"no raw item: {len(no_raw)}; text differs: {len(mism)}", ex)


def check_claims_substring_of_raw_field():
    """Weaker, parser-free form: the claim text occurs inside the decoded raw field value (array items joined, or description)."""
    b = base().set_index("unique_id")
    miss = []
    for r in claims()[["claim_id", "unique_id", "field", "text"]].itertuples(index=False):
        v = b.at[r.unique_id, r.field]
        if r.field != "description":
            it = _items(v) or []
            v = "\x1e".join(x if isinstance(x, str) else json.dumps(x) for x in it if x is not None)
        if not isinstance(v, str) or r.text not in v:
            miss.append(r.claim_id)
    return res("claims_substring_of_raw_field", "pass" if not miss else "fail", f"{len(miss)} / {len(claims())}", "0",
               "claim text found verbatim inside its stated raw field of the same record", miss)


def check_raw_items_represented_once():
    """Every non-empty raw item / sentence of the kept records appears exactly once in claims (misses and extras)."""
    j = joined()
    misses = j[j._merge == "right_only"]
    extras = j[j._merge == "left_only"]
    dup_keys = int(claims().duplicated(["unique_id", "field", "idx"]).sum())
    n_exp = int((j._merge != "left_only").sum())
    bad = len(misses) + len(extras) + dup_keys
    ex = [f"miss {r.unique_id[:8]}:{r.field}:{int(r.idx)} {r.text_raw[:60]!r}" for r in misses.head(3).itertuples()]
    ex += [f"extra {r.claim_id}" for r in extras.head(2).itertuples()]
    return res("raw_items_represented_once", "pass" if bad == 0 else "fail",
               f"misses {len(misses)}, extras {len(extras)}, duplicate keys {dup_keys}; expected {n_exp}, claims {len(claims())}", "0",
               "independent Python reconstruction over the 9,959 kept records (kie, UUID id, first copy)", ex)


def check_idx_equals_raw_position():
    """claim_id idx is the rank among non-empty items; where the raw array holds empty or null items the idx is not the
    raw position, so 'field[idx]' on the raw JSON points at a different item."""
    j = joined()
    b = j[j._merge == "both"]
    off = b[b.idx != b.raw_pos]
    recs = off.unique_id.nunique()
    ex = [f"{r.claim_id}: raw position {int(r.raw_pos)}" for r in off.drop_duplicates("unique_id").head(5).itertuples()]
    by = off.field.value_counts().to_dict()
    return res("idx_equals_raw_position", "pass" if len(off) == 0 else "warn", f"{len(off)} / {len(b)} claims in {recs} records",
               "0 (documentation issue: idx is the rank among non-empty items)", f"by field {by}", ex)


def check_kept_text_untrimmed_unicode_space():
    """Texts that still start or end with a Unicode space (NBSP, zero-width, ideographic) after the RE2 trim."""
    t = claims().text
    m = t.str.match(r"^[\s\u200b\ufeff]") | t.str.contains(r"[\s\u200b\ufeff]$", regex=True)
    ex = claims()[m].claim_id.head(5).tolist()
    return res("kept_text_untrimmed_unicode_space", "pass" if m.sum() == 0 else "warn", f"{int(m.sum())} / {len(t)}", "0",
               "cosmetic: such texts never equal a Python .strip() of the same item", ex)


def check_split_records_dropped():
    """The raw table carries records broken by an embedded newline in description: the head row keeps the UUID but its
    source is null, the tail becomes fragment rows with shifted columns. build_claims keeps only source = 'kie', so these
    facilities and their claim sentences are absent. The live Marketplace table has the same 10,088 rows (sql.sh)."""
    r = raw()
    ok = r.unique_id.astype(str).str.match(UUID.pattern)
    heads = r[ok & (r.source != "kie")]
    frags = r[~ok]
    n_items = 0
    for row in frags.itertuples(index=False):
        for v in row:
            it = _items(v) if isinstance(v, str) and v.startswith("[") else None
            if it and any(isinstance(x, str) and " " in x for x in it):
                n_items += sum(1 for x in it if isinstance(x, str) and x.strip())
    return res("split_records_dropped", "warn" if len(heads) else "pass",
               f"{len(heads)} facility records dropped; {len(frags)} fragment rows; about {n_items} sentence items lost",
               "0 records lost", "upstream CSV breakage carried into the Marketplace table; recoverable by stitching fragments",
               heads.unique_id.head(5).tolist())


def check_duplicate_uid_rows_identical():
    r = raw()
    k = r[r.unique_id.astype(str).str.match(UUID.pattern) & (r.source == "kie")]
    d = k[k.unique_id.duplicated(keep=False)]
    differ = [u for u, g in d.groupby("unique_id") if len(g.astype(str).drop_duplicates()) > 1]
    n = d.unique_id.nunique()
    return res("duplicate_uid_rows_identical", "pass" if not differ else "fail", f"{len(differ)} of {n} duplicated ids differ",
               "0", f"{len(d) - n} extra rows dropped by first-row dedup; dedup order is arbitrary, so copies must be identical",
               differ or d.unique_id.drop_duplicates().head(5).tolist())


def check_claim_id_unique_and_format():
    c = claims()
    fmt = c.unique_id.str[:8] + ":" + c.field.str[:4] + ":" + c.idx.astype(str)
    bad_fmt = int((fmt != c.claim_id).sum())
    dup = int(c.claim_id.duplicated().sum())
    u = pd.Series(base().unique_id.unique())
    coll = u.str[:8][u.str[:8].duplicated(keep=False)]
    ok = bad_fmt == 0 and dup == 0 and coll.empty
    return res("claim_id_unique_and_format", "pass" if ok else "fail",
               f"format mismatches {bad_fmt}, duplicate claim_ids {dup}, uid8 prefix collisions {coll.nunique()}", "0",
               "claim_id = uid8:field4:idx must be unique; an 8-hex prefix collision would merge two records' ids", coll.head(5).tolist())


def check_dup_in_record_recomputed():
    c = claims().copy()
    c["norm"] = c.text.str.lower().str.replace(r"[^a-z0-9]+", " ", regex=True).str.strip()
    c["fo"] = c.field.map({"procedure": 0, "capability": 1, "equipment": 2, "description": 3})
    c = c.sort_values(["unique_id", "fo", "idx"])
    exp = c.duplicated(["unique_id", "norm"])
    bad = c[exp != c.dup_in_record]
    return res("dup_in_record_recomputed", "pass" if bad.empty else "fail", f"{len(bad)} / {len(c)} disagree; {int(exp.sum())} echoes",
               "0", "first copy (procedure, capability, equipment, description order) kept, later ones flagged", bad.claim_id.head(5).tolist())


def check_description_split_fragments():
    """Description sentences split after an abbreviation ('Dr.', 'No.', 'Pvt.'), leaving a fragment that is not a sentence."""
    c = claims()
    d = c[c.field == "description"]
    abbr = d.text.str.contains(r"(?:^|\s)(?:Dr|Mr|Mrs|Ms|St|No|Pvt|Ltd|Co|Sr|Jr|Prof|Rd|Hon|Smt|Shri|Sri|Govt|Dept|Vol|vs|etc|e\.g|i\.e|U\.S|M\.D|B\.Sc|M\.S)\.$",
                               regex=True)
    short = d.text.str.len() <= 3
    bad = d[abbr | short]
    return res("description_split_fragments", "pass" if len(bad) < 0.01 * len(d) else "warn",
               f"{len(bad)} / {len(d)} description sentences end at an abbreviation or are 3 chars or fewer",
               "< 1% of description sentences", f"abbreviation ends {int(abbr.sum())}, very short {int(short.sum())}; split rule ([.!?])\\s+",
               [f"{r.claim_id}: {r.text[-50:]!r}" for r in bad.head(5).itertuples()])


def check_array_truncated_at_50():
    """Upstream cap (REPORT claims-07): arrays of exactly 50 items are probably cut, so absence of a service is not evidence."""
    b = base()
    n = {f: int(b[f].map(lambda j: len(_items(j) or []) == 50).sum()) for f in ARRAY_FIELDS}
    recs = int(b[list(ARRAY_FIELDS)].apply(lambda r: any(len(_items(j) or []) == 50 for j in r), axis=1).sum())
    return res("array_truncated_at_50", "warn" if recs else "pass", f"{recs} / {len(b)} records have a 50-item array", "informational",
               f"per field {n}; not a claims bug, but 'not found' must never read as 'not offered'")


# ---------------------------------------------------------------- exhaustive: attribution and downstream consistency

def check_attribution_columns_consistent():
    """own_anchored needs a self-name hit; unanchored must have no self-name, foreign or sibling name."""
    c = claims()
    own_bad = c[(c.attribution == "own_anchored") & (c.self_names == "")]
    un_bad = c[(c.attribution == "unanchored") & (c.self_names != "")]
    labels_ok = set(c.attribution.unique()) <= {"own_anchored", "unanchored", "ambiguous", "other_facility"}
    bad = len(own_bad) + len(un_bad)
    un_with_foreign = int(((c.attribution == "unanchored") & ((c.foreign_names != "") | (c.sibling_names != ""))).sum())
    return res("attribution_columns_consistent", "pass" if bad == 0 and labels_ok else "fail",
               f"{bad} / {len(c)} labels contradict their detector columns", "0",
               f"own without self name {len(own_bad)}; unanchored with self name {len(un_bad)}; unanchored that still list a foreign or "
               f"sibling name {un_with_foreign} (detector put them in a credential/relation context); label set ok={labels_ok}",
               (own_bad.claim_id.head(3).tolist() + un_bad.claim_id.head(2).tolist()))


def check_dps_sentence_rows_match_claims():
    """data_point_scores 'sent:' rows: one per claim, original_value = text, same field and attribution, rule follows the label."""
    p = pd.read_parquet(f"{V1}/data_point_scores.parquet", columns=["dp_id", "dp_type", "claim_id", "unique_id", "field", "original_value",
                                                                     "attribution", "rule"])
    s = p[p.dp_type == "claim_attribution"]
    c = claims()[["claim_id", "unique_id", "field", "text", "attribution"]]
    m = c.merge(s, on="claim_id", how="outer", suffixes=("", "_dp"), indicator=True)
    rule = {"other_facility": "ATTR_OTHER_FACILITY", "ambiguous": "ATTR_AMBIGUOUS", "own_anchored": "ATTR_UNFLAGGED", "unanchored": "ATTR_UNFLAGGED"}
    both = m[m._merge == "both"]
    issues = {
        "claims_without_dp": int((m._merge == "left_only").sum()),
        "dp_without_claim": int((m._merge == "right_only").sum()),
        "dp_dup": int(s.claim_id.duplicated().sum()),
        "text_differs": int((both.text != both.original_value).sum()),
        "uid_differs": int((both.unique_id != both.unique_id_dp).sum()),
        "field_differs": int((both.field != both.field_dp).sum()),
        "attribution_differs": int((both.attribution != both.attribution_dp).sum()),
        "rule_differs": int((both.attribution.map(rule) != both.rule).sum()),
        "dp_id_format": int((s.dp_id != "sent:" + s.claim_id).sum()),
    }
    bad = sum(issues.values())
    ex = both[both.text != both.original_value].claim_id.head(3).tolist() + both[both.attribution != both.attribution_dp].claim_id.head(2).tolist()
    return res("dps_sentence_rows_match_claims", "pass" if bad == 0 else "fail", f"{bad} inconsistencies over {len(c)} claims", "0",
               json.dumps(issues), ex)


def check_app_facts_claim_text():
    """app/facts/out/facts.json.gz 'claims' (claim_id -> [field, text, nonoffer, attribution]) must equal claims.parquet."""
    import gzip
    p = f"{ROOT}/app/facts/out/facts.json.gz"
    if not os.path.exists(p):
        return res("app_facts_claim_text", "not_run", "facts.json.gz missing", "", p)
    fc = json.load(gzip.open(p, "rt"))["claims"]
    c = claims().set_index("claim_id")
    missing = [i for i in fc if i not in c.index]
    differ = [i for i, v in fc.items() if i in c.index and
              (v[0] != c.at[i, "field"] or v[1] != c.at[i, "text"] or bool(v[2]) != bool(c.at[i, "nonoffer"]) or v[3] != c.at[i, "attribution"])]
    bad = len(missing) + len(differ)
    return res("app_facts_claim_text", "pass" if bad == 0 else "fail", f"{len(missing)} unknown ids, {len(differ)} field/text/flag mismatches over {len(fc)}",
               "0", "the app shows these quotes verbatim", missing[:3] + differ[:2])


def check_planner_cites_nonoffer_sentences():
    """Sentences the kb lexicon flags as non-offer (future, camp, negation, referral, past) that planner_v1 cites as capability
    evidence. planner/data_v1.py:83 filters on claims.nonoffer, which cleaning/claims computes only for its own 8 services."""
    import gzip
    p = json.load(gzip.open(f"{ROOT}/planner/out/planner_v1.json.gz", "rt"))
    cited = {(cap, cid) for cap, v in p["capabilities"].items() for ids in v["e"] for cid in ids}
    m = lex_matches()
    cued = m[(m.nonoffer_cue != "") | m.negation_extra]
    cmap = cued.groupby("claim_id").nonoffer_cue.agg(lambda x: "|".join(sorted(set(x) - {""})) or "negation_extra").to_dict()
    hit = sorted({(cap, cid) for cap, cid in cited if cid in cmap})
    t = claims().set_index("claim_id").text
    ex = [f"{cap} <- {cid} [{cmap[cid]}] {t[cid][:70]!r}" for cap, cid in hit[:5]]
    lab = _labels("planner_nonoffer_citations.csv")
    read = ""
    if lab is not None and sorted(zip(lab.capability, lab.claim_id)) == hit:
        read = f"; read in full: {lab.verdict.value_counts().to_dict()} (nonoffer = the citation is wrong, offer = cue false alarm)"
        ex = [f"{r.capability} <- {r.claim_id}: {r.note}" for r in lab[lab.verdict == "nonoffer"].head(5).itertuples()]
    return res("planner_cites_nonoffer_sentences", "pass" if not hit else "fail",
               f"{len(hit)} (capability, claim) citations over {len({c for _, c in hit})} kb-cued sentences; {len(cited)} citations in all",
               "0", "the planner shows these as evidence the facility has the capability" + read, ex)


# ---------------------------------------------------------------- exhaustive: kb/taxonomy lexicon

@functools.lru_cache(None)
def lexicon():
    return json.load(open(f"{TAX}/lexicon.json"))


@functools.lru_cache(None)
def lex_compiled():
    L = lexicon()
    comp = {}
    for sid, d in L["services"].items():
        c = lambda k: re.compile(d[k], re.I) if d.get(k) else None  # noqa: E731
        comp[sid] = {k: c(k) for k in ("include", "exclude", "exclude_clause", "strip_before_match", "negation_extra")}
    return comp, re.compile(L["clause_split"])


def lex_match(text: str) -> list[str]:
    """Matching rule as lexicon.json 'about' states it (reimplemented from the JSON, not imported from kb code)."""
    comp, split = lex_compiled()
    out = []
    for sid, c in comp.items():
        t = c["strip_before_match"].sub(" ", text) if c["strip_before_match"] else text
        if not c["include"].search(t) or (c["exclude"] and c["exclude"].search(t)):
            continue
        if c["exclude_clause"]:
            cl = [x for x in split.split(t) if c["include"].search(x)] or [t]
            if all(c["exclude_clause"].search(x) for x in cl):
                continue
        out.append(sid)
    return out


@functools.lru_cache(None)
def lex_matches() -> pd.DataFrame:
    return pd.read_parquet(f"{TAX}/out/lexicon_matches.parquet")


@functools.lru_cache(None)
def lex_reapplied() -> pd.DataFrame:
    c = claims()
    rows = [(cid, s) for cid, t in zip(c.claim_id, c.text) for s in lex_match(t)]
    return pd.DataFrame(rows, columns=["claim_id", "service"])


def check_lexicon_matches_reproduce_from_json():
    """Re-apply lexicon.json to all 469,498 claim texts; the result must equal out/lexicon_matches.parquet."""
    a = lex_reapplied().assign(k=1)
    b = lex_matches()[["claim_id", "service"]].assign(k=1)
    m = a.merge(b, on=["claim_id", "service"], how="outer", indicator=True)
    only_json = m[m._merge == "left_only"]
    only_file = m[m._merge == "right_only"]
    bad = len(only_json) + len(only_file)
    stated = (64670, 58004)
    got = (len(b), b.claim_id.nunique())
    ex = [f"json-only {r.claim_id} {r.service}" for r in only_json.head(3).itertuples()]
    ex += [f"file-only {r.claim_id} {r.service}" for r in only_file.head(2).itertuples()]
    return res("lexicon_matches_reproduce_from_json", "pass" if bad == 0 and got == stated else "fail",
               f"{bad} pair differences; file {got[0]} pairs / {got[1]} sentences (TAXONOMY.md states {stated[0]} / {stated[1]})", "0",
               f"only from lexicon.json {len(only_json)}, only in parquet {len(only_file)}", ex)


def check_lexicon_matches_join_claims():
    m = lex_matches()
    c = claims().set_index("claim_id")
    j = m.join(c[["unique_id", "field", "attribution", "kind", "dup_in_record"]], on="claim_id", rsuffix="_c")  # noqa
    issues = {"unknown_claim": int(j.unique_id_c.isna().sum()), "dup_pairs": int(m.duplicated(["claim_id", "service"]).sum())}
    for k in ("unique_id", "field", "attribution", "kind", "dup_in_record"):
        issues[k + "_differs"] = int((j[k] != j[k + "_c"]).sum())
    svc = set(json.load(open(f"{TAX}/services.json"))["services"]) if isinstance(json.load(open(f"{TAX}/services.json")).get("services"), dict) else None
    bad = sum(issues.values())
    return res("lexicon_matches_join_claims", "pass" if bad == 0 else "fail", f"{bad} inconsistencies over {len(m)} pairs", "0", json.dumps(issues))


def check_lexicon_nonoffer_cue_reproduce():
    """nonoffer_cue = first shared non-offer cue (lexicon.json order) hitting the text; negation_extra = the service's own pattern."""
    L = lexicon()
    cues = {k: re.compile(p, re.I) for k, p in L["shared_cues"]["nonoffer"].items()}
    comp, _ = lex_compiled()
    m = lex_matches().join(claims().set_index("claim_id").text, on="claim_id")
    exp = [next((k for k, r in cues.items() if r.search(t)), "") for t in m.text]
    neg = [bool(comp[s]["negation_extra"] and comp[s]["negation_extra"].search(t)) for s, t in zip(m.service, m.text)]
    b1 = int((pd.Series(exp, index=m.index) != m.nonoffer_cue).sum())
    b2 = int((pd.Series(neg, index=m.index) != m.negation_extra).sum())
    return res("lexicon_nonoffer_cue_reproduce", "pass" if b1 + b2 == 0 else "fail", f"nonoffer_cue {b1}, negation_extra {b2} differ over {len(m)}",
               "0", "reapplied from lexicon.json shared_cues.nonoffer and services.*.negation_extra")


def check_claims_nonoffer_vs_kb_cue():
    """claims.parquet nonoffer is computed only on sentences the cleaning/claims lexicon tagged; app/facts and planner read it for
    all sentences. Count kb-matched sentences that carry a kb non-offer cue but claims.nonoffer = False."""
    m = lex_matches()
    kb_cued = m[(m.nonoffer_cue != "") | m.negation_extra].claim_id.unique()
    c = claims().set_index("claim_id")
    sub = c.loc[kb_cued]
    gap = sub[~sub.nonoffer]
    cue_true_on_untagged = int((c.nonoffer & (c.services == "")).sum())
    return res("claims_nonoffer_vs_kb_cue", "pass" if gap.empty else "warn",
               f"{len(gap)} / {len(sub)} kb-cued service sentences have claims.nonoffer = False", "0",
               f"claims.nonoffer True on {int(c.nonoffer.sum())} rows, on untagged rows {cue_true_on_untagged}; consumers of claims.nonoffer "
               "(app/facts/build.py, planner/data_v1.py) miss these non-offers", gap.index[:5].tolist())


# ---------------------------------------------------------------- exhaustive: specialty map

@functools.lru_cache(None)
def raw_specialties() -> pd.DataFrame:
    rows = []
    for uid, j in base()[["unique_id", "specialties"]].itertuples(index=False):
        for s in (_items(j) or []):
            if isinstance(s, str) and s.strip():
                rows.append((uid, s))
    return pd.DataFrame(rows, columns=["unique_id", "specialty"])


def check_specialty_map_covers_raw_values():
    sm = pd.read_csv(f"{TAX}/specialty_map.csv", keep_default_na=False)
    loc = set(pd.read_parquet(f"{V1}/facility_location.parquet", columns=["unique_id"]).unique_id)
    sp = raw_specialties()
    vals = set(sp.specialty)
    keys = set(sm.specialty)
    missing = sorted(vals - keys)
    extra = sorted(keys - vals)
    dups = int(sm.specialty.duplicated().sum())
    usable = sp[sp.unique_id.isin(loc)].drop_duplicates()
    nf = usable.groupby("specialty").unique_id.nunique()
    cnt = sm.set_index("specialty").n_facilities.astype(int)
    diff = cnt.reindex(nf.index).fillna(-1).astype(int) != nf
    ids = set(json.load(open(f"{TAX}/lexicon.json"))["services"])
    labels = {"too_general", "out_of_scope", "not_a_service"}
    bad_ids = [v for v in sm.service_id if not all(t in ids or t in labels for t in v.split(";"))]
    bad_pre = [v for v in sm.prereq_for if v and not all(t in ids for t in v.split(";"))]
    bad = len(missing) + dups + int(diff.sum()) + len(bad_ids) + len(bad_pre)
    return res("specialty_map_covers_raw_values", "pass" if bad == 0 else "fail",
               f"raw values {len(vals)}, map rows {len(sm)}; missing {len(missing)}, not in raw {len(extra)}, dup keys {dups}, "
               f"n_facilities wrong {int(diff.sum())}, unknown service ids {len(bad_ids)}, unknown prereq ids {len(bad_pre)}", "0",
               "every raw specialties string maps exactly once to a known id; facility counts over the 9,959 usable records",
               missing[:3] + list(nf[diff].index[:2]) + bad_ids[:2])


def check_specialty_weights_consistent():
    w = pd.read_csv(f"{TAX}/specialty_evidence_weights.csv", keep_default_na=False)
    sm = pd.read_csv(f"{TAX}/specialty_map.csv", keep_default_na=False)
    ids = set(json.load(open(f"{TAX}/lexicon.json"))["services"])
    vcol = next(c for c in w.columns if c in ("specialty", "value"))
    scol = next(c for c in w.columns if c in ("service", "service_id"))
    wcol = next(c for c in w.columns if c in ("weight", "evidence_weight"))
    out_rng = int(((w[wcol] < 0) | (w[wcol] > 1)).sum())
    unk_v = int((~w[vcol].isin(sm.specialty)).sum())
    unk_s = int((~w[scol].isin(ids)).sum())
    dup = int(w.duplicated([vcol, scol]).sum())
    # each (value, service) should come from the map: the value is labelled with the service or lists it as prereq_for
    smi = sm.set_index("specialty")
    unlinked = [f"{v}->{s}" for v, s in zip(w[vcol], w[scol]) if v in smi.index and s not in smi.at[v, "service_id"].split(";")
                and s not in smi.at[v, "prereq_for"].split(";")]
    bad = out_rng + unk_v + unk_s + dup + len(unlinked)
    return res("specialty_weights_consistent", "pass" if bad == 0 else "fail",
               f"{len(w)} rows; weight out of [0,1] {out_rng}, unknown value {unk_v}, unknown service {unk_s}, dup {dup}, "
               f"pair not in map {len(unlinked)}", "0", f"columns {list(w.columns)[:8]}", unlinked[:5])


# ---------------------------------------------------------------- hand-read samples (labels/*.csv, drawn by samples.py)

def _labels(name):
    p = os.path.join(LAB, name)
    return pd.read_csv(p, keep_default_na=False) if os.path.exists(p) else None


def _sample_drift(lab, key, regen):
    """The labelled ids must be exactly what samples.py draws today (fixed seed), else the sample is stale."""
    return sorted(lab[key]) != sorted(regen[key])


def check_attribution_handread():
    import samples
    lab = _labels("attribution_80.csv")
    if lab is None or (lab.verdict == "").any():
        return res("attribution_handread", "not_run", "labels missing", "", "")
    drift = _sample_drift(lab, "claim_id", samples.attribution_sample())
    pop = claims().attribution.value_counts()
    per, notes = {}, []
    # correct = the label is right for what the sentence says. own/unanchored are right when the sentence is about this facility
    # (or generic); other_facility right when it is about another facility; ambiguous right when it cannot be told.
    ok_for = {"own_anchored": {"own"}, "unanchored": {"own"}, "other_facility": {"other"}, "ambiguous": {"unclear", "other"}}
    for lbl, g in lab.groupby("attribution"):
        k = int(g.verdict.isin(ok_for[lbl]).sum())
        per[lbl] = dict(n=len(g), correct=k, precision=round(k / len(g), 3), wilson=wilson(k, len(g)), verdicts=g.verdict.value_counts().to_dict())
    # recall of the other-facility flag: weight strata by population share
    w = {l: pop[l] / (lab.attribution == l).sum() for l in pop.index}
    other_true = lab.verdict == "other"
    tp = sum(w[l] for l in lab[other_true & (lab.attribution == "other_facility")].attribution)
    allo = sum(w[l] for l in lab[other_true].attribution)
    flag = lab.attribution.isin(["other_facility", "ambiguous"])
    allo_flag = sum(w[l] for l in lab[other_true & flag].attribution)
    rec = dict(other_facility_only=round(tp / allo, 3) if allo else None, other_or_ambiguous=round(allo_flag / allo, 3) if allo else None,
               est_other_sentences=round(allo), note="population-weighted; one 'other' among unanchored carries ~21,000 sentences")
    of = per.get("other_facility", {})
    status = "pass" if of.get("precision", 0) >= 0.7 and per.get("unanchored", {}).get("precision", 0) >= 0.9 else "warn"
    if drift:
        status, notes = "warn", ["sample ids differ from samples.py output (stale labels)"]
    ex = [f"{r.claim_id} [{r.attribution}->{r.verdict}] {r.note}" for r in lab[~lab.apply(lambda r: r.verdict in ok_for[r.attribution], axis=1)].head(5).itertuples()]
    return res("attribution_handread", status, json.dumps({k: (v["correct"], v["n"], v["wilson"]) for k, v in per.items()}),
               "other_facility precision >= 0.70; unanchored >= 0.90",
               json.dumps(dict(per=per, recall=rec, prior="handcheck.json A other_facility 17/23 (0.739), B ambiguous other 7 own 4 "
                                                          "not_a_claim 3, C unanchored 18/20; REPORT F1 20/30", notes=notes)), ex)


def check_lexicon_precision_handread():
    import samples
    lab = _labels("lexicon_precision.csv")
    if lab is None or (lab.verdict == "").any():
        return res("lexicon_precision_handread", "not_run", "labels missing", "", "")
    drift = _sample_drift(lab.assign(k=lab.claim_id + "|" + lab.service), "k",
                          samples.lexicon_precision_sample().assign(k=lambda d: d.claim_id + "|" + d.service))
    k = int((lab.verdict == "correct").sum())
    n = len(lab)
    ex = [f"{r.claim_id} {r.service}: {r.note}" for r in lab[lab.verdict != "correct"].head(5).itertuples()]
    st = "pass" if k / n >= 0.9 else "warn"
    return res("lexicon_precision_handread", "warn" if drift else st, f"{k}/{n} = {k / n:.3f} Wilson {wilson(k, n)}", ">= 0.90",
               f"random matched (sentence, service) pairs, all 37 services, seed {samples.SEED_LEXP}; prior: TAXONOMY v1.1 new-5 95/100 "
               f"(0.888-0.978), reviewer 37/40; verdicts {lab.verdict.value_counts().to_dict()}" + ("; STALE sample" if drift else ""), ex)


def check_lexicon_recall_handread():
    """Stratified recall: matched stratum (precision from the sample above) and unmatched stratum (misses found by reading)."""
    import samples
    lab = _labels("lexicon_recall.csv")
    lp = _labels("lexicon_precision.csv")
    if lab is None or (lab.verdict == "").any() or lp is None:
        return res("lexicon_recall_handread", "not_run", "labels missing", "", "")
    n = len(lab)
    miss = lab[lab.verdict == "missed"]
    k = len(miss)
    lo, hi = wilson(k, n)
    m_pairs = lex_matches()
    n_un = len(claims()) - m_pairs.claim_id.nunique()
    prec = (lp.verdict == "correct").mean()
    tp = prec * len(m_pairs)
    rec = tp / (tp + n_un * k / n) if n else None
    rec_lo = tp / (tp + n_un * hi)
    rec_hi = tp / (tp + n_un * lo)
    ex = [f"{r.claim_id} should be {r.service}: {r.note}" for r in miss.head(5).itertuples()]
    return res("lexicon_recall_handread", "pass" if rec >= 0.8 else "warn",
               f"misses {k}/{n} unmatched sentences (Wilson {lo}-{hi}); sentence-pair recall about {rec:.3f} ({rec_lo:.3f}-{rec_hi:.3f})",
               "recall >= 0.80", f"random unmatched sentences, seed {samples.SEED_LEXR}; unmatched pool {n_un}; no prior recall estimate existed "
               "(REVIEW.md 'Not run')", ex)


def check_specialty_map_handread():
    import samples
    lab = _labels("specialty_map.csv")
    if lab is None or (lab.verdict == "").any():
        return res("specialty_map_handread", "not_run", "labels missing", "", "")
    sm = pd.read_csv(f"{TAX}/specialty_map.csv", keep_default_na=False).set_index("specialty")[["service_id", "prereq_for"]]
    lab = lab.join(sm, on="specialty")
    k = int((lab.verdict == "correct").sum())
    n = len(lab)
    ex = [f"{r.specialty} -> {r.service_id} (prereq {r.prereq_for}): {r.note}" for r in lab[lab.verdict != "correct"].head(5).itertuples()]
    return res("specialty_map_handread", "pass" if k / n >= 0.9 else "warn", f"{k}/{n} = {k / n:.3f} Wilson {wilson(k, n)}", ">= 0.90",
               f"facility-mention-weighted sample of (record, specialties value), seed {samples.SEED_SPEC}; label and prereq_for both judged; "
               "prior: fresh v1.1 service-labelled 39/40 (0.871-0.996), reviewer random 80/80 after fixes", ex)


def check_nonoffer_positives_handread():
    import samples
    lab = _labels("nonoffer_30.csv")
    if lab is None or (lab.verdict == "").any():
        return res("nonoffer_positives_handread", "not_run", "labels missing", "", "")
    k = int((lab.verdict == "offer").sum())
    n = len(lab)
    ex = [f"{r.claim_id} {r.service}: {r.note}" for r in lab[lab.verdict != "offer"].head(5).itertuples()]
    return res("nonoffer_positives_handread", "pass" if k / n >= 0.9 else "warn", f"{k}/{n} positives really state an offer; Wilson {wilson(k, n)}",
               ">= 0.90", f"random kb positives (no cue, not other_facility, not staff/directory), seed {samples.SEED_NEG}; "
               f"verdicts {lab.verdict.value_counts().to_dict()}; prior: REPORT claims-03 v2 cues 34/40, handcheck D 14/15", ex)


def check_nonoffer_broad_scan():
    """Exhaustive: kb positives containing a broad negation / non-offer word that no cue caught. Upper bound on missed non-offers."""
    m = lex_matches()
    pos = m[(m.nonoffer_cue == "") & ~m.negation_extra & (m.attribution != "other_facility") & ~m.kind.isin(["staff", "directory"])]
    t = pos.join(claims().set_index("claim_id").text, on="claim_id")
    broad = re.compile(r"\b(not|no|never|nor|without|lack\w*|absence|unable|refer\w*|nearest|nearby|outside|elsewhere|soon|future|"
                       r"proposed|awaited|pending|temporar\w*|suspended|closed|stopped|only on|visiting|on call|on-call|weekly|monthly)\b", re.I)
    hit = t[t.text.map(lambda s: bool(broad.search(s)))]
    words = hit.text.str.extract(broad.pattern.replace("\\b(", "\\b(?P<w>", 1), flags=re.I).w.str.lower().value_counts().head(12).to_dict()
    return res("nonoffer_broad_scan", "warn" if len(hit) else "pass", f"{len(hit)} / {len(t)} positive pairs carry a broad cue word",
               "informational (upper bound)", f"top words {words}; see nonoffer_30 hand read for the true rate", hit.claim_id.head(5).tolist())


# ---------------------------------------------------------------- exhaustive follow-ups of hand-read error classes

OLD_NAMES = {"bijapur": ["vijayapura"], "vijayapura": ["bijapur"], "pondicherry": ["puducherry"], "puducherry": ["pondicherry"],
             "bombay": ["mumbai"], "madras": ["chennai"], "calcutta": ["kolkata"], "bangalore": ["bengaluru", "bangalore urban", "bangalore rural"],
             "bengaluru": ["bangalore"], "gurgaon": ["gurugram"], "gurugram": ["gurgaon"], "trivandrum": ["thiruvananthapuram"],
             "thiruvananthapuram": ["trivandrum"], "cochin": ["kochi", "ernakulam"], "calicut": ["kozhikode"], "poona": ["pune"],
             "baroda": ["vadodara"], "allahabad": ["prayagraj"], "prayagraj": ["allahabad"], "belgaum": ["belagavi"], "belagavi": ["belgaum"],
             "gulbarga": ["kalaburagi"], "mysore": ["mysuru"], "mangalore": ["mangaluru"], "orissa": ["odisha"], "tanjore": ["thanjavur"],
             "shimoga": ["shivamogga"], "hubli": ["hubballi", "dharwad"]}


def check_other_facility_own_place():
    """other_facility sentences whose every flagged place is the record's own city, district or state under an old or alternate name
    (Bijapur = Vijayapura, Poona = Pune, 'Hyderabad, Andhra Pradesh' for Telangana, 'Senapati Bapat Marg' read as Senapati, Manipur).
    The detector (audit/merge/detect.py place_relation) compares against the merge audit's own-place set, not
    facility_location.district, and has no historical-name table. Lower bound on location-trigger false positives."""
    c = claims()
    f = pd.read_parquet(f"{V1}/facility_location.parquet", columns=["unique_id", "address_city", "state_final", "district"]).set_index("unique_id")
    o = c[c.attribution == "other_facility"].join(f, on="unique_id")
    hits = []
    for r in o.itertuples():
        places = [p for p in (r.places_other_state + "; " + r.places_other_district).split("; ") if p]
        if not places or r.foreign_names or r.sibling_names:
            continue
        mine = {str(x).lower() for x in (r.address_city, r.state_final, r.district) if isinstance(x, str)}
        t = r.text.lower()
        ok = all(p in mine or any(a in mine for a in OLD_NAMES.get(p, [])) or (p == "senapati" and "senapati bapat" in t)
                 or (p == "andhra pradesh" and str(r.state_final).upper() == "TELANGANA") for p in places)
        if ok:
            hits.append(r.claim_id)
    return res("other_facility_own_place", "warn" if hits else "pass", f"{len(hits)} / {len(o)} other_facility sentences",
               "0", f"in {o[o.claim_id.isin(hits)].unique_id.nunique()} records; list in out/other_facility_own_place_alias.csv", hits)


def check_negation_cue_nonsurgical():
    """kb 'negation' cue pairs fired only by 'non-surgical' / 'without surgery' / 'no scar' phrasing: these describe a technique
    the facility offers, so they are removed from positive evidence wrongly (model v2 assemble/evidence.py reads nonoffer_cue)."""
    neg = re.compile(lexicon()["shared_cues"]["nonoffer"]["negation"], re.I)
    soft = re.compile(r"non[- ]surgical|\bwithout (surgery|open|the need|incision|scar|cuts?)|\bno (scars?|surgery|cuts?)\b", re.I)
    m = lex_matches().join(claims().set_index("claim_id").text, on="claim_id")
    n = m[m.nonoffer_cue == "negation"]
    bad = n[n.text.map(lambda t: all(soft.search(x.group(0)) for x in neg.finditer(t)))]
    return res("negation_cue_nonsurgical", "warn" if len(bad) else "pass", f"{len(bad)} / {len(n)} negation-cued pairs",
               "0", f"by service {bad.service.value_counts().to_dict()}", bad.claim_id.head(5).tolist())


def check_mri_magnetic_resonance_therapy():
    """'Quantum Magnetic Resonance Therapy' (QMRT) devices match the MRI core pattern 'magnetic resonance'
    (cleaning/claims lexicon.py SERVICES['mri'] core and kb lexicon.json mri include)."""
    m = lex_matches().join(claims().set_index("claim_id").text, on="claim_id")
    q = m[(m.service == "mri") & m.text.str.contains(r"QMRT|quantum magnetic|magnetic resonance therap", case=False)]
    good = set(m[(m.service == "mri") & ~m.claim_id.isin(q.claim_id)].unique_id)
    only = sorted(set(q.unique_id) - good)
    return res("mri_magnetic_resonance_therapy", "fail" if only else ("warn" if len(q) else "pass"),
               f"{len(q)} mri pairs; {len(only)} facilities have MRI only through these", "0",
               "all 3 are in app/facts pairs.mri graded moderate (G_mod, score about 0.8)", [u[:8] for u in only])


def check_ultrasound_3d_scan_only():
    """ultrasound pairs matched only by '(3|4|5)D (scan|ultrasound)', read in full (labels/ultrasound_3d_scan_all101.csv)."""
    lab = _labels("ultrasound_3d_scan_all101.csv")
    m = lex_matches().join(claims().set_index("claim_id").text, on="claim_id")
    u = m[m.service == "ultrasound"]
    other = re.compile(r"ultrasound|ultra-?sonograph|\bUSG\b|sonograph|colou?r doppler|doppler (?:study|scan|ultra)|anomaly scan|obstetric scan"
                       r"|f(?:o)?etal well[- ]?being|\bNT[- ]?scan|growth scan|level[- ]?(?:ii|2) (?:scan|ultrasound|anomaly)|\bTIFFA\b|nuchal translucency", re.I)
    only = u[~u.text.map(lambda t: bool(other.search(t)))]
    if lab is None or sorted(lab.claim_id) != sorted(only.claim_id):
        return res("ultrasound_3d_scan_only", "not_run", f"{len(only)} pairs; labels missing or stale", "", "")
    bad = lab[lab.verdict == "not_ultrasound"]
    good_f = set(u[~u.claim_id.isin(bad.claim_id)].unique_id)
    lost = sorted(set(bad.unique_id) - good_f)
    return res("ultrasound_3d_scan_only", "warn" if len(bad) else "pass",
               f"{len(bad)} / {len(only)} are not ultrasound (dental intraoral/CBCT, eye OCT, orthotics); {len(lost)} facilities have ultrasound only through them",
               "0", f"precision of the 3D-scan alternative {len(lab) - len(bad) - (lab.verdict == 'unclear').sum()}/{len(lab)}; kb lexicon.json ultrasound include",
               bad.claim_id.head(5).tolist())


def check_spine_neurosurgery_only():
    """spineNeurosurgery maps to neurosurgery (service label) although v1.1 defines neurosurgery as brain surgery with spine as an
    attribute; count facilities whose neurosurgery 'any' evidence is that value alone."""
    loc = set(pd.read_parquet(f"{V1}/facility_location.parquet", columns=["unique_id"]).unique_id)
    sp = raw_specialties()
    sp = sp[sp.unique_id.isin(loc)].drop_duplicates()
    sm = pd.read_csv(f"{TAX}/specialty_map.csv", keep_default_na=False)
    neu = set(sm[sm.service_id.str.split(";").map(lambda x: "neurosurgery" in x)].specialty)
    spine = set(sp[sp.specialty == "spineNeurosurgery"].unique_id)
    other = set(sp[sp.specialty.isin(neu - {"spineNeurosurgery"})].unique_id) | set(lex_matches().query("service == 'neurosurgery'").unique_id)
    only = sorted(spine - other)
    w = pd.read_csv(f"{TAX}/specialty_evidence_weights.csv", keep_default_na=False)
    wt = w[(w.specialty == "spineNeurosurgery") & (w.service == "neurosurgery")].weight.tolist()
    return res("spine_neurosurgery_only", "warn" if only else "pass", f"{len(only)} / {len(spine)} spineNeurosurgery facilities", "0",
               f"label={sm.set_index('specialty').at['spineNeurosurgery', 'service_id']}; evidence weight {wt} damps it in the model; "
               "coverage 'any' counts them as neurosurgery", [u[:8] for u in only[:5]])


def check_v2_claim_id_contract():
    """Contract for derived/v2 (in flux, not judged here): every claim id it cites, in a claim_id column or inside a string
    column of ids, exists in derived/v1/claims.parquet. Runs only with RUN_V2=1, after the model fit (#11) has written v2."""
    import glob
    if os.environ.get("RUN_V2") != "1":
        return res("v2_claim_id_contract", "not_run", "gated: set RUN_V2=1 once derived/v2 is final", "0 unknown claim ids", "")
    files = glob.glob(f"{ROOT}/derived/v2/*.parquet")
    if not files:
        return res("v2_claim_id_contract", "not_run", "derived/v2 has no parquet files", "0 unknown claim ids", "")
    known = set(claims().claim_id)
    cid = re.compile(r"[0-9a-f]{8}:(?:proc|equi|capa|desc):\d+")
    bad, n = [], 0
    for f in files:
        d = pd.read_parquet(f)
        for col in d.columns:
            if d[col].dtype == object or str(d[col].dtype) in ("str", "string"):
                for v in d[col].dropna().astype(str):
                    for x in cid.findall(v):
                        n += 1
                        if x not in known:
                            bad.append(f"{os.path.basename(f)}:{col}:{x}")
    return res("v2_claim_id_contract", "pass" if not bad else "fail", f"{len(bad)} unknown of {n} cited claim ids", "0", "", bad)


CHECKS = [v for k, v in sorted(globals().items()) if k.startswith("check_") and callable(v)]


def main(only=None):
    os.makedirs(OUT, exist_ok=True)
    sys.path.insert(0, D)
    results = []
    for f in CHECKS:
        if only and f.__name__ not in only:
            continue
        try:
            r = f()
        except Exception as e:  # a crashing check is reported, never silently skipped
            r = res(f.__name__[6:], "fail", "check crashed", "", f"{type(e).__name__}: {e}")
        results.append(r)
        print(f"[{r['status']:7}] {r['name']}: {r['metric']}", flush=True)
    path = os.path.join(OUT, "results.json" if not only else "results_partial.json")
    json.dump(results, open(path, "w"), indent=1, default=str)
    return results


if __name__ == "__main__":
    main(set("check_" + a for a in sys.argv[1:]) or None)
