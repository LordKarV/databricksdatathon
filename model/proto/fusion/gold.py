"""Gold labels for fusion: v1 (36, all dev) and v2 (140, splits.json), with inclusion weights and label status.

Test rows are dropped before any label field is used unless the caller is the sealed evaluator
(environment variable FUSION_SEALED_EVAL=1, set only by eval_test.py).

Label status (rule fixed on dev notes, applied blind to test):
  checked    the labeller looked the pair up: service in {confirmed, contradicted}, or no_info with >= 1 evidence URL
  unchecked  service = no_info and no evidence URL. The v2 batches ran out of web-search budget; these pairs were
             never searched, so they carry no information about the facility and are treated as missing.
Primary target y = 1 if confirmed, else 0 (contract). Secondary y2 = confirmed vs contradicted (no_info dropped).
Inclusion probability (v2): pi = 5 / pool size of the (service, stratum) cell (sample_v2_stats.json). v1 pairs get
the pi of the same v2 cell (approximation: v1 used close but not identical stratum rules). Case weight = 1 / pi,
then scaled within each (split, stratum) by n_pairs / n_checked so that dropping unchecked pairs does not shift
the stratum mix (missing at random within a stratum, stated assumption), then normalised to mean 1.
"""
import glob
import json
import os

import numpy as np
import pandas as pd

from fcommon import ROOT

G = ROOT / "model/gold"
V1 = ROOT / "audit/ground_truth"


def _v2_labels():
    out = {}
    for f in sorted(glob.glob(str(G / "labels_p*.json"))):
        for r in json.load(open(f))["results"]:
            out[r["pair_id"]] = dict(r, location=r.get("location_ok"))
    return out


def _v1_labels():
    out = {}
    for f in ["web_1", "web_2", "web_3"]:
        for r in json.load(open(V1 / f"{f}.json"))["results"]:
            out[r["pair_id"]] = dict(r, location=r.get("location_matches"))
    return out


def load_gold(split: str = "dev") -> pd.DataFrame:
    if split != "dev" and os.environ.get("FUSION_SEALED_EVAL") != "1":
        raise PermissionError("test labels are read only by eval_test.py")
    sp = pd.DataFrame(json.load(open(G / "splits.json"))["pairs"])
    # contract: all 36 v1 pairs were read during design, so all are dev (training) data; the 17 that splits.json
    # marks test stay out of every headline metric. Headline test = v2 test only.
    sp = sp[((sp.version == "v1") | (sp.split == "dev"))] if split == "dev" else sp[(sp.version == "v2") & (sp.split == "test")]
    meta = {p["pair_id"]: p for p in json.load(open(G / "sample_v2.json"))}
    meta |= {p["pair_id"]: p for p in json.load(open(V1 / "sample.json"))}
    labels = _v1_labels() | _v2_labels()
    pools = json.load(open(G / "sample_v2_stats.json"))["pool_sizes"]
    rows = []
    for r in sp.itertuples():
        lab = labels.get(r.pair_id)
        if lab is None:
            continue
        n_url = len(lab.get("evidence_urls") or [])
        status = "unchecked" if lab["service"] == "no_info" and n_url == 0 else "checked"
        pool = pools.get(f"{r.service}_{r.stratum}")
        rows.append(dict(pair_id=r.pair_id, version=r.version, unique_id=r.unique_id, service=r.service, stratum=r.stratum,
                         split=split, split_orig=r.split, split_group=r.group, name=meta[r.pair_id]["name"],
                         label_service=lab["service"], label_exists=lab["exists"], label_location=lab["location"],
                         label_conf=lab.get("confidence"), n_evidence_urls=n_url, status=status,
                         y=int(lab["service"] == "confirmed"),
                         y2=None if lab["service"] == "no_info" else int(lab["service"] == "confirmed"),
                         pi=5.0 / pool if pool else np.nan))
    d = pd.DataFrame(rows)
    d["ipw"] = 1.0 / d.pi
    d["double_label"] = d.pair_id.isin(json.load(open(G / "overlap_v2.json")))
    return d


def case_weights(d: pd.DataFrame, checked_only: bool = True) -> pd.Series:
    """IPW with the within-stratum missingness correction, normalised to mean 1 over the rows kept."""
    keep = d.status.eq("checked") if checked_only else pd.Series(True, index=d.index)
    w = d.ipw.copy()
    for (_, _), g in d.groupby(["version", "stratum"]):
        k = keep[g.index].sum()
        if k:
            w[g.index] = w[g.index] * len(g) / k
    w = w.where(keep, 0.0)
    return w / w[keep].mean()


def overlap_kappa(d: pd.DataFrame) -> dict:
    """Cohen's kappa per field on the double-labelled pairs present in d (dev only when called by the builder)."""
    o = {}
    for f in sorted(glob.glob(str(G / "labels_o*.json"))):
        for r in json.load(open(f))["results"]:
            o[r["pair_id"]] = r
    prim = _v2_labels()
    out = {}
    for field, key in [("service", "service"), ("exists", "exists"), ("location", "location_ok")]:
        a, b = [], []
        for pid in d.pair_id:
            if pid in o and pid in prim:
                a.append(prim[pid][key]); b.append(o[pid][key])
        if not a:
            continue
        cats = sorted(set(a) | set(b))
        po = np.mean([x == y for x, y in zip(a, b)])
        pe = sum((a.count(c) / len(a)) * (b.count(c) / len(b)) for c in cats)
        out[field] = dict(n=len(a), agreement=round(float(po), 3), kappa=None if pe == 1 else round(float((po - pe) / (1 - pe)), 3))
    return out


if __name__ == "__main__":
    d = load_gold("dev")
    try:
        load_gold("test")
        raise AssertionError("guard failed")
    except PermissionError:
        pass
    w = case_weights(d)
    print(len(d), d.version.value_counts().to_dict(), d.status.value_counts().to_dict())
    print(pd.crosstab([d.version, d.status], d.label_service))
    print("checked y:", d[d.status == "checked"].y.value_counts().to_dict(), "ESS", round(w.sum() ** 2 / (w ** 2).sum(), 1))
    print("exists:", d[d.status == "checked"].label_exists.value_counts().to_dict(),
          "location:", d[d.status == "checked"].label_location.value_counts().to_dict())
    print("kappa dev overlap:", overlap_kappa(d))
