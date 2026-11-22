"""Audit of kb/web_evidence and kb/vf_details (website and dataset-detail facts).

Every check_<name>() returns dict(name, status, metric, threshold, detail, examples). All checks are read-only.
Run all:   /Users/karthikvattem/projects/datathon/.venv-viz/bin/python checks.py      (writes out/checks.json)
Run some:  ... checks.py check_web_fact_quotes_verbatim check_vf_quotes_verbatim

The hand-judged sample checks read labels.py (verdicts written by reading sample.py output); the liveness check reads
out/liveness.json written by liveness.py (a polite live fetch). Both raise nothing when their input is missing:
they report status "not_run" in detail and warn.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
import sys
from functools import lru_cache

import pandas as pd

ROOT = "/Users/karthikvattem/projects/datathon"
WE = f"{ROOT}/kb/web_evidence/out"
VF = f"{ROOT}/kb/vf_details/out"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
FACT_TABLES = ("web_services", "web_hours", "web_details")


# ---------------------------------------------------------------- helpers
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 3), round(c + h, 3))


def result(name: str, status: str, metric, threshold: str, detail: str, examples: list) -> dict:
    return {"name": name, "status": status, "metric": metric, "threshold": threshold, "detail": detail, "examples": examples[:5]}


@lru_cache(None)
def table(name: str) -> pd.DataFrame:
    base = VF if name in ("facts", "facility_details") else WE
    return pd.read_parquet(f"{base}/{name}.parquet")


@lru_cache(None)
def docs() -> dict[str, dict]:
    """Every page file cited by any web table, opened once."""
    paths = set()
    for t in FACT_TABLES:
        paths |= set(table(t).path)
    paths |= set(table("page_identity").path)
    paths |= set(pd.read_parquet(f"{ROOT}/kb/crawl/pages.parquet", columns=["path"]).path.dropna())
    out = {}
    for p in paths:
        with gzip.open(os.path.join(ROOT, p)) as fh:
            out[p] = json.load(fh)
    return out


def url_path(url: str) -> str:
    """kb/crawl/crawl.py store(): the file name is sha1(final_url)[:20]."""
    return f"data/crawl/pages/{hashlib.sha1(url.encode()).hexdigest()[:20]}.json.gz"


# ---------------------------------------------------------------- exhaustive: web quotes
def check_web_fact_quotes_verbatim() -> dict:
    """Every service, hour and detail quote is an exact substring of the stored field it names, its segment sits at
    seg_start in that field, and the quote lies inside the segment."""
    D = docs()
    n = bad_sub = bad_pos = bad_inseg = bad_match = 0
    ex = []
    for t in FACT_TABLES:
        df = table(t)
        seg_col = "segment" if t == "web_services" else "source_text"
        for r in df[["path", "field", "quote", seg_col, "seg_start", "match"]].itertuples(index=False):
            n += 1
            txt = D[r.path].get(r.field) or ""
            q, seg = r.quote, getattr(r, seg_col)
            if not (isinstance(q, str) and q and q in txt):
                bad_sub += 1
                ex.append(f"{t}: {r.path} {r.field} quote not in field: {str(q)[:60]!r}")
            if txt[int(r.seg_start):int(r.seg_start) + len(seg)] != seg:
                bad_pos += 1
                if len(ex) < 10:
                    ex.append(f"{t}: {r.path} {r.field}@{r.seg_start} segment not at offset: {seg[:60]!r}")
            if q not in seg:
                bad_inseg += 1
            if isinstance(r.match, str) and r.match and r.match not in seg:
                bad_match += 1
    bad = bad_sub + bad_pos + bad_inseg + bad_match
    return result("web_fact_quotes_verbatim", "pass" if bad == 0 else "fail", {"rows": n, "quote_not_in_field": bad_sub, "segment_not_at_offset": bad_pos,
                  "quote_not_in_segment": bad_inseg, "match_not_in_segment": bad_match}, "0 failures",
                  f"{n} rows over {', '.join(FACT_TABLES)} re-checked against {len(D)} gz files", ex)


def check_web_identity_quotes_verbatim() -> dict:
    """page_identity name/PIN/locality quotes are exact substrings of their field; site_identity quotes are substrings
    of the page the cited URL maps to (sha1 of the URL)."""
    D = docs()
    n = bad = missing_file = 0
    ex = []
    pi = table("page_identity")
    for col, fcol in (("name_quote", "name_field"), ("pin_quote", "pin_field"), ("loc_quote", "loc_field")):
        for r in pi[pi[col].notna()][["path", fcol, col, "unique_id"]].itertuples(index=False):
            n += 1
            if r[2] not in (D[r[0]].get(r[1]) or ""):
                bad += 1
                ex.append(f"page_identity {r.unique_id} {col}: {r[2][:60]!r}")
    si = table("site_identity")
    for col, fcol, ucol in (("name_quote", "name_field", "name_url"), ("pin_quote", "pin_field", "pin_url"), ("locality_quote", "locality_field", "locality_url")):
        for r in si[si[col].notna()][[ucol, fcol, col, "unique_id"]].itertuples(index=False):
            n += 1
            p = url_path(r[0])
            if p not in D:
                missing_file += 1
                ex.append(f"site_identity {r.unique_id} {ucol} has no stored page: {r[0]}")
                continue
            if r[2] not in (D[p].get(r[1]) or ""):
                bad += 1
                ex.append(f"site_identity {r.unique_id} {col}: {r[2][:60]!r}")
    return result("web_identity_quotes_verbatim", "pass" if bad + missing_file == 0 else "fail",
                  {"quotes": n, "not_substring": bad, "cited_url_not_stored": missing_file}, "0 failures",
                  "page_identity and site_identity name, PIN and locality quotes", ex)


def check_web_provenance() -> dict:
    """The URL, target and fetch time printed next to a fact are the ones of the file the quote was verified in."""
    D = docs()
    n = 0
    bad = {"final_url": 0, "target_id": 0, "fetched_at": 0, "path_hash": 0, "unexplained_meta": 0}
    ex = []
    pages = pd.read_parquet(f"{ROOT}/kb/crawl/pages.parquet", columns=["path", "text_hash"]).dropna(subset=["path"])
    shared = set(pages[pages.path.duplicated(keep=False)].path)
    for t in FACT_TABLES:
        df = table(t)
        for r in df[["path", "final_url", "target_id", "fetched_at", "unique_id"]].itertuples(index=False):
            n += 1
            d = D[r.path]
            for k, got in (("final_url", d.get("url_final")), ("target_id", d.get("target_id")), ("fetched_at", d.get("fetched_at"))):
                if got != getattr(r, k):
                    bad[k] += 1
                    if len(ex) < 5:
                        ex.append(f"{t} {r.unique_id} {r.path}: {k} row={getattr(r, k)!r} file={got!r}")
            if url_path(r.final_url) != r.path:
                bad["path_hash"] += 1
            if (d.get("target_id"), d.get("fetched_at")) != (r.target_id, r.fetched_at) and r.path not in shared:
                bad["unexplained_meta"] += 1
    # the crawl names a file by sha1(final_url), so a URL fetched by 2 page rows is one file holding the last write;
    # every pages.parquet text_hash must still equal sha1 of that file's text, else a quote may come from other content
    hash_bad = [r.path for r in pages.itertuples() if hashlib.sha1((D[r.path].get("text") or "").encode()).hexdigest() != r.text_hash]
    hard = bad["final_url"] + bad["path_hash"] + bad["unexplained_meta"] + len(hash_bad)
    return result("web_provenance", "fail" if hard else ("warn" if bad["target_id"] + bad["fetched_at"] else "pass"),
                  {"rows": n, **bad, "page_rows": len(pages), "files_shared_by_2plus_page_rows": len(shared), "text_hash_mismatch": len(hash_bad)},
                  "0 hard mismatches (final_url, path hash, text hash, unexplained meta)",
                  "row final_url / target_id / fetched_at against the gz file; target_id/fetched_at differences on shared files are the "
                  "row's own fetch metadata (the file holds the other fetch of the same URL, same text hash)", ex + hash_bad[:2])


def check_web_identity_quote_semantics() -> dict:
    """A PIN quote must contain the record's PIN; a locality quote its city or district (word match, any case)."""
    si = table("site_identity")
    loc = pd.read_parquet(f"{ROOT}/cleaning/geo_identity/facility_location.parquet", columns=["unique_id", "address_city", "district", "pin"]).drop_duplicates("unique_id")
    x = si.merge(loc, on="unique_id", how="left")
    pin_rows = x[x.pin_quote.notna()]
    pin_ok = [bool(pd.notna(p) and re.search(rf"{str(int(p))[:3]}\s?-?\s?{str(int(p))[3:]}", q)) for p, q in zip(pin_rows.pin, pin_rows.pin_quote)]
    pin_bad = pin_rows[[not o for o in pin_ok]]
    lrows = x[x.locality_quote.notna()]

    def has_place(q, c, d):
        for v in (c, d):
            if isinstance(v, str) and v.strip() and re.search(rf"(?<![a-z]){re.escape(v.strip().lower())}(?![a-z])", q.lower()):
                return True
        return False
    lok = [has_place(q, c, d) for q, c, d in zip(lrows.locality_quote, lrows.address_city, lrows.district)]
    lbad = lrows[[not o for o in lok]]
    ex = [f"{r.unique_id} pin={r.pin} quote={r.pin_quote[:70]!r}" for r in pin_bad.head(3).itertuples()] + \
         [f"{r.unique_id} city={r.address_city} district={r.district} quote={r.locality_quote[:70]!r}" for r in lbad.head(3).itertuples()]
    nb = len(pin_bad) + len(lbad)
    return result("web_identity_quote_semantics", "pass" if nb == 0 else "warn",
                  {"pin_quotes": len(pin_rows), "pin_quote_without_record_pin": len(pin_bad), "locality_quotes": len(lrows), "locality_quote_without_city_or_district": len(lbad)},
                  "0", "site_identity evidence quotes contain the record's own PIN / place", ex)


