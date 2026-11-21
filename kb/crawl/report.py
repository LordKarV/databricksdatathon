"""Crawl report: targets, runtime, liveness, pages, coverage by state and facility type, an
identity check and a content teaser. Reads kb/crawl/*.parquet, data/crawl/runs.jsonl and the
stored page text; writes kb/crawl/crawl_stats.json, coverage_by_state.csv, coverage_by_type.csv."""
import gzip
import json
import math
import re
import sys

import pandas as pd
from rapidfuzz import fuzz

ROOT = "/Users/karthikvattem/projects/datathon"
KB = f"{ROOT}/kb/crawl"
sys.path.insert(0, f"{ROOT}/audit/provenance")
from domains import name_key  # noqa: E402

REACHABLE = {"ok", "ok_thin"}
GROUPS = {
    "dead_or_unreachable": {"dns_fail", "connect_error", "timeout", "tls_error", "protocol_error", "http_5xx"},
    "live_but_not_this_facility": {"hijacked_spam", "parked_or_for_sale", "suspended_or_expired", "redirect_unverified",
                                   "redirect_third_party", "http_4xx", "empty", "too_many_redirects", "non_html"},
    "blocked_by_site_policy": {"robots_disallow", "robots_txt_forbidden", "robots_txt_5xx", "crawl_delay_too_long"},
}
TEASER = {
    "mentions_24x7": r"24\s?[x*/]\s?7|24\s?hours|round the clock|24-hour",
    "opd_or_timings": r"\bopd\b.{0,40}\d|timings?\s*[:\-]|\d{1,2}(:\d\d)?\s?(am|a\.m\.)\s?(to|-)\s?\d{1,2}(:\d\d)?\s?(pm|p\.m\.)",
    "dialysis": r"dialysis|haemodialysis|hemodialysis",
    "nabh": r"\bnabh\b",
    "beds_number": r"\b\d{2,4}\s?(-|\s)?(bed|beds|bedded)\b",
    "insurance_or_pmjay": r"cashless|\btpa\b|ayushman|pm-?jay|empanel",
}
TEASER_RX = {k: re.compile(v, re.I) for k, v in TEASER.items()}


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [float("nan"), float("nan")]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 3), round(c + h, 3)]


