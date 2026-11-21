"""Per-facility summaries of the web facts, and the comparison of the web evidence with the provided VF dataset.

Inputs: out/*.parquet from build_web_evidence.py; kb/taxonomy/out/lexicon_matches.parquet and specialty_map.csv (the
dataset's service claims, same lexicon); data/raw/facilities.parquet (specialties, source_urls).
Writes out/web_service_summary.parquet, out/web_facility_details.parquet, out/compare_by_service.csv, out/stats_compare.json.

Population: usable records with an attributable own site or branch page (identity high or medium; chain homepages never
count). Dataset claim for (record, service): a positive claim sentence (taxonomy rule: no non-offer cue, not attributed
to another facility, not a staff or directory sentence) or a specialties value mapped to the service.
- confirm: share of dataset claims with a positive web quote for the service.
- web_only: share of positive web pairs with no dataset mention at all (no matched sentence of any polarity, no
  mapped specialty).
- silent: share of dataset claims with no web match of any polarity, counted only where the site has a services,
  specialty or facilities page. The crawl stored at most 6 pages per site, so silence is weak evidence of absence.
Independence: VF text was itself scraped from web pages. A record whose source_urls include the crawled site's host may
have its dataset text copied from that same site, so confirm is reported for both groups.
Run: /Users/karthikvattem/projects/datathon/.venv/bin/python compare_dataset.py
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import re

import sys

import duckdb
import pandas as pd

ROOT = "/Users/karthikvattem/projects/datathon"
D = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(D, "out")
sys.path.insert(0, f"{ROOT}/kb/vf_details")
_spec = importlib.util.spec_from_file_location("vf_extract", f"{ROOT}/kb/vf_details/extract.py")
VE = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(VE)
SERVICE_IDS = [s["id"] for c in json.load(open(f"{ROOT}/kb/taxonomy/services.json"))["categories"] for s in c["services"]]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    if n == 0:
        return None, None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(c - h, 3), round(c + h, 3)


def rate(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": int(k), "n": int(n), "rate": round(k / n, 3) if n else None, "wilson_lo": lo, "wilson_hi": hi}


def service_summary(svc: pd.DataFrame) -> pd.DataFrame:
    """One row per (record, service) over attributable rows: counts and the best positive quote (services page, a
    sentence rather than a menu item, main text before chrome)."""
    a = svc[svc.attributable].assign(r=lambda x: (~x.services_page) * 4 + (x.line_kind == "item") * 2 + (x.field == "chrome_text") * 1)
    rows = []
    for (u, s), g in a.groupby(["unique_id", "service_id"], sort=False):
        pos = g[g.positive].assign(r=lambda x: x.r + (x.strength != "strong") * 8).sort_values("r")
        best = pos.iloc[0] if len(pos) else g.sort_values("r").iloc[0]
        rows.append({"unique_id": u, "service_id": s, "web_positive": len(pos) > 0, "web_positive_strong": bool((pos.strength == "strong").any()), "n_positive_rows": len(pos),
                     "n_positive_quotes": pos.quote.nunique(), "n_pages_positive": pos.page_id.nunique(),
                     "n_negated_rows": int(g.negated.sum()), "n_rows": len(g),
                     "positive_on_services_page": bool(pos.services_page.any()), "positive_sentence": bool((pos.line_kind == "sentence").any()),
                     "best_quote": best.quote, "best_url": best.final_url, "best_field": best.field, "best_fetched_at": best.fetched_at,
                     "best_positive": bool(best.positive), "identity_conf": best.identity_conf, "scope": best.scope})
    return pd.DataFrame(rows)


def dataset_claims(usable: set[str]) -> pd.DataFrame:
    m = pd.read_parquet(f"{ROOT}/kb/taxonomy/out/lexicon_matches.parquet")
    pos = m[(m.nonoffer_cue == "") & ~m.negation_extra & (m.attribution != "other_facility") & ~m.kind.isin(["staff", "directory"])]
    smap = pd.read_csv(f"{ROOT}/kb/taxonomy/specialty_map.csv", keep_default_na=False)[["specialty", "service_id"]]
    smap = smap.assign(service_id=smap.service_id.str.split(";")).explode("service_id")
    sp = duckdb.sql(f"""select distinct unique_id, s as specialty from (select unique_id, unnest(from_json(specialties, '["VARCHAR"]')) s
                        from read_parquet('{ROOT}/data/raw/facilities.parquet') where json_valid(specialties))""").df().merge(smap, on="specialty")
    keys = lambda df, col: set(zip(df.unique_id, df[col]))
    t_any, t_pos, spec = keys(m, "service"), keys(pos, "service"), keys(sp, "service_id")
    allk = {k for k in t_any | spec if k[0] in usable and k[1] in SERVICE_IDS}
    return pd.DataFrame([{"unique_id": u, "service_id": s, "text_any": (u, s) in t_any, "text_pos": (u, s) in t_pos, "spec": (u, s) in spec} for u, s in allk])


def source_overlap(si: pd.DataFrame) -> pd.DataFrame:
    """Per (record, site): does the record's VF source_urls list a page on this host?"""
    raw = pd.read_parquet(f"{ROOT}/data/raw/facilities.parquet", columns=["unique_id", "source_urls"]).drop_duplicates("unique_id")
    host = lambda u: re.sub(r"^(www|m)\.", "", re.sub(r"^https?://", "", u.strip().lower()).split("/")[0])
    hosts = {r.unique_id: {host(x) for x in (json.loads(r.source_urls) if isinstance(r.source_urls, str) and r.source_urls.startswith("[") else []) if isinstance(x, str)}
             for r in raw.itertuples()}
    return si.assign(site_in_vf_sources=[s in hosts.get(u, set()) for u, s in zip(si.unique_id, si.site)])