def check_web_attributable_contract() -> dict:
    """attributable implies identity high/medium and not a chain homepage, on the site of an ok/ok_thin target."""
    sites = pd.read_parquet(f"{ROOT}/kb/crawl/sites.parquet", columns=["target_id", "site_status"])
    ok_targets = set(sites[sites.site_status.isin(["ok", "ok_thin"])].target_id)
    out, ex = {}, []
    for t in FACT_TABLES:
        df = table(t)
        a = df[df.attributable]
        bad = a[~a.identity_conf.isin(["high", "medium"]) | (a.scope == "chain_home") | ~a.target_id.isin(ok_targets)]
        out[t] = {"attributable": len(a), "violations": len(bad)}
        ex += [f"{t} {r.unique_id} {r.target_id} conf={r.identity_conf} scope={r.scope}" for r in bad.head(2).itertuples()]
    si = table("site_identity")
    sbad = si[si.attributable != (si.confidence.isin(["high", "medium"]) & (si.kind != "shared_home"))]
    out["site_identity"] = {"rows": len(si), "violations": len(sbad)}
    ex += [f"site_identity {r.unique_id} {r.target_id} kind={r.kind} conf={r.confidence} attributable={r.attributable}" for r in sbad.head(3).itertuples()]
    nb = sum(v["violations"] for v in out.values())
    return result("web_attributable_contract", "pass" if nb == 0 else "fail", out, "0 violations", "README contract for `attributable`", ex)


