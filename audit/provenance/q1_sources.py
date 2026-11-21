"""Q1: source URLs, source types and ids; does source class predict contamination?
Outputs: q1_records.parquet (one row per well-formed facility), q1_results.json,
handcheck_*.csv samples for manual precision checks."""
import json
import re
import sys
from collections import Counter

import pandas as pd

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/provenance")
from common import OUT, facilities, host, jlist, norm_pin, norm_state, pin_states  # noqa: E402
from domains import classify  # noqa: E402
from proxies import (AFFILIATION_RX, _k, institution_mentions, is_foreign,  # noqa: E402
                     place_states, url_place)
from rapidfuzz import fuzz  # noqa: E402

CLASSES = ["official", "official_like", "other_health_site", "government", "wikipedia",
           "research", "docs_repo", "health_aggregator", "insurance_scheme", "business_dir",
           "maps_geo", "news", "social", "education", "crowdfunding_ngo", "other"]
# claims that read as extracted from a research paper rather than a service listing
RESEARCH_LANG = re.compile(
    r"\b(multi-?cent\w*|published|journal|cohort|retrospective|prospective|randomi[sz]ed|"
    r"et al|authors?|consortium|cross-sectional|case report|case series|we report|"
    r"was conducted|were included|patients were|subjects|study period|"
    r"(?:study|trial) (?:was|enrolled|recruited|included|documented|population|site|evaluat\w*)|"
    r"(?:in|of) (?:a|an|the) (?:\d{4} )?(?:[\w-]+ ){0,4}(?:study|trial))\b", re.I)
PROXIES = ("p1_pin_state_mismatch", "p2_url_cross_state", "p3_foreign_name",
           "p3c_foreign_claim", "p3s_similar_name", "p4_coord_far_from_pin", "any_proxy")
LIST_PAGE = re.compile(r"(network-hospital|/nct-|/places/|/villages/|/listing/|hospitals-in|"
                       r"list-of|/search|/directory|empanel|/category/|top-\d+|best-)", re.I)


# Stated-vs-PIN state pairs that are not contamination: Hyderabad-area records stated as Andhra
# Pradesh (pre-2014 state), Mohali/Panchkula stated as Chandigarh, NCR suburbs stated as Delhi.
COMPATIBLE = [{"ANDHRA PRADESH", "TELANGANA"}, {"CHANDIGARH", "PUNJAB", "HARYANA"},
              {"DELHI", "UTTAR PRADESH", "HARYANA"}]


def state_conflict(stated, pin_sts):
    if stated in pin_sts:
        return False
    return not any(stated in g and pin_sts & g for g in COMPATIBLE)


GENERIC_SLUG = {"hospital", "hospitals", "clinic", "clinics", "dental", "medical", "care",
                "health", "healthcare", "centre", "center", "multispeciality", "speciality",
                "super", "nursing", "home", "research", "institute", "diagnostic", "diagnostics",
                "eye", "children", "child", "women", "mother", "city", "general", "india", "the",
                "and", "sri", "shri", "shree", "new", "life", "lifeline"}


def url_kind(url, name, cls):
    """'about' when the URL is the record's own site or its path carries a distinctive word of
    the facility name; 'list' for category/listing pages; else 'unverified'."""
    if cls in ("official", "official_like"):
        return "about"
    path = set(re.findall(r"[a-z]+", re.sub(r"^[a-z]+://[^/]+", "", url.lower())))
    core = re.split(r"\s[-\u2013|(]\s?|,", name or "")[0].lower()  # drop address tails
    toks = {t for t in re.findall(r"[a-z]{4,}", core) if t not in GENERIC_SLUG}
    if toks and toks & path:
        return "about"
    if LIST_PAGE.search(url):
        return "list"
    return "unverified"


def official_hosts(r):
    w = r.officialWebsite
    return {host(w)} if isinstance(w, str) and w not in ("null", "") else set()


