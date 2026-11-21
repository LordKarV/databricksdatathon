"""Labels for the feature study. DEV split only for gold; official-list positive-unlabeled (PU) labels.

Gold (model/gold/splits.json): only pairs with split == "dev" are read. That is stricter than
model/proto/fusion/gold.py, which also trains on the 17 v1 pairs that splits.json marks test; those
17 stay out here. Labels come from model/gold/labels_p*.json (v2) and audit/ground_truth/web_*.json
(v1). Target y = 1 if the web check confirmed the service, 0 if contradicted or searched (at least
one evidence URL) with nothing found; never-searched pairs are missing (as MODEL_SPEC 3.2).
Inclusion weight ipw = pool size / 5 for the (service, stratum) cell (sample_v2_stats.json), as in
fusion/gold.py. Location target: location_ok yes = 1, no = 0, one row per facility.

PU labels:
  nabh_codes     population: NABH-matched facilities with at least one of the 7 fetched specialty
                 codes (1,054 facilities) x the 4 services with a code. y = NABH lists the code.
                 Positive-unlabeled: a missing code is not a negative, NABH codes are self-declared.
  official_lists all 69,713 pairs. y = 1 if any official list speaks for the pair: NABH code,
                 NMC strong course, LaQshya Maternity OT (current or expired), MoHFW trauma list.
"""
from __future__ import annotations

import glob
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/karthikvattem/projects/datathon")
G = ROOT / "model/gold"


def _labels() -> dict:
    out = {}
    for f in sorted(glob.glob(str(G / "labels_p*.json"))):
        for r in json.load(open(f))["results"]:
            out[r["pair_id"]] = dict(r, location=r.get("location_ok"))
    for f in ["web_1", "web_2", "web_3"]:
        for r in json.load(open(ROOT / f"audit/ground_truth/{f}.json"))["results"]:
            out[r["pair_id"]] = dict(r, location=r.get("location_matches"))
    return out


def gold_dev() -> pd.DataFrame:
    sp = pd.DataFrame(json.load(open(G / "splits.json"))["pairs"])
    sp = sp[sp.split == "dev"]  # sealed test: never read
    labs = _labels()
    pools = json.load(open(G / "sample_v2_stats.json"))["pool_sizes"]
    rows = []
    for r in sp.itertuples():
        lab = labs.get(r.pair_id)
        if lab is None:
            continue
        urls = lab.get("evidence_urls") or []
        searched = not (lab["service"] == "no_info" and len(urls) == 0)
        pool = pools.get(f"{r.service}_{r.stratum}")
        rows.append(dict(pair_id=r.pair_id, unique_id=r.unique_id, service=r.service, stratum=r.stratum,
                         version=r.version, group=r.group, label_service=lab["service"],
                         label_location=lab["location"], label_exists=lab["exists"], searched=searched,
                         y=float(lab["service"] == "confirmed") if searched else np.nan,
                         ipw=pool / 5.0 if pool else np.nan, evidence_urls=urls))
    return pd.DataFrame(rows)


def pu_labels(feat: pd.DataFrame) -> pd.DataFrame:
    """Return feat[[unique_id, service]] with pu_nabh (NaN outside its population) and pu_lists."""
    d = feat[["unique_id", "service"]].copy()
    in_pop = (feat.d_nabh_code_known == 1) & feat.d_nabh_service_code.notna()
    d["pu_nabh"] = np.where(in_pop, feat.d_nabh_service_code, np.nan)
    pos = ((feat.d_nabh_service_code == 1) | (feat.d_nmc_course_strong == 1) |
           (feat.d_laqshya_ot_ever == 1) | (feat.d_mohfw_trauma_centre == 1))
    d["pu_lists"] = pos.astype(float)
    return d


def _domain(u: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", u).split("/")[0].lower()


def evidence_overlap(dev: pd.DataFrame) -> dict:
    """How often the gold labeller's evidence came from a page the features also read (DEV only)."""
    su = pd.read_parquet(ROOT / "derived/v1/source_urls.parquet", columns=["unique_id", "domain", "host"])
    rec_dom = su.groupby("unique_id").domain.apply(lambda s: set(s.str.lower()))
    tg = pd.read_parquet(ROOT / "kb/crawl/targets.parquet").explode("unique_ids")
    own = tg.groupby("unique_ids").domain.apply(lambda s: set(s.dropna().str.lower()))
    n_pairs = n_url = 0
    hit = dict(record_source_domain=0, own_website=0, nabh_portal=0, any_of_these=0)
    for r in dev[dev.evidence_urls.apply(len) > 0].itertuples():
        n_pairs += 1
        doms = {_domain(u) for u in r.evidence_urls}
        regs = {".".join(x.split(".")[-2:]) for x in doms}
        rs, ow = rec_dom.get(r.unique_id, set()), own.get(r.unique_id, set())
        a = bool((doms | regs) & rs)
        b = bool((doms | regs) & ow)
        c = any("nabh" in x for x in doms)
        hit["record_source_domain"] += a
        hit["own_website"] += b
        hit["nabh_portal"] += c
        hit["any_of_these"] += a or b or c
        n_url += len(r.evidence_urls)
    return dict(dev_pairs_with_evidence_urls=n_pairs, evidence_urls=n_url, pairs_hit=hit,
                note="A pair is hit when any evidence URL's domain (or registrable domain) is among the record's "
                     "cited source domains (derived/v1/source_urls), its crawled own-site domain (kb/crawl/targets), "
                     "or contains 'nabh'. DEV split only.")


if __name__ == "__main__":
    d = gold_dev()
    assert (d.y.notna().sum(), int(d.y.sum())) == (61, 22), (d.y.notna().sum(), d.y.sum())
    print(len(d), "dev pairs;", int(d.y.notna().sum()), "searched;", int(d.y.sum()), "confirmed")
    print(evidence_overlap(d))