def check_web_service_summary_consistency() -> dict:
    """web_service_summary is a faithful roll-up: best_quote is a positive attributable row of that pair at best_url,
    and web_positive / web_positive_strong / n_pages_positive recount from web_services."""
    svc = table("web_services")
    ss = table("web_service_summary")
    pos = svc[svc.positive & svc.attributable]
    rows = set(zip(pos.unique_id, pos.service_id, pos.quote, pos.final_url, pos.field))
    g = pos.groupby(["unique_id", "service_id"]).agg(n_pages=("page_id", "nunique"), strong=("strength", lambda s: (s == "strong").any())).reset_index()
    x = ss.merge(g, on=["unique_id", "service_id"], how="left")
    sp = x[x.web_positive]
    no_row = sp[[(u, s, q, l, f) not in rows for u, s, q, l, f in zip(sp.unique_id, sp.service_id, sp.best_quote, sp.best_url, sp.best_field)]]
    pos_mis = x[x.web_positive != x.n_pages.notna()]
    strong_mis = sp[sp.web_positive_strong != sp.strong.fillna(False).astype(bool)]
    pages_mis = sp[sp.n_pages_positive != sp.n_pages]
    m = {"pairs": len(ss), "positive_pairs": len(sp), "best_quote_not_a_positive_row": len(no_row), "web_positive_mismatch": len(pos_mis),
         "strong_mismatch": len(strong_mis), "n_pages_positive_mismatch": len(pages_mis)}
    ex = [f"{r.unique_id} {r.service_id} best={r.best_quote[:50]!r}" for r in no_row.head(2).itertuples()] + \
         [f"{r.unique_id} {r.service_id} n_pages_positive={r.n_pages_positive} recount={r.n_pages}" for r in pages_mis.head(3).itertuples()]
    nb = len(no_row) + len(pos_mis) + len(strong_mis) + len(pages_mis)
    return result("web_service_summary_consistency", "pass" if nb == 0 else "warn", m, "0", "summary vs web_services recount (page_id distinct)", ex)