def main() -> None:
    sites = pd.read_parquet(f"{KB}/sites.parquet")
    pages = pd.read_parquet(f"{KB}/pages.parquet")
    tstats = json.load(open(f"{KB}/targets_stats.json"))
    loc = pd.read_parquet(f"{ROOT}/cleaning/geo_identity/facility_location.parquet", columns=["unique_id", "name", "state_final"])
    loc = loc.drop_duplicates("unique_id")
    raw = pd.read_parquet(f"{ROOT}/data/raw/facilities.parquet", columns=["unique_id", "facilityTypeId"]).drop_duplicates("unique_id")
    meta = loc.merge(raw, on="unique_id", how="left").set_index("unique_id")
    runs = [json.loads(x) for x in open(f"{ROOT}/data/crawl/runs.jsonl") if x.strip()]

    st = {}
    st["runtime"] = {"runs": len(runs), "seconds_total": round(sum(r["seconds"] for r in runs), 1),
                     "minutes_total": round(sum(r["seconds"] for r in runs) / 60, 1),
                     "note": "includes a 122 s smoke run whose output was discarded (robots parser bug) and recrawled"}
    st["targets"] = {k: tstats[k] for k in ("usable_records", "records_with_official_candidate", "sites",
                                            "registrable_domains", "shared_sites", "targets_by_kind", "targets_total")}
    st["targets_attempted"] = len(sites)
    st["sites_attempted"] = int(sites.site.nunique())
    site_ok = sites.groupby("site").site_status.agg(lambda s: bool(set(s) & REACHABLE))
    st["sites_reachable"] = int(site_ok.sum())
    st["targets_reachable"] = int(sites.site_status.isin(REACHABLE).sum())
    st["targets_by_status"] = sites.site_status.value_counts().to_dict()
    st["targets_by_group"] = {g: int(sites.site_status.isin(v).sum()) for g, v in GROUPS.items()}
    st["targets_by_group"]["reachable"] = st["targets_reachable"]
    st["flags"] = {k: int(sites[c].fillna(False).astype(bool).sum()) for k, c in
                   (("tls_invalid_cert", "site_tls_invalid"), ("http_fallback", "site_http_fallback"),
                    ("redirect_same_org", "site_redirect_same_org"), ("under_construction", "site_under_construction"),
                    ("spam_injected", "site_spam_injected"), ("relabelled_at_index", "site_relabelled"))
                   if c in sites}

    stored = pages[pages.path.notna()].copy()
    stored = stored.merge(sites[["target_id", "site_status", "kind"]], on="target_id", how="left")
    st["pages"] = {
        "attempts": len(pages), "stored": len(stored),
        "stored_on_reachable_targets": int(stored.site_status.isin(REACHABLE).sum()),
        "distinct_text_hash": int(stored.text_hash.nunique()),
        "by_role": stored.role.str.split(":").str[0].value_counts().to_dict(),
        "link_pages_by_keyword_group": stored.role[stored.role.str.startswith("link")].str[5:].value_counts().to_dict(),
        "text_len_median": float(stored.text_len.median()), "text_len_p90": float(stored.text_len.quantile(0.9)),
        "empty_text": int((stored.text_len == 0).sum()), "truncated_2mb": int(pages.truncated.fillna(False).sum()),
        "fallback_full_text": int(stored.fallback_text.fillna(False).sum()),
        "with_last_modified_header": int(stored.last_modified.notna().sum()),
        "lang": stored.lang.value_counts().to_dict(),
        "page_errors": pages.error.value_counts().to_dict(),
    }

    # coverage: a record is covered when a facility-specific target (own site or branch page) is reachable
    ex = sites.explode("unique_ids").rename(columns={"unique_ids": "unique_id"})
    ex["reach"] = ex.site_status.isin(REACHABLE)
    spec = ex[ex.kind != "shared_home"].groupby("unique_id").reach.any()
    chain = ex[ex.kind == "shared_home"].groupby("unique_id").reach.any()
    m = meta.copy()
    m["has_candidate"] = m.index.isin(ex.unique_id)
    m["covered_own_site"] = m.index.map(spec).fillna(False).astype(bool)
    m["covered_chain_home_only"] = (~m.covered_own_site) & m.index.map(chain).fillna(False).astype(bool)
    m["state"] = m.state_final.fillna("UNKNOWN")
    m["ftype"] = m.facilityTypeId.fillna("null").astype(str)
    agg = dict(records=("name", "size"), with_candidate=("has_candidate", "sum"), covered_own_site=("covered_own_site", "sum"),
               chain_home_only=("covered_chain_home_only", "sum"))
    by_state = m.groupby("state").agg(**agg).sort_values("records", ascending=False)
    by_state["share_covered"] = (by_state.covered_own_site / by_state.records).round(3)
    by_type = m.groupby("ftype").agg(**agg).sort_values("records", ascending=False)
    by_type["share_covered"] = (by_type.covered_own_site / by_type.records).round(3)
    by_state.to_csv(f"{KB}/coverage_by_state.csv")
    by_type.to_csv(f"{KB}/coverage_by_type.csv")
    st["coverage"] = {"records": len(m), "covered_own_site": int(m.covered_own_site.sum()),
                      "covered_chain_home_only": int(m.covered_chain_home_only.sum()),
                      "states_with_any_covered_record": int((by_state.covered_own_site > 0).sum()),
                      "states_total": len(by_state), "by_type": by_type.to_dict("index")}

    # identity + teaser over reachable facility-specific targets: read every stored page once
    tgt = sites[sites.site_status.isin(REACHABLE) & (sites.kind != "shared_home")]
    tp = stored[stored.target_id.isin(set(tgt.target_id))].groupby("target_id").path.apply(list)
    ident, teaser = {}, {k: 0 for k in TEASER}
    for t in tgt.itertuples():
        txt = []
        for p in tp.get(t.target_id, []):
            d = json.load(gzip.open(f"{ROOT}/{p}", "rt"))
            txt.append(f"{d['title']}\n{d['text']}\n{d['chrome_text']}")
        blob = "\n".join(txt)
        flat = re.sub(r"[^a-z0-9]", "", blob.lower())
        keys = [k for k in (name_key(meta.name.get(u, "")) for u in t.unique_ids) if len(k) >= 5]
        if keys:
            ident[t.target_id] = any(fuzz.partial_ratio(k, flat) >= 90 for k in keys)
        for k, rx in TEASER_RX.items():
            teaser[k] += bool(rx.search(blob))
    k, n = sum(ident.values()), len(ident)
    st["identity_check"] = {"definition": "reachable own-site/branch targets whose stored text contains the distinctive "
                                          "part of a linked record's name (fuzzy partial ratio >= 90; names with a "
                                          "distinctive key of 5+ chars)", "matched": k, "n": n,
                            "share": round(k / n, 3) if n else None, "wilson95": wilson(k, n)}
    st["content_teaser"] = {"denominator_reachable_specific_targets": len(tgt),
                            "targets_with_match": teaser, "patterns": TEASER}
    hc = st.setdefault("hand_checks", {})
    hc["dns_fail_recheck_8888"] = {"resolved": 0, "n": 40, "wilson95_false_dns_fail": wilson(0, 40)}
    hc["hijacked_spam_sample"] = {"correct": 25, "n": 25, "wilson95": wilson(25, 25)}
    hc["redirect_unverified_census_before_final_relabel"] = {
        "n": 67, "same_org_rebrand_or_acquired": 25, "different_org_or_junk": 29, "unclear": 13,
        "note": "every redirect_unverified target was labelled by eye from landing URL and title; some junk ones "
                "were later relabelled hijacked_spam by the injected-spam rule"}
    hc["parked_or_for_sale_sample_v1"] = {"correct": 8, "n": 10, "wilson95": wilson(8, 10),
                                          "note": "first version; the false positive (dan.com inside netranidan.com) is fixed"}
    try:
        st["gov_probe"] = [json.loads(x) for x in open(f"{KB}/gov_probe.jsonl")]
    except FileNotFoundError:
        st["gov_probe"] = "not run"
    json.dump(st, open(f"{KB}/crawl_stats.json", "w"), indent=1, default=str)
    print(json.dumps({k: v for k, v in st.items() if k not in ("coverage",)}, indent=1, default=str))
    print(by_type.to_string())
    print(by_state.to_string())


if __name__ == "__main__":
    assert wilson(25, 25)[0] > 0.86 and wilson(0, 40)[1] < 0.09
    main()