def record_row(r, pst, places):
    urls = jlist(r.source_urls)
    off = official_hosts(r)
    classes = [classify(host(u), off, r["name"]) for u in urls]
    cc = Counter(classes)
    kinds = Counter(url_kind(u, r["name"], c) for u, c in zip(urls, classes))
    stated = norm_state(r.address_stateOrRegion)
    pin = norm_pin(r.address_zipOrPostcode)
    ps = pst.get(pin) if pin else None
    p1 = None if (stated is None or ps is None) else state_conflict(stated, ps)
    # P2: compare URL places with stated state (fall back to PIN state when unambiguous)
    ref = stated or (next(iter(ps)) if ps and len(ps) == 1 else None)
    own_city = _k(r.address_city)
    p2_hits = []
    for u in urls:
        pl = url_place(u)
        if not pl or ref is None:
            continue
        kind, key = pl
        if kind == "state":
            if key != ref:
                p2_hits.append(u)
        elif key != own_city:
            st = places.get(key)
            if st and len(st) == 1 and ref not in st:
                p2_hits.append(u)
    claims = [(k, x) for k in ("procedure", "equipment", "capability") for x in jlist(r[k])]
    own_places = {own_city, _k(r.address_line2), _k(r.address_line3)} - {""}
    p3_hits = []
    for k, x in claims:
        for m in institution_mentions(x):
            if is_foreign(m, r["name"], own_places):
                p3_hits.append((k, m, x))
    # P3c: foreign mention in a sentence that is not a staff/affiliation/landmark mention,
    # i.e. the sentence asserts something about the other institution itself
    p3c = [(k, m, x) for k, m, x in p3_hits if not AFFILIATION_RX.search(x)]
    # similar-name merges (Kamal vs Kamat): foreign phrase close to the record's own name
    p3s = [(k, m, x) for k, m, x in p3c
           if fuzz.token_sort_ratio(m.lower(), (r["name"] or "").lower()) >= 70]
    res_lang = sum(bool(RESEARCH_LANG.search(x)) for _, x in claims)
    return {
        "unique_id": r.unique_id, "name": r["name"], "city": r.address_city,
        "state_raw": r.address_stateOrRegion, "state_norm": stated, "pin": pin,
        "pin_states": "|".join(sorted(ps)) if ps else None,
        "n_urls": len(urls), "n_hosts": len({host(u) for u in urls}),
        "n_list_urls": sum(bool(LIST_PAGE.search(u)) for u in urls),
        "n_url_about": kinds.get("about", 0), "n_url_list": kinds.get("list", 0),
        "n_url_unverified": kinds.get("unverified", 0),
        "n_source_ids_distinct": len(set(jlist(r.source_ids))),
        "source_types": "|".join(sorted(set(jlist(r.source_types)))),
        **{f"n_{c}": cc.get(c, 0) for c in CLASSES},
        "n_claims": len(claims), "n_research_lang_claims": res_lang,
        "p1_pin_state_mismatch": p1, "p2_url_cross_state": len(p2_hits) > 0 if ref else None,
        "p2_examples": json.dumps(p2_hits[:3]), "p3_foreign_name": len(p3_hits) > 0,
        "n_p3_claims": len({x for _, _, x in p3_hits}),
        "p3_examples": json.dumps([[k, m, x[:300]] for k, m, x in p3_hits[:3]]),
        "p3c_foreign_claim": len(p3c) > 0, "n_p3c_claims": len({x for _, _, x in p3c}),
        "p3c_examples": json.dumps([[k, m, x[:300]] for k, m, x in p3c[:3]]),
        "p3s_similar_name": len(p3s) > 0,
        "p3s_examples": json.dumps([[k, m, x[:300]] for k, m, x in p3s[:3]]),
    }


def rate(s):
    s = s.dropna().astype(bool)
    return {"flagged": int(s.sum()), "of": int(len(s)),
            "pct": round(100 * s.mean(), 2) if len(s) else None}


