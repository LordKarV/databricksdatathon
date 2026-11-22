"""Independent recomputation of headline numbers in viz/features/FEATURES.md.

Written from scratch for the review: reads raw inputs (not out/features_pairs.parquet) wherever the
feature is simple to rebuild, its own gold-DEV loader, and sklearn's roc_auc_score. Gold: split == "dev"
only (model/gold/splits.json); the TEST split is filtered out before any label is looked at.
Run: /Users/karthikvattem/projects/datathon/.venv-viz/bin/python viz/features/review/recompute.py
"""
import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

R = Path("/Users/karthikvattem/projects/datathon")
rng = np.random.default_rng(7)
OUT = {}


def dev_labels():
    sp = pd.DataFrame(json.load(open(R / "model/gold/splits.json"))["pairs"])
    dev_ids = set(sp.loc[sp.split == "dev", "pair_id"])  # filter first: test pair ids never enter the dict
    lab = {}
    files = sorted(glob.glob(str(R / "model/gold/labels_p*.json"))) + [str(R / f"audit/ground_truth/web_{i}.json") for i in (1, 2, 3)]
    for f in files:
        for r in json.load(open(f))["results"]:
            if r["pair_id"] in dev_ids:
                lab[r["pair_id"]] = r
    d = sp[sp.split == "dev"].copy()
    d["svc_lab"] = d.pair_id.map(lambda p: lab[p]["service"] if p in lab else None)
    d["urls"] = d.pair_id.map(lambda p: lab.get(p, {}).get("evidence_urls") or [])
    d["loc_lab"] = d.pair_id.map(lambda p: lab.get(p, {}).get("location_ok", lab.get(p, {}).get("location_matches")))
    searched = ~((d.svc_lab == "no_info") & (d.urls.apply(len) == 0))
    d["y"] = np.where(searched, (d.svc_lab == "confirmed").astype(float), np.nan)
    return d


def boot_auc(x, y, g, b=2000):
    x, y, g = np.asarray(x, float), np.asarray(y, float), np.asarray(g)
    ok = ~np.isnan(x) & ~np.isnan(y)
    x, y, g = x[ok], y[ok], g[ok]
    pt = roc_auc_score(y, x)
    ug = np.unique(g)
    idx = {k: np.where(g == k)[0] for k in ug}
    bs = []
    for _ in range(b):
        sel = np.concatenate([idx[k] for k in rng.choice(ug, len(ug))])
        if len(np.unique(y[sel])) == 2:
            bs.append(roc_auc_score(y[sel], x[sel]))
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return dict(n=int(len(y)), pos=int(y.sum()), auc=round(pt, 3), lo=round(lo, 3), hi=round(hi, 3))