def compare(svc_sum: pd.DataFrame, si: pd.DataFrame, svc: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    own = si[si.attributable & si.kind.isin(["site", "branch"])]
    pop = set(own.unique_id)
    has_sp = set(own[own.has_services_page].unique_id)
    same_src = set(own[own.site_in_vf_sources].unique_id)
    dc = dataset_claims(pop)
    web_pos = set(zip(svc_sum[svc_sum.web_positive].unique_id, svc_sum[svc_sum.web_positive].service_id))
    web_strong = set(zip(svc_sum[svc_sum.web_positive_strong].unique_id, svc_sum[svc_sum.web_positive_strong].service_id))
    a = svc[svc.attributable & svc.scope.isin(["own_site", "branch_page"])]
    web_any = set(zip(a.unique_id, a.service_id))
    wp_own = {k for k in web_pos if k[0] in pop}
    claim = dc[dc.text_pos | dc.spec].assign(k=lambda x: list(zip(x.unique_id, x.service_id)))
    claim = claim.assign(conf=claim.k.isin(web_pos), conf_strong=claim.k.isin(web_strong), any_web=claim.k.isin(web_any), sp=claim.unique_id.isin(has_sp), same=claim.unique_id.isin(same_src))
    mention = set(zip(dc[dc.text_any | dc.spec].unique_id, dc[dc.text_any | dc.spec].service_id))
    rows = []
    for s in SERVICE_IDS + ["ALL"]:
        c = claim if s == "ALL" else claim[claim.service_id == s]
        w = wp_own if s == "ALL" else {k for k in wp_own if k[1] == s}
        ws = {k for k in w if k in web_strong}
        txt, spo = c[c.text_pos], c[~c.text_pos]
        sil = c[c.sp]
        r = {"service_id": s, "dataset_claims": len(c), "confirmed": int(c.conf.sum()),
             "confirm_rate": rate(c.conf.sum(), len(c))["rate"], "confirm_lo": rate(c.conf.sum(), len(c))["wilson_lo"], "confirm_hi": rate(c.conf.sum(), len(c))["wilson_hi"],
             "confirm_rate_strong": rate(c.conf_strong.sum(), len(c))["rate"],
             "claims_text": len(txt), "confirm_rate_text": rate(txt.conf.sum(), len(txt))["rate"],
             "claims_specialty_only": len(spo), "confirm_rate_specialty_only": rate(spo.conf.sum(), len(spo))["rate"],
             "confirm_rate_site_not_in_vf_sources": rate(c[~c.same].conf.sum(), (~c.same).sum())["rate"],
             "confirm_rate_site_in_vf_sources": rate(c[c.same].conf.sum(), c.same.sum())["rate"],
             "web_positive_pairs": len(w), "web_only": len(w - mention), "web_only_rate": rate(len(w - mention), len(w))["rate"],
             "web_only_lo": rate(len(w - mention), len(w))["wilson_lo"], "web_only_hi": rate(len(w - mention), len(w))["wilson_hi"],
             "web_strong_pairs": len(ws), "web_only_strong": len(ws - mention), "web_only_strong_rate": rate(len(ws - mention), len(ws))["rate"],
             "claims_with_services_page": len(sil), "silent": int((~sil.any_web).sum()), "silent_rate": rate((~sil.any_web).sum(), len(sil))["rate"],
             "silent_lo": rate((~sil.any_web).sum(), len(sil))["wilson_lo"], "silent_hi": rate((~sil.any_web).sum(), len(sil))["wilson_hi"]}
        rows.append(r)
    st = {"population_records": len(pop), "population_with_services_page": len(has_sp), "population_site_in_vf_sources": len(same_src),
          "all": rows[-1]}
    return pd.DataFrame(rows), st


def main() -> None:
    si = source_overlap(pd.read_parquet(os.path.join(OUT, "site_identity.parquet")))
    svc = pd.read_parquet(os.path.join(OUT, "web_services.parquet"))
    ss = service_summary(svc)
    ss.to_parquet(os.path.join(OUT, "web_service_summary.parquet"), index=False)
    facts = pd.concat([pd.read_parquet(os.path.join(OUT, f)) for f in ("web_hours.parquet", "web_details.parquet")], ignore_index=True)
    facts = facts[facts.attributable].assign(attribution="own_anchored", claim_id=lambda x: x.segment_id)
    fd = VE.facility_table(facts).merge(facts[["fact_id", "final_url", "fetched_at"]].rename(columns={"fact_id": "best_fact_id", "final_url": "best_url"}), on="best_fact_id", how="left")
    fd = fd.drop(columns=["claim_ids", "best_claim_id"]).rename(columns={"fields": "page_fields"})
    fd.to_parquet(os.path.join(OUT, "web_facility_details.parquet"), index=False)
    cmp, st = compare(ss, si, svc)
    cmp.to_csv(os.path.join(OUT, "compare_by_service.csv"), index=False)
    st["service_summary_rows"] = len(ss)
    st["records_with_web_positive_service"] = int(ss[ss.web_positive].unique_id.nunique())
    st["facility_details_rows"] = len(fd)
    json.dump(st, open(os.path.join(OUT, "stats_compare.json"), "w"), indent=1, default=int)
    print(json.dumps(st, indent=1, default=int))
    print(cmp[["service_id", "dataset_claims", "confirm_rate", "confirm_rate_text", "confirm_rate_specialty_only", "confirm_rate_site_not_in_vf_sources",
               "confirm_rate_site_in_vf_sources", "confirm_rate_strong", "web_positive_pairs", "web_only_rate", "web_strong_pairs", "web_only_strong_rate", "claims_with_services_page", "silent_rate"]].to_string(index=False))


if __name__ == "__main__":
    main()