def _facility_value_check(name: str, fd: pd.DataFrame, facts: pd.DataFrame) -> dict:
    f = facts.drop_duplicates("fact_id").set_index("fact_id")
    x = fd[fd.n_usable > 0].join(f[["quote", "value_text", "value_num", "unique_id"]].rename(columns=lambda c: "c_" + c), on="best_fact_id")
    missing = x[x.c_quote.isna()]
    x = x[x.c_quote.notna()]
    qbad = x[x.best_quote != x.c_quote]
    ubad = x[x.unique_id != x.c_unique_id]
    tv = x.value_text.fillna("").astype(str)
    cv = x.c_value_text.fillna("").astype(str)
    nv = ~((x.value_num == x.c_value_num) | (x.value_num.isna() & x.c_value_num.isna()))
    vbad = x[(tv != cv) | nv]
    by = vbad.groupby(["fact_type", "attribute"]).size().sort_values(ascending=False).head(8).to_dict()
    ex = [f"{r.unique_id} {r.fact_type}:{r.attribute} shown=({r.value_text!r}, {r.value_num}) cited_row=({r.c_value_text!r}, {r.c_value_num}) quote={r.best_quote[:50]!r}"
          for r in vbad.sample(min(5, len(vbad)), random_state=1).itertuples()] if len(vbad) else []
    m = {"usable_facility_facts": int((fd.n_usable > 0).sum()), "best_fact_id_missing": len(missing), "best_quote_differs_from_cited_row": len(qbad),
         "unique_id_differs": len(ubad), "value_differs_from_cited_row": len(vbad), "share": round(len(vbad) / max(1, len(x)), 4),
         "top_attributes": {f"{a}:{b}": int(v) for (a, b), v in by.items()}}
    st = "fail" if len(missing) + len(qbad) + len(ubad) else ("warn" if len(vbad) else "pass")
    return result(name, st, m, "0 (a shown value should be supported by the quote shown next to it)",
                  "facility-level value_text/value_num vs the row whose quote is cited (best_fact_id)", ex)


def check_web_facility_value_supported() -> dict:
    facts = pd.concat([table("web_hours"), table("web_details")])
    return _facility_value_check("web_facility_value_supported", table("web_facility_details"), facts)


def check_vf_facility_value_supported() -> dict:
    return _facility_value_check("vf_facility_value_supported", table("facility_details"), table("facts"))


# ---------------------------------------------------------------- exhaustive: vf_details quotes
@lru_cache(None)
def raw_fields() -> pd.DataFrame:
    import duckdb
    return duckdb.sql(f"""select unique_id, any_value(procedure) procedure, any_value(capability) capability, any_value(equipment) equipment,
        any_value(description) description from read_parquet('{ROOT}/data/raw/facilities.parquet')
        where source='kie' group by 1""").df().set_index("unique_id")


def check_vf_quotes_verbatim() -> dict:
    """quote in source_text and match in quote for every fact; source_text equals the cited claim's text; the claim
    text is in the raw dataset field it came from; typed-field facts equal the cleaned typed value."""
    f = table("facts")
    txt = f[f.claim_id.notna()]
    claims = pd.read_parquet(f"{ROOT}/derived/v1/claims.parquet", columns=["claim_id", "unique_id", "field", "text"]).set_index("claim_id")
    q_bad = f[[not (isinstance(q, str) and q and q in s) for q, s in zip(f.quote, f.source_text)]]
    m_bad = f[[isinstance(m, str) and bool(m) and m not in q for m, q in zip(f.match, f.quote)]]
    j = txt.join(claims.rename(columns=lambda c: "c_" + c), on="claim_id")
    no_claim = j[j.c_text.isna()]
    s_bad = j[j.c_text.notna() & (j.source_text != j.c_text)]
    u_bad = j[j.c_text.notna() & ((j.unique_id != j.c_unique_id) | (j.field != j.c_field))]
    raw = raw_fields()
    raw_bad = []
    for r in j[j.c_text.notna()].drop_duplicates("claim_id").itertuples():
        v = raw.at[r.unique_id, r.field] if r.unique_id in raw.index else None
        if not isinstance(v, str):
            raw_bad.append(r.claim_id)
            continue
        if r.field != "description":
            try:
                v = "\n".join(x for x in json.loads(v) if isinstance(x, str))
            except ValueError:
                pass
        if r.c_text not in v:
            raw_bad.append(r.claim_id)
    sc = pd.read_parquet(f"{ROOT}/audit/scale/scale_flags.parquet", columns=["unique_id", "doctors_clean", "capacity_clean"]).drop_duplicates("unique_id").set_index("unique_id")
    st = f[f.method == "structured"]
    typed_bad = []
    for r in st[st.field.isin(["capacity", "numberDoctors"])].itertuples():
        col = "capacity_clean" if r.field == "capacity" else "doctors_clean"
        v = sc[col].get(r.unique_id)
        if v is None or pd.isna(v) or float(v) != float(r.value_num) or r.quote != f"{int(v)}":
            typed_bad.append(f"{r.fact_id} value={r.value_num} clean={v}")
    m = {"facts": len(f), "text_facts": len(txt), "quote_not_in_source_text": len(q_bad), "match_not_in_quote": len(m_bad), "claim_id_not_found": len(no_claim),
         "source_text_differs_from_claim": len(s_bad), "unique_id_or_field_differs": len(u_bad), "claim_not_in_raw_field": len(raw_bad),
         "typed_fact_value_mismatch": len(typed_bad), "typed_facts_checked": int(st.field.isin(["capacity", "numberDoctors"]).sum())}
    ex = [f"{r.fact_id}: {r.quote[:60]!r}" for r in q_bad.head(2).itertuples()] + [f"{r.fact_id}: source_text != claim text" for r in s_bad.head(2).itertuples()] + raw_bad[:2] + typed_bad[:2]
    nb = len(q_bad) + len(m_bad) + len(no_claim) + len(s_bad) + len(u_bad) + len(raw_bad) + len(typed_bad)
    return result("vf_quotes_verbatim", "pass" if nb == 0 else "fail", m, "0 failures", "quote -> source_text -> derived/v1/claims.text -> data/raw field", ex)