def main():
    df = facilities()
    pst, places = pin_states(), place_states()
    rec = pd.DataFrame([record_row(r, pst, places) for _, r in df.iterrows()])
    shared = df.content_table_id.map(df.content_table_id.value_counts())
    rec["content_id_group_size"] = shared.values
    # P4 needs q3_pincode.py output: facility lat/lon > 50 km from its PIN's directory centroid
    km = pd.read_parquet(f"{OUT}/facility_coord_pin_km.parquet")
    rec = rec.merge(km, on="unique_id", how="left")
    rec["p4_coord_far_from_pin"] = (rec.coord_pin_km > 50).where(rec.coord_pin_km.notna())
    rec["any_proxy"] = rec[["p1_pin_state_mismatch", "p2_url_cross_state", "p3c_foreign_claim",
                            "p4_coord_far_from_pin"]].fillna(False).astype(bool).any(axis=1)
    rec.to_parquet(f"{OUT}/q1_records.parquet", index=False)

    n = len(rec)
    tot_urls = int(rec.n_urls.sum())
    res = {"records": n, "urls_total": tot_urls,
           "records_with_zero_urls": int((rec.n_urls == 0).sum()),
           "url_count_quantiles": rec.n_urls.quantile([.1, .25, .5, .75, .9, .99]).to_dict(),
           "distinct_source_ids_quantiles":
               rec.n_source_ids_distinct.quantile([.25, .5, .75, .9]).to_dict(),
           "records_gt1_distinct_source_id": int((rec.n_source_ids_distinct > 1).sum()),
           "list_page_urls": int(rec.n_list_urls.sum()),
           "url_kind_totals": {k: int(rec[f"n_url_{k}"].sum()) for k in ("about", "list", "unverified")},
           "records_with_zero_about_urls": int((rec.n_url_about == 0).sum()),
           "source_types_combos": rec.source_types.value_counts().head(12).to_dict()}
    res["url_share_by_class"] = {c: {"urls": int(rec[f"n_{c}"].sum()),
                                     "pct_urls": round(100 * rec[f"n_{c}"].sum() / tot_urls, 2),
                                     "records_with": int((rec[f"n_{c}"] > 0).sum())}
                                 for c in CLASSES}
    for p in PROXIES:
        res[f"base_{p}"] = rate(rec[p])
    # proxy rate with vs without each class, overall and within URL-count strata
    rec["url_bucket"] = pd.cut(rec.n_urls, [-1, 5, 10, 20, 1000],
                               labels=["0-5", "6-10", "11-20", "21+"])
    by = {}
    for c in CLASSES:
        has = rec[f"n_{c}"] > 0
        by[c] = {}
        for p in PROXIES:
            strata = {str(b): {"with": rate(g.loc[g[f"n_{c}"] > 0, p]),
                               "without": rate(g.loc[g[f"n_{c}"] == 0, p])}
                      for b, g in rec.groupby("url_bucket", observed=True)}
            by[c][p] = {"with": rate(rec.loc[has, p]), "without": rate(rec.loc[~has, p]),
                        "by_url_bucket": strata}
    res["proxy_by_class"] = by
    res["proxy_by_url_bucket"] = {str(b): {p: rate(g[p]) for p in
                                           PROXIES}
                                  for b, g in rec.groupby("url_bucket", observed=True)}
    sid = pd.cut(rec.n_source_ids_distinct, [-1, 0, 1, 3, 10, 1000],
                 labels=["0", "1", "2-3", "4-10", "11+"])
    res["proxy_by_distinct_source_ids"] = {
        str(b): {p: rate(g[p]) for p in PROXIES}
        for b, g in rec.groupby(sid, observed=True)}
    # research vector: research-language claims in records with / without research URLs
    hr = rec.n_research > 0
    res["research_vector"] = {
        "records_with_research_url": int(hr.sum()),
        "research_urls": int(rec.n_research.sum()),
        "claims_in_research_records": int(rec.loc[hr, "n_claims"].sum()),
        "research_lang_claims_in_research_records": int(rec.loc[hr, "n_research_lang_claims"].sum()),
        "claims_in_other_records": int(rec.loc[~hr, "n_claims"].sum()),
        "research_lang_claims_in_other_records": int(rec.loc[~hr, "n_research_lang_claims"].sum()),
        "p3_claims_in_research_records": int(rec.loc[hr, "n_p3_claims"].sum()),
        "p3_claims_in_other_records": int(rec.loc[~hr, "n_p3_claims"].sum()),
        "p3c_claims_in_research_records": int(rec.loc[hr, "n_p3c_claims"].sum()),
        "p3c_claims_in_other_records": int(rec.loc[~hr, "n_p3c_claims"].sum()),
        "median_urls_research_records": float(rec.loc[hr, "n_urls"].median()),
        "records_with_research_lang_claim": int((rec.n_research_lang_claims > 0).sum()),
        # claim-level foreign-claim rate within URL-count strata, research vs not
        "p3c_claim_rate_by_url_bucket": {
            str(b): {k: {"p3c_claims": int(g.loc[m, "n_p3c_claims"].sum()),
                         "claims": int(g.loc[m, "n_claims"].sum()),
                         "records": int(m.sum())}
                     for k, m in (("research", g.n_research > 0), ("no_research", g.n_research == 0))}
            for b, g in rec.groupby("url_bucket", observed=True)},
        "median_urls_other_records": float(rec.loc[~hr, "n_urls"].median()),
    }
    sh = rec.content_id_group_size > 1
    res["content_table_id"] = {
        "distinct": int(df.content_table_id.nunique()),
        "equals_source_content_id": int((df.content_table_id == df.source_content_id).sum()),
        "equals_unique_id": int((df.content_table_id == df.unique_id).sum()),
        "records_sharing_with_other_records": int(sh.sum()),
        "groups_shared": int(df.content_table_id[sh.values].nunique()),
        "max_group_size": int(rec.content_id_group_size.max()),
        "proxy_shared_vs_not": {p: {"shared": rate(rec.loc[sh, p]), "not": rate(rec.loc[~sh, p])}
                                for p in PROXIES}}
    # cross-validation: proxies built from different fields should co-occur if both are real
    p4 = rec.p4_coord_far_from_pin
    res["p4_rate_given_other_proxy"] = {
        p: {"given_flag": rate(p4[rec[p].fillna(False).astype(bool)]),
            "given_no_flag": rate(p4[~rec[p].fillna(False).astype(bool)])}
        for p in ("p2_url_cross_state", "p3c_foreign_claim", "p3s_similar_name")}
    res["cluster_id_distinct"] = int(df.cluster_id.nunique())
    res["source_column_values"] = df.source.value_counts().to_dict()
    with open(f"{OUT}/q1_results.json", "w") as f:
        json.dump(res, f, indent=1, default=str)

    # hand-check samples
    rec[rec.p3_foreign_name].sample(40, random_state=11)[
        ["unique_id", "name", "city", "p3_examples"]].to_csv(f"{OUT}/handcheck_p3.csv", index=False)
    rec[rec.p3c_foreign_claim].sample(40, random_state=12)[
        ["unique_id", "name", "city", "p3c_examples"]].to_csv(f"{OUT}/handcheck_p3c.csv", index=False)
    rec[rec.p3s_similar_name].sample(30, random_state=12)[
        ["unique_id", "name", "city", "p3s_examples"]].to_csv(f"{OUT}/handcheck_p3s.csv", index=False)
    rec[rec.p2_url_cross_state.fillna(False)].sample(30, random_state=11)[
        ["unique_id", "name", "city", "state_norm", "p2_examples"]].to_csv(
        f"{OUT}/handcheck_p2.csv", index=False)
    rec[rec.p1_pin_state_mismatch.fillna(False)][
        ["unique_id", "name", "city", "state_raw", "pin", "pin_states"]].to_csv(
        f"{OUT}/handcheck_p1.csv", index=False)
    print(json.dumps({k: v for k, v in res.items() if k.startswith("base_") or
                      k in ("records", "urls_total", "research_vector")}, indent=1))


if __name__ == "__main__":
    main()