def main():
    d = dev_labels()
    pf = pd.read_parquet(R / "model/proto/evidence/pair_features.parquet")
    su = pd.read_parquet(R / "derived/v1/source_urls.parquet", columns=["unique_id", "source_class"])
    fd = pd.read_parquet(R / "kb/vf_details/out/facility_details.parquet")
    nabh_txt = set(fd[(fd.fact_type == "accreditation") & (fd.attribute == "NABH") & (fd.n_usable > 0)].unique_id)
    nurl = su.groupby("unique_id").size()
    ff = pd.read_parquet(R / "model/proto/evidence/facility_features.parquet").set_index("unique_id")
    fl = pd.read_parquet(R / "derived/v1/facility_location.parquet").set_index("unique_id")
    x = d.merge(pf[["unique_id", "service", "n_atoms", "n_specialties", "facility_type"]], on=["unique_id", "service"], how="left")
    x["n_urls"] = x.unique_id.map(nurl)
    x["text_nabh"] = x.unique_id.isin(nabh_txt).astype(float)
    x["hospital"] = (x.facility_type == "hospital").astype(float)
    x["votes_against"] = x.unique_id.map(ff.n_votes_against).astype(float)
    x["loc_conf"] = x.unique_id.map(fl.loc_conf.map({"high": 3, "medium": 2, "low": 1, "disputed": 0})).astype(float)
    s = x[x.y.notna()]
    OUT["dev_searched_confirmed"] = [int(len(s)), int(s.y.sum())]
    for col, name in [("n_atoms", "a_n_atoms"), ("text_nabh", "k_text_nabh"), ("n_specialties", "g_n_specialties"),
                      ("n_urls", "c_n_urls"), ("hospital", "g_type_hospital")]:
        OUT[f"dev_service_auc[{name}]"] = boot_auc(s[col], s.y, s.group)
    h = s.groupby("hospital").y.agg(["sum", "count"])
    OUT["g_type_hospital_2x2"] = {f"hospital={int(k)}": f"{int(v['sum'])}/{int(v['count'])} confirmed" for k, v in h.iterrows()}
    loc = x[x.loc_lab.isin(["yes", "no"])].drop_duplicates("unique_id")
    yl = (loc.loc_lab == "yes").astype(float)
    OUT["dev_location_n_wrong"] = [int(len(loc)), int((yl == 0).sum())]
    for col, name in [("n_urls", "c_n_urls"), ("votes_against", "b_votes_against"), ("loc_conf", "b_loc_conf")]:
        OUT[f"dev_location_auc[{name}]"] = boot_auc(loc[col], yl, loc.group)
    for v in ["v1", "v2"]:
        m = loc.version == v
        if yl[m].nunique() == 2:
            OUT[f"dev_location_auc[b_loc_conf, {v} only]"] = boot_auc(loc[m].loc_conf, yl[m], loc[m].group, 500)
        OUT[f"dev_location_n[{v}]"] = [int(m.sum()), int((yl[m] == 0).sum())]
    # pre-override v1 location score (score_model) vs the shipped one: does the 1.00 come from the gold override?
    dp = pd.read_parquet(R / "derived/v1/data_point_scores.parquet", columns=["dp_type", "unique_id", "score", "score_model"])
    dl = dp[dp.dp_type == "location"].set_index("unique_id")
    OUT["dev_location_auc[c_location_score_v1 as shipped]"] = boot_auc(loc.unique_id.map(dl.score), yl, loc.group, 500)
    OUT["dev_location_auc[v1 score_model, before gold override]"] = boot_auc(loc.unique_id.map(dl.score_model), yl, loc.group, 500)

    # NABH dialysis: of facilities NABH lists with DIA/NPH, how many does the text mention dialysis for
    nb = pd.read_parquet(R / "data/external/nabh_accredited/nabh_vf_match.parquet")
    nb = nb[nb.accept]
    codes = nb.groupby("unique_id").nabh_specs.apply(lambda s: set().union(*[set(v) if v is not None else set() for v in s]))
    for svc, cs in {"dialysis": {"DIA", "NPH"}, "emergency_csection": {"OBG"}}.items():
        ids = set(codes[codes.apply(lambda c: bool(c & cs))].index)
        p = pf[(pf.service == svc) & pf.unique_id.isin(ids)]
        OUT[f"nabh_{svc}"] = dict(nabh_listed=int(len(p)), text_T_ge1=int((p["T"] >= 1).sum()),
                                  any_atom=int((p.n_atoms > 0).sum()))
    # silent pairs: text level 0 vs no atom at all
    OUT["pairs_T0"] = int((pf["T"] == 0).sum())
    OUT["pairs_no_atom"] = int((pf.n_atoms == 0).sum())
    OUT["pairs_atom_but_T0"] = int(((pf.n_atoms > 0) & (pf["T"] == 0)).sum())
    OUT["pairs_total"] = int(len(pf))
    # registrable-domain shortcut in labels.evidence_overlap: how many DEV evidence URLs reduce to a public suffix
    regs = [".".join(u.split("//")[-1].split("/")[0].lower().removeprefix("www.").split(".")[-2:]) for us in d.urls for u in us]
    OUT["evidence_regdomain_counts_top"] = pd.Series(regs).value_counts().head(15).to_dict()
    su_dom = pd.read_parquet(R / "derived/v1/source_urls.parquet", columns=["domain"]).domain.str.lower()
    OUT["source_domains_that_are_public_suffixes"] = {k: int((su_dom == k).sum()) for k in ["co.in", "gov.in", "org.in", "nic.in", "ac.in", "net.in"]}
    print(json.dumps(OUT, indent=1, default=str))
    (Path(__file__).parent / "recompute.json").write_text(json.dumps(OUT, indent=1, default=str))


if __name__ == "__main__":
    main()


def nabh_code_split():
    """Chart 12 check: split the 488 'dialysis' NABH facilities into DIA (dialysis) and NPH-only (nephrology)."""
    pf = pd.read_parquet(R / "model/proto/evidence/pair_features.parquet", columns=["unique_id", "service", "n_atoms"])
    nb = pd.read_parquet(R / "data/external/nabh_accredited/nabh_vf_match.parquet")
    nb = nb[nb.accept].set_index("unique_id").nabh_specs.apply(lambda v: set(v) if v is not None else set())
    mention = set(pf[(pf.service == "dialysis") & (pf.n_atoms > 0)].unique_id)
    res = {}
    for lab, m in {"DIA listed": nb.apply(lambda c: "DIA" in c),
                   "NPH only (no DIA)": nb.apply(lambda c: "NPH" in c and "DIA" not in c),
                   "DIA or NPH": nb.apply(lambda c: bool(c & {"DIA", "NPH"}))}.items():
        ids = set(nb[m].index)
        res[lab] = dict(n=len(ids), text_mentions_dialysis=len(ids & mention))
    return res


if __name__ == "__main__":
    r = nabh_code_split()
    print(json.dumps(r, indent=1))
    p = Path(__file__).parent / "recompute.json"
    j = json.loads(p.read_text()); j["nabh_dialysis_by_code"] = r; p.write_text(json.dumps(j, indent=1))