def check_vf_handcheck_reproducible() -> dict:
    """The 50 hand-checked fact_ids still exist with the same value (the reported 0.92 still refers to this table)."""
    lab = pd.read_csv(f"{ROOT}/kb/vf_details/handcheck_labels.csv")
    hs = pd.read_csv(f"{VF}/handcheck_sample.csv")
    f = table("facts").set_index("fact_id")
    gone = [i for i in lab.fact_id if i not in f.index]
    x = hs[hs.fact_id.isin(f.index)]
    changed = [r.fact_id for r in x.itertuples() if (str(f.at[r.fact_id, "value_text"]) != str(r.value_text) and not (pd.isna(r.value_text) and pd.isna(f.at[r.fact_id, "value_text"])))
               or f.at[r.fact_id, "attribute"] != r.attribute or f.at[r.fact_id, "fact_type"] != r.fact_type]
    st = "pass" if not gone else "warn"
    return result("vf_handcheck_reproducible", st, {"labelled": len(lab), "fact_id_gone": len(gone), "changed_since_label": len(changed)}, "0 gone",
                  "fact_ids gone are the post-handcheck fixes (README: specialty doctors, free_with_package)", gone[:3] + changed[:2])


# ---------------------------------------------------------------- exhaustive: ids, domains, privacy
def check_ids_and_domains() -> dict:
    out, ex = {}, []
    for t, key in (("web_hours", "fact_id"), ("web_details", "fact_id"), ("facts", "fact_id")):
        df = table(t)
        d = int(df[key].duplicated().sum())
        out[f"{t}_dup_{key}"] = d
        if d:
            ex.append(f"{t} duplicate {key}: {df[df[key].duplicated()][key].iloc[0]}")
    svc = table("web_services")
    out["web_services_dup_key"] = int(svc.duplicated(["unique_id", "page_id", "field", "seg_start", "service_id"]).sum())
    taxo = set(json.load(open(f"{ROOT}/kb/taxonomy/lexicon.json")).get("services", {}).keys()) if os.path.exists(f"{ROOT}/kb/taxonomy/lexicon.json") else set()
    if taxo:
        out["service_id_outside_taxonomy"] = int((~svc.service_id.isin(taxo)).sum())
    for t in ("web_hours", "web_details", "facts"):
        df = table(t)
        out[f"{t}_bad_status"] = int((~df.status.isin(["ok", "flagged", "excluded"])).sum())
        out[f"{t}_bad_polarity"] = int((~df.polarity.isin(["positive", "neutral", "negative"])).sum())
        num = df[df.value_num.notna() & (df.status != "excluded") & (df.polarity == "positive")]
        neg = num[num.value_num <= 0]
        out[f"{t}_nonpositive_usable_count"] = len(neg)
        if len(neg):
            ex.append(f"{t} {neg.fact_id.iloc[0]} value_num={neg.value_num.iloc[0]}")
    # schedule strings: every hh:mm must be a valid clock time (kb/vf_details/patterns.py _mins adds 12 to "18pm")
    def bad_clock(v) -> bool:
        return any(int(a) > 24 or int(b) > 59 for a, b in re.findall(r"(\d{1,2}):(\d{2})", v if isinstance(v, str) else ""))
    for t in ("web_hours", "facts", "web_facility_details", "facility_details"):
        df = table(t)
        b = df[df.value_text.map(bad_clock)]
        if "status" in df:
            out[f"{t}_invalid_clock_rows"] = len(b)
            out[f"{t}_invalid_clock_usable"] = int((b.status.isin(["ok", "flagged"]) & (b.polarity == "positive")).sum())
            ex += [f"{t} {r.fact_id} {r.value_text} <- {r.quote[:50]!r}" for r in b.head(2).itertuples()]
        else:
            out[f"{t}_invalid_clock_facility_values"] = int((b.n_usable > 0).sum())
            ex += [f"{t} {r.unique_id} {r.attribute} {r.value_text}" for r in b.head(1).itertuples()]
    nb = sum(v for k, v in out.items())
    return result("ids_and_domains", "pass" if nb == 0 else "warn", out, "0", "unique keys, enum domains, positive counts, clock times", ex)


PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)|(?<!\d)0\d{2,4}\s*[\s-]\s*\d{6,8}(?!\d)|(?<![\d.])\d{10,12}(?![\d.])")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def check_quote_redaction() -> dict:
    """Web quotes are shown in the app: count quotes that still carry a phone number or email the crawl did not redact."""
    out, ex = {}, []
    for t in FACT_TABLES:
        q = table(t).quote.drop_duplicates()
        ph = q[q.str.contains(PHONE)]
        em = q[q.str.contains(EMAIL)]
        out[t] = {"distinct_quotes": len(q), "with_phone": len(ph), "with_email": len(em)}
        ex += [f"{t}: {s[:80]!r}" for s in ph.head(2)] + [f"{t}: {s[:80]!r}" for s in em.head(1)]
    nb = sum(v["with_phone"] + v["with_email"] for v in out.values())
    return result("quote_redaction", "pass" if nb == 0 else "warn", out, "0 unredacted contacts",
                  "regex: Indian mobile (10 digits from 6-9, optional +91) or STD landline with separator; email", ex)


# ---------------------------------------------------------------- exhaustive: systematic error patterns
BIO = re.compile(r"\b(?:MBBS|M\.?B\.?B\.?S|FRCS|MRCP|D\.?N\.?B|M\.?Ch|years? of experience|experience of \d|trained (?:at|in)|worked (?:at|as|in)|"
                 r"he is|she is|his |her |completed (?:his|her)|fellowship|graduated)", re.I)
SOON = re.compile(r"coming soon|opening soon|will be (?:operational|started|starting|launched|available|commissioned)|under construction|upcoming|shortly", re.I)
PHONE_CUE = re.compile(r"\bcall\b|helpline|help line|hotline|phone|\[phone\]|contact|whatsapp|appointment|enquir|booking|toll[- ]?free|customer care|support", re.I)


def check_service_error_patterns() -> dict:
    """Population prevalence of the systematic error patterns among positive attributable service pairs."""
    svc = table("web_services")
    pos = svc[svc.positive & svc.attributable]
    pairs = pos.groupby(["unique_id", "service_id"])
    n_pairs = pairs.ngroups

    def only(mask) -> tuple[int, int]:
        """pairs having >=1 row with the pattern, and pairs whose every positive row has it"""
        k = pos.assign(m=mask).groupby(["unique_id", "service_id"]).m.agg(["any", "all"])
        return int(k["any"].sum()), int(k["all"].sum())
    chrome = pos.field == "chrome_text"
    # template text: the identical quote positive on 10+ distinct sites
    qsites = pos.groupby("quote").target_id.nunique()
    template = pos.quote.map(qsites) >= 10
    seg = pos.segment
    bio = seg.str.contains(BIO)
    soon = seg.str.contains(SOON)
    path_recs = pos.groupby("path").unique_id.nunique()
    shared_page = pos.path.map(path_recs) >= 2
    tgt_recs = table("site_identity").groupby("target_id").unique_id.nunique()
    multi_record_site = pos.target_id.map(tgt_recs).fillna(1) >= 3
    m = {"positive_pairs": n_pairs}
    for k, mask in (("chrome_text_menu_footer", chrome), ("template_quote_on_10plus_sites", template), ("doctor_bio_cue", bio), ("coming_soon_cue", soon),
                    ("page_credited_to_2plus_records", shared_page), ("site_serving_3plus_records", multi_record_site)):
        a, al = only(mask)
        m[k] = {"rows": int(mask.sum()), "pairs_any": a, "pairs_only": al, "pairs_only_share": round(al / n_pairs, 4)}
    ex = [f"template: {q!r} on {qsites[q]} sites" for q in qsites.sort_values(ascending=False).head(3).index] + \
         [f"soon: {r.unique_id} {r.service_id} {r.quote[:70]!r}" for r in pos[soon].head(2).itertuples()]
    worst = max(v["pairs_only_share"] for k, v in m.items() if isinstance(v, dict) and k != "site_serving_3plus_records")
    return result("service_error_patterns", "warn" if worst > 0.02 else "pass", m, "pairs resting only on a pattern <= 2% each",
                  "positive & attributable web_services rows; 'pairs_only' = every positive row of the pair has the pattern", ex)


def check_hours_error_patterns() -> dict:
    """24x7 emergency facts that are phone support, and facility-24x7 facts that name a unit (QA fix 5, re-measured)."""
    h = table("web_hours")
    u = h[h.attributable & h.status.isin(["ok", "flagged"]) & (h.polarity == "positive")]
    em = u[(u.fact_type == "hours_24x7") & (u.attribute == "emergency")]
    phone = em[em.source_text.str.contains(PHONE_CUE)]
    rec_em = em.groupby("unique_id").fact_id.size()
    rec_phone_only = em.assign(p=em.source_text.str.contains(PHONE_CUE)).groupby("unique_id").p.all()
    fac = u[(u.fact_type == "hours_24x7") & (u.attribute == "facility")]
    unit = fac[fac.source_text.str.contains(r"\b(?:ICU|NICU|PICU|HDU|ICCU|CCU|pharmacy|lab|laboratory|ambulance|dialysis|blood bank|radiology|x-?ray|CT|MRI|OT)\b", case=False)]
    bare = fac[fac["flags"].str.contains("bare_24x7_line")]
    chrome = u[u.field == "chrome_text"]
    m = {"usable_emergency_24x7_rows": len(em), "emergency_rows_with_phone_cue": len(phone), "records_with_emergency_24x7": len(rec_em),
         "records_whose_every_emergency_row_has_phone_cue": int(rec_phone_only.sum()),
         "usable_facility_24x7_rows": len(fac), "facility_24x7_naming_a_unit": len(unit), "facility_24x7_bare_line": len(bare),
         "usable_hour_rows_from_chrome_text": len(chrome), "usable_hour_rows": len(u)}
    ex = [f"{r.unique_id} emergency: {r.source_text[:80]!r}" for r in phone.sample(min(3, len(phone)), random_state=2).itertuples()] + \
         [f"{r.unique_id} facility: {r.source_text[:80]!r}" for r in unit.sample(min(2, len(unit)), random_state=2).itertuples()]
    share = len(phone) / max(1, len(em))
    return result("hours_error_patterns", "warn" if share > 0.05 else "pass", m, "emergency rows with a phone cue <= 5%",
                  f"phone cue regex: {PHONE_CUE.pattern}", ex)


def check_vf_error_patterns() -> dict:
    """The same patterns in vf_details usable text facts."""
    f = table("facts")
    u = f[(f.method != "structured") & f.status.isin(["ok", "flagged"]) & (f.polarity == "positive")]
    em = u[(u.fact_type == "hours_24x7") & (u.attribute == "emergency")]
    phone = em[em.source_text.str.contains(PHONE_CUE)]
    soon = u[u.source_text.str.contains(SOON)]
    bio = u[u.source_text.str.contains(BIO) & (u.fact_type != "staffing")]
    other = u[u.attribution.isin(["other_facility", "ambiguous"])]
    m = {"usable_text_facts": len(u), "emergency_24x7": len(em), "emergency_with_phone_cue": len(phone), "coming_soon_cue": len(soon),
         "doctor_bio_cue_non_staffing": len(bio), "attribution_other_or_ambiguous": len(other),
         "attribution_counts": u.attribution.value_counts().to_dict()}
    ex = [f"{r.fact_id}: {r.source_text[:80]!r}" for r in phone.head(2).itertuples()] + [f"{r.fact_id}: {r.source_text[:80]!r}" for r in soon.head(2).itertuples()] + \
         [f"{r.fact_id}: {r.source_text[:80]!r}" for r in bio.head(1).itertuples()]
    st = "warn" if (len(phone) / max(1, len(em)) > 0.05 or len(soon) / max(1, len(u)) > 0.01) else "pass"
    return result("vf_error_patterns", st, m, "phone-cue emergency <= 5%, coming-soon <= 1%", "usable text facts in kb/vf_details/out/facts.parquet", ex)


# ---------------------------------------------------------------- hand-judged sample (labels.py)
def _sample_scores() -> dict | None:
    sp = os.path.join(OUT, "sample.csv")
    if not os.path.exists(sp) or not os.path.exists(os.path.join(HERE, "labels.py")):
        return None
    sys.path.insert(0, HERE)
    from labels import LABELS
    s = pd.read_csv(sp, keep_default_na=False)
    s = s[s.n.isin(LABELS)]
    s["correct"] = s.n.map(lambda n: LABELS[n][0])
    s["error"] = s.n.map(lambda n: LABELS[n][1])
    return s


def _group_result(name: str, group: str, reported: tuple[int, int], s) -> dict:
    if s is None:
        return result(name, "warn", "not run", "", "out/sample.csv or labels.py missing", [])
    g = s[s.group == group]
    k, n = int(g.correct.sum()), len(g)
    st = g.groupby("stratum").agg(k=("correct", "sum"), n=("correct", "size"), N=("pop_n", "first"))
    w = st.N / st.N.sum()
    wp = round(float((w * st.k / st.n).sum()), 3)
    rk, rn = reported
    lo, hi = wilson(k, n)
    rlo, rhi = wilson(rk, rn) if rn else (None, None)
    overlap = rn == 0 or not (hi < rlo or lo > rhi)
    errs = g[~g.correct].error.value_counts().to_dict()
    m = {"k": k, "n": n, "p": round(k / n, 3) if n else None, "wilson95": (lo, hi), "population_weighted_p": wp,
         "by_stratum": {i: f"{int(r.k)}/{int(r.n)} {wilson(int(r.k), int(r.n))} N={int(r.N)}" for i, r in st.iterrows()},
         "reported_qa": f"{rk}/{rn} {wilson(rk, rn) if rn else ''}", "errors": errs}
    ex = [f"item {r.n} {r.stratum} {r.unique_id} {r.item}: {r.error}" for r in g[~g.correct].head(5).itertuples()]
    status = "fail" if wp < 0.6 else ("warn" if wp < 0.85 else "pass")
    return result(name, status, m, "population-weighted precision >= 0.85 pass, >= 0.6 warn", f"intervals overlap QA: {overlap}", ex)


def check_sample_web_services() -> dict:
    return _group_result("sample_web_services", "svc", (36, 60), _sample_scores())


def check_sample_web_hours() -> dict:
    return _group_result("sample_web_hours", "hrs", (22, 30), _sample_scores())


def check_sample_web_details() -> dict:
    return _group_result("sample_web_details", "det", (21, 30), _sample_scores())


def check_sample_site_identity() -> dict:
    return _group_result("sample_site_identity", "id", (23, 30), _sample_scores())


def check_sample_vf_details() -> dict:
    return _group_result("sample_vf_details", "vf", (46, 50), _sample_scores())


# ---------------------------------------------------------------- live liveness (liveness.py)
def check_site_liveness() -> dict:
    p = os.path.join(OUT, "liveness.json")
    if not os.path.exists(p):
        return result("site_liveness", "warn", "not run", "", "out/liveness.json missing; run liveness.py", [])
    rows = json.load(open(p))
    judged = [r for r in rows if r["agree"] is not None]
    k = sum(r["agree"] for r in judged)
    dis = [f"{r['target_id']} stored={r['stored']} now={r['live_class']} ({r['live_detail']})" for r in judged if not r["agree"]]
    m = {"sites": len(rows), "judged": len(judged), "agree": k, "wilson95": wilson(k, len(judged)), "not_fetched": len(rows) - len(judged),
         "by_stored_class": pd.DataFrame(judged).groupby("stored").agree.agg(lambda s: f"{int(s.sum())}/{len(s)}").to_dict() if judged else {}}
    st = "pass" if judged and k / len(judged) >= 0.85 else "warn"
    return result("site_liveness", st, m, "agreement >= 0.85", "fresh fetch, robots.txt respected, 1 req/s per domain; drift since crawl counts as disagreement", dis)


def check_model_feature_exposure() -> dict:
    """How the issues reach the model features built in viz/features/build_features.py (e_ family, lines 272-293)."""
    ss = table("web_service_summary")
    si = table("site_identity")
    att = si[si.attributable]
    pos = ss[ss.web_positive & ss.unique_id.isin(set(att.unique_id))]
    weak_1page = pos[~pos.web_positive_strong & (pos.n_pages_positive == 1)]
    only_medium = att.groupby("unique_id").confidence.agg(lambda c: set(c) == {"medium"})
    wh = table("web_hours")
    em = wh[(wh.status == "ok") & wh.attributable & (wh.fact_type == "hours_24x7") & (wh.attribute == "emergency")]
    phone_only = em.assign(p=em.source_text.str.contains(PHONE_CUE)).groupby("unique_id").p.all()
    wf = table("web_facility_details")
    nabh = wf[(wf.fact_type == "accreditation") & (wf.attribute == "NABH") & (wf.n_usable > 0)]
    not_full = nabh[nabh.value_text.isin(["pre_accreditation", "pre_entry_level"])]
    m = {"e_web_service_pairs": len(pos), "of_which_weak": int((~pos.web_positive_strong).sum()), "weak_single_page": len(weak_1page),
         "attributable_records": int(att.unique_id.nunique()), "records_attributable_only_via_medium_identity": int(only_medium.sum()),
         "e_web_24x7_emergency_records": int(em.unique_id.nunique()), "records_whose_every_row_has_phone_cue": int(phone_only.sum()),
         "e_web_nabh_claim_records": int(nabh.unique_id.nunique()), "nabh_pre_accreditation_only": len(not_full)}
    ex = [f"weak 1-page pair {r.unique_id} {r.service_id}: {r.best_quote[:60]!r}" for r in weak_1page.sample(3, random_state=3).itertuples()] + \
         [f"pre-accreditation NABH {r.unique_id}: {r.best_quote[:60]!r}" for r in not_full.head(2).itertuples()]
    return result("model_feature_exposure", "warn", m, "informational", "e_web_service counts weak pairs (sample precision 5/15 web-only weak); "
                  "e_identity_conf takes max confidence over all targets including medium", ex)


ALL = [v for k, v in sorted(globals().items()) if k.startswith("check_") and callable(v)]

if __name__ == "__main__":
    pick = set(sys.argv[1:])
    res = []
    for fn in ALL:
        if pick and fn.__name__ not in pick:
            continue
        try:
            r = fn()
        except Exception as e:  # a crashing check is a failed check, reported, never silent
            r = result(fn.__name__[6:], "fail", "error", "", f"{type(e).__name__}: {e}", [])
        res.append(r)
        print(json.dumps(r, default=str)[:1500], flush=True)
    os.makedirs(OUT, exist_ok=True)
    name = "checks.json" if not pick else "checks_partial.json"
    json.dump(res, open(os.path.join(OUT, name), "w"), indent=1, default=str)
