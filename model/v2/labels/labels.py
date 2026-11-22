"""Training labels for Witness Ledger v2: gold DEV labels, positive-unlabeled list labels, c estimates, cross-fit plan.

Reads derived/v2 (assemble step), model/gold (v1 and v2 pairs, all DEV under MODEL_SPEC 3.1 change 5), the e2e
benchmark labels, model/gold/v3/dev_labels.json if present (never any other v3 file), and the external list matches
through model/v2/assemble/external.x_lists (same matches, thresholds and scopes as the features).
Writes parquet under out/ and out/stats.json. Run: /Users/karthikvattem/projects/datathon/.venv-viz/bin/python labels.py
"""
from __future__ import annotations

import glob
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/karthikvattem/projects/datathon")
HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
sys.path.insert(0, str(ROOT / "model/v2/assemble"))
import acommon as A  # noqa: E402  (paths, services, precision registry, wilson)
import external as XT  # noqa: E402  (list matches and scopes, reused unchanged)

G = ROOT / "model/gold"
V1 = ROOT / "audit/ground_truth"
V3_DEV = G / "v3/dev_labels.json"   # the only v3 file this script may open
LIST_SITES = r"nabh\.co|nmc\.org\.in|nhsrc|eraktkosh|mohfw\.gov\.in|pmndp"
MIN_POS_FOR_C = 10                  # positives in scope needed before a c estimate is used
C_PRIOR = (0.5, 0.1, 0.9)           # documented fallback when no anchor reaches MIN_POS_FOR_C
VERSION_RANK = {"v3_dev": 0, "v2": 1, "v1": 2, "e2e": 3}  # which label wins when a pair is labelled twice


def fold5(group: str) -> int:
    """Deterministic grouped fold, the same for every table, so cross-fitting folds line up."""
    return int(hashlib.sha256(f"labels-v2:{group}".encode()).hexdigest(), 16) % 5


def facility_frame() -> pd.DataFrame:
    ff = pd.read_parquet(A.OUT / "facility_features.parquet", columns=["unique_id", "service", "leakage_group_id", "a_T", "e_web_cell"])
    fl = pd.read_parquet(ROOT / "derived/v1/facility_location.parquet", columns=["unique_id", "state_final"])
    fac = ff.drop_duplicates("unique_id")[["unique_id", "leakage_group_id"]].merge(fl, on="unique_id", how="left")
    fac["leakage_group_id"] = fac.leakage_group_id.astype(str)
    fac["fold5"] = fac.leakage_group_id.map(fold5)
    assert len(fac) == 9959 and fac.unique_id.is_unique
    return fac.rename(columns={"state_final": "state"}), ff


# ---------------------------------------------------------------- 1. gold DEV labels
def _results(files: list[str]) -> list[dict]:
    return [r | {"batch": Path(f).stem} for f in files for r in json.load(open(f))["results"]]


def load_gold() -> pd.DataFrame:
    meta = {p["pair_id"]: p | {"version": "v2"} for p in json.load(open(G / "sample_v2.json"))}
    meta |= {p["pair_id"]: p | {"version": "v1"} for p in json.load(open(V1 / "sample.json"))}
    meta |= {p["pair_id"]: p | {"version": "e2e", "stratum": "e2e_pool"}
             for p in json.load(open(ROOT / "model/proto/decision/e2e_pairs_to_label.json"))}
    labs = _results(sorted(glob.glob(str(G / "labels_p*.json")))) + _results([str(V1 / f"web_{i}.json") for i in (1, 2, 3)]) \
        + _results(sorted(glob.glob(str(G / "labels_e*.json"))))
    if V3_DEV.exists():  # teammate's extra DEV labels; same result schema expected, fail loudly otherwise
        v3 = json.load(open(V3_DEV))
        v3 = v3["results"] if isinstance(v3, dict) else v3
        for r in v3:
            for k in ("pair_id", "unique_id", "service", "exists", "location_ok"):
                if k not in r:
                    raise KeyError(f"v3 dev label missing {k}: {r.get('pair_id')}")
            meta[r["pair_id"]] = dict(unique_id=r["unique_id"], service=r["service"], stratum=r.get("stratum", "v3"), version="v3_dev")
        labs += [r | {"batch": "v3_dev"} for r in v3]
    second = {r["pair_id"]: r for r in _results(sorted(glob.glob(str(G / "labels_o*.json"))))}
    pools = json.load(open(G / "sample_v2_stats.json"))["pool_sizes"]
    split_orig = {p["pair_id"]: p["split"] for p in json.load(open(G / "splits.json"))["pairs"]}
    rows = []
    for r in labs:
        m = meta[r["pair_id"]]
        svc_raw = m["service"]
        svc = A.ALIASES.get(svc_raw, svc_raw)
        assert svc in A.SERVICES, svc
        urls = r.get("evidence_urls") or []
        loc = r.get("location_ok", r.get("location_matches"))
        searched = len(urls) > 0
        s = r["service"]
        assert s in ("confirmed", "contradicted", "no_info"), s
        # MODEL_SPEC 3.2: confirmed 1; contradicted 0; searched but nothing 0; never searched missing
        y_s = 1.0 if s == "confirmed" else (0.0 if s == "contradicted" or searched else np.nan)
        o = second.get(r["pair_id"])
        pool = pools.get(f"{svc_raw}_{m['stratum']}")
        rows.append(dict(
            pair_id=r["pair_id"], version=m["version"], batch=r["batch"], unique_id=m["unique_id"], service=svc,
            service_raw=svc_raw, stratum=m["stratum"], split_orig=split_orig.get(r["pair_id"], "none"), split="dev",
            label_service=s, label_exists=r["exists"], label_location=loc, label_conf=r.get("confidence"),
            n_evidence_urls=len(urls), searched=searched, evidence_urls=json.dumps(urls),
            gold_cites_list=bool(re.search(LIST_SITES, " ".join(urls))),
            y_S=y_s,
            # y_L: yes 1, no 0; unclear is not evidence of a wrong place, so missing
            y_L={"yes": 1.0, "no": 0.0}.get(loc, np.nan),
            # y_E mirrors the y_S rule (prototype fit.existence_rows): yes 1; no, or searched and unclear, 0
            y_E=1.0 if r["exists"] == "yes" else (0.0 if r["exists"] == "no" or searched else np.nan),
            y_E_strict={"yes": 1.0, "no": 0.0}.get(r["exists"], np.nan),
            second_service=o["service"] if o else None, second_exists=o["exists"] if o else None,
            second_location=o.get("location_ok") if o else None,
            pi=5.0 / pool if (pool and m["version"] in ("v1", "v2")) else np.nan))
    d = pd.DataFrame(rows)
    d["ipw"] = 1.0 / d.pi
    d["_r"] = d.version.map(VERSION_RANK)
    d = d.sort_values(["unique_id", "service", "_r", "pair_id"])
    d["primary"] = ~d.duplicated(["unique_id", "service"])
    d["dup_conflict"] = d.groupby(["unique_id", "service"]).y_S.transform(lambda x: x.dropna().nunique() > 1)
    return d.drop(columns="_r").reset_index(drop=True)


def location_extra(fac: pd.DataFrame) -> pd.DataFrame:
    """Facility location labels outside the gold pairs, read exactly as the prototype P_L fit read them (MODEL_SPEC 3.3)."""
    p1 = pd.read_parquet(A.OUT / "facility_features.parquet", columns=["unique_id", "p1_src"]).drop_duplicates("unique_id").set_index("unique_id").p1_src
    hv = pd.read_csv(ROOT / "audit/geo/hand_check_verdicts.csv")
    col = {"listing_coordinates": "coords_ok", "postcode_centre": "pin_ok", "address_city_centre": "stated_state_ok"}
    rows = []
    for r in hv.itertuples():
        c = col.get(p1.get(r.unique_id))
        v = getattr(r, c) if c else None
        if v in ("yes", "no"):
            rows.append(dict(unique_id=r.unique_id, y_L=float(v == "yes"), src="geo_hand_check", basis=f"{c} for p1_src {p1.get(r.unique_id)}"))
    hc = pd.read_csv(ROOT / "model/proto/fusion/inputs_snapshot/handcheck_location.csv")
    pre = {u[:8]: u for u in fac.unique_id}
    for r in hc.itertuples():
        if r.chosen_right in ("yes", "no") and r.uid8 in pre:
            rows.append(dict(unique_id=pre[r.uid8], y_L=float(r.chosen_right == "yes"), src="cleaning_hand_check", basis=r.rule))
    return pd.DataFrame(rows)


def facility_gold(gold: pd.DataFrame, fac: pd.DataFrame) -> pd.DataFrame:
    """One row per (facility, source) for the P_L and P_E heads. Gold: first labelled pair by VERSION_RANK."""
    g = gold.assign(_r=gold.version.map(VERSION_RANK)).sort_values(["unique_id", "_r", "pair_id"])
    conf_L = g.groupby("unique_id").y_L.agg(lambda x: x.dropna().nunique() > 1)
    conf_E = g.groupby("unique_id").y_E.agg(lambda x: x.dropna().nunique() > 1)
    first = lambda col: g.dropna(subset=[col]).drop_duplicates("unique_id").set_index("unique_id")[col]  # noqa: E731
    gf = pd.DataFrame({"unique_id": g.unique_id.unique()})
    for c in ("y_L", "y_E", "y_E_strict"):
        gf[c] = gf.unique_id.map(first(c))
    gf["pair_ids"] = gf.unique_id.map(g.groupby("unique_id").pair_id.agg(lambda x: ",".join(x)))
    gf["conflict_L"] = gf.unique_id.map(conf_L)
    gf["conflict_E"] = gf.unique_id.map(conf_E)
    gf = gf.assign(src="gold_dev", basis="first labelled pair (v3_dev > v2 > v1 > e2e)")
    ex = location_extra(fac)
    ex = ex[~ex.unique_id.isin(gf.unique_id[gf.y_L.notna()])]  # gold location wins (prototype order)
    ex = ex.drop_duplicates("unique_id")
    out = pd.concat([gf, ex], ignore_index=True)
    return out.merge(fac, on="unique_id", how="left")


# ---------------------------------------------------------------- 2. positive-unlabeled list labels
LIST_SERVICES = {  # label family -> services it labels (the task's list-to-service map; e-RaktKosh prerequisite rows are not labels)
    "nabh": sorted({s for v, _ in XT.NABH_CODE_SVC.values() for s in v}),
    "nmc": sorted(XT.NMC_COURSES),
    "laqshya": ["emergency_csection", "institutional_delivery"],
    "mohfw_tcf": ["trauma_care"],
    "eraktkosh": ["blood_bank"],
    "pmndp_goa": ["dialysis"],
}


def pu_labels(fac: pd.DataFrame) -> pd.DataFrame:
    attrs = pd.read_parquet(A.OUT / "facility_attributes.parquet", columns=["unique_id", "operator", "facility_level", "facility_type"])
    rec = attrs[["unique_id"]].merge(fac[["unique_id", "state"]].rename(columns={"state": "state_final"}), on="unique_id")
    xr, xobs, _ = XT.x_lists(rec, attrs)
    out = []
    for lst, svcs in LIST_SERVICES.items():
        o = xobs[(xobs.list == lst) & xobs.service.isin(svcs)]
        o = o[o.observability != "not_observable"]          # outside the list's scope: excluded, never unlabeled
        x = xr[(xr.source_key == lst) & xr.service.isin(svcs)]
        x = x.sort_values("value", ascending=False).drop_duplicates(["unique_id", "service"])
        d = o.merge(x[["unique_id", "service", "witness", "role", "value", "value_text", "evidence_id", "evidence_url",
                       "fetched_date", "quote"]], on=["unique_id", "service"], how="left")
        k, n = A.PRECISION[lst][:2]
        d["label_family"] = lst
        d["match_precision"] = k / n
        d["match_k"], d["match_n"] = k, n
        expired = d.witness.eq("laqshya_expired")
        d["label"] = np.where(d.observability == "present", np.where(expired, "excluded_expired", "positive"), "unlabeled")
        # positive weight = match precision x witness value (assemble: 1.0 strong, 0.5 NMC support course)
        d["weight"] = np.where(d.label == "positive", d.match_precision * d.value.fillna(1.0), np.where(d.label == "unlabeled", 1.0, 0.0))
        out.append(d.drop(columns=["observability", "list"]))
    pu = pd.concat(out, ignore_index=True).merge(fac, on="unique_id", how="left")
    assert not pu.duplicated(["label_family", "service", "unique_id"]).any()
    assert (pu.weight[pu.label == "positive"] > 0).all() and pu.label.isin(["positive", "unlabeled", "excluded_expired"]).all()
    return pu


# ---------------------------------------------------------------- c (Elkan and Noto label frequency)
def c_estimates(pu: pd.DataFrame, gold: pd.DataFrame, ff: pd.DataFrame) -> pd.DataFrame:
    """c = P(list positive | service offered, in the list's scope), estimated on three anchor sets of known positives:
    gold  DEV pairs with y_S = 1 (a web check confirmed it)
    web   pairs whose own website has a cell A or B service quote (QA 13/13 and 3/3; independent of the lists)
    text  pairs with own-text level T >= 4 (units in 2+ fields; independent of the lists)
    Each is a selected sample of positives, not a random one (SCAR does not hold), so each c is anchor-conditional."""
    gpos = gold[gold.primary & (gold.y_S == 1)][["unique_id", "service"]].assign(anchor="gold")
    gpos_nolist = gold[gold.primary & (gold.y_S == 1) & ~gold.gold_cites_list][["unique_id", "service"]].assign(anchor="gold_no_list_url")
    web = ff[ff.e_web_cell.isin(["A", "B"])][["unique_id", "service"]].assign(anchor="web_AB")
    txt = ff[ff.a_T >= 4][["unique_id", "service"]].assign(anchor="text_T4")
    anchors = pd.concat([gpos, gpos_nolist, web, txt])
    sc = pu[pu.label != "excluded_expired"][["label_family", "service", "unique_id", "label"]]
    m = anchors.merge(sc, on=["unique_id", "service"])
    rows = []
    for (lst, anc), g in m.groupby(["label_family", "anchor"]):
        for svc, h in list(g.groupby("service")) + [("ALL", g)]:
            k, n = int((h.label == "positive").sum()), len(h)
            lo, hi = (max(0.0, v) for v in A.wilson(k, n))
            rows.append(dict(label_family=lst, service=svc, anchor=anc, k=k, n=n, c=round(k / n, 4), c_lo=lo, c_hi=hi))
    c = pd.DataFrame(rows)
    used = []
    for lst, svcs in LIST_SERVICES.items():
        for svc in svcs + ["ALL"]:
            pick = None
            # this service on gold, web, text anchors; then the list's pooled estimate in the same order
            for where, anc in [(svc, a) for a in ("gold", "web_AB", "text_T4")] + [("ALL", a) for a in ("gold", "web_AB", "text_T4")]:
                r = c[(c.label_family == lst) & (c.service == where) & (c.anchor == anc)]
                if len(r) and r.n.iloc[0] >= MIN_POS_FOR_C:
                    pick = r.iloc[0].copy()
                    pick["service"], pick["anchor"] = svc, anc if where == svc else f"{anc}_pooled_over_list"
                    break
            if pick is None:
                used.append(dict(label_family=lst, service=svc, anchor="documented_prior", k=np.nan, n=np.nan,
                                 c=C_PRIOR[0], c_lo=C_PRIOR[1], c_hi=C_PRIOR[2], used=True))
            else:
                used.append(dict(pick.to_dict(), used=True))
    c["used"] = False
    return pd.concat([c, pd.DataFrame(used)], ignore_index=True)


# ---------------------------------------------------------------- 3. cross-fitting plan
SOURCE_COLUMNS = {  # facility_features columns computed from each label family's source
    "nabh": ["d_nabh_service_code", "d_nabh_listed", "d_nabh_full_accreditation"],
    "nmc": ["d_nmc_course_strong"],
    "laqshya": ["d_laqshya_ot_valid", "d_laqshya_ot_ever", "d_laqshya_labour_room"],
    "mohfw_tcf": ["d_mohfw_trauma_centre"],
    "eraktkosh": ["d_erk_blood_centre_on_site", "d_erk_nearest_km"],
    "pmndp_goa": [],
}
LIST_AGGREGATES = ["x_any_list", "obs_X"]  # built from every list, so they carry the label list too
SCOPE_COLUMNS = {  # the list's scope is defined on these (selection, FEATURES.md): allowed, near-constant within scope
    "nabh": ["d_nabh_listed"], "nmc": [], "laqshya": ["operator_public", "g_public_level", "g_iphs_prior", "g_iphs_essential"],
    "mohfw_tcf": ["operator_public", "g_type_hospital"], "eraktkosh": ["g_type_hospital"], "pmndp_goa": ["operator_public"],
}
PROXY_COLUMNS = {"nabh": ["k_text_nabh"]}  # FEATURES.md leak 'shared': record text says NABH; not the list, flag only
GOLD_FITTED = ["b_loc_conf", "b_coord_pin_km"]  # tuned on gold (FEATURES.md 'fitted'; ASSEMBLE.md leakage notes)
GOLD_SHARED = ["e_site_alive", "e_identity_conf", "e_web_hours_found", "e_web_service", "e_web_cell", "e_web_negated",
               "e_web_24x7_emergency", "web_state", "obs_W", "c_n_urls", "c_log2_n_urls", "c_share_social", "b_website_other_org"]


def crossfit_plan(gold: pd.DataFrame) -> pd.DataFrame:
    rows = []
    gold_svcs = sorted(gold.service.unique())
    for svc in A.SERVICES:
        for lst, svcs in LIST_SERVICES.items():
            if svc not in svcs:
                continue
            rows.append(dict(
                service=svc, label_family=lst, label_table="pu_labels.parquet",
                drop_witness_rows=f"family X, source_key {lst}, every service (pooled fits included)",
                drop_columns=SOURCE_COLUMNS[lst] + LIST_AGGREGATES,
                ablate_columns=PROXY_COLUMNS.get(lst, []), scope_columns=SCOPE_COLUMNS[lst],
                keep_note="other lists' X rows stay; add back x_any_list / obs_X only if rebuilt without " + lst))
        if svc in gold_svcs:
            rows.append(dict(
                service=svc, label_family="gold_web_check", label_table="gold_dev_pairs.parquet",
                drop_witness_rows="none by source; R rows if the reader (issue #50) was trained on gold pairs",
                drop_columns=GOLD_FITTED, ablate_columns=GOLD_SHARED,
                scope_columns=[],
                keep_note="X lists stay as features (never gold labels); pairs with gold_cites_list read the NABH portal, "
                          "so report the NABH-feature weight with and without them; T C N S P D are 'design' (gold strata were drawn on them)"))
        rows.append(dict(service=svc, label_family="location_and_existence (facility)", label_table="gold_dev_facility.parquet",
                         drop_witness_rows="none", drop_columns=GOLD_FITTED, ablate_columns=["d_nabh_listed", "f_osm_match", "f_osm_conflict"],
                         scope_columns=[], keep_note="facility head, one row per facility; selection-tagged location features are matcher gates"))
    p = pd.DataFrame(rows).drop_duplicates(subset=["service", "label_family"])
    for c in ("drop_columns", "ablate_columns", "scope_columns"):
        p[c] = p[c].map(lambda x: ",".join(x))
    return p


def check_columns(plan: pd.DataFrame) -> None:
    cols = set(pd.read_parquet(A.OUT / "facility_features.parquet").columns)
    named = {c for s in plan.drop_columns.tolist() + plan.ablate_columns.tolist() + plan.scope_columns.tolist() for c in s.split(",") if c}
    missing = named - cols
    assert not missing, f"plan names columns that are not in facility_features: {missing}"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    fac, ff = facility_frame()
    gold = load_gold().merge(fac, on="unique_id", how="left")
    assert gold.leakage_group_id.notna().all(), "gold facility missing from derived/v2"
    # MODEL_SPEC 3.2 target rule
    assert gold[(gold.label_service == "no_info") & ~gold.searched].y_S.isna().all()
    assert (gold[gold.label_service == "contradicted"].y_S == 0).all() and (gold[gold.label_service == "confirmed"].y_S == 1).all()
    assert (gold[(gold.label_service == "no_info") & gold.searched].y_S == 0).all()
    gfac = facility_gold(gold, fac)
    pu = pu_labels(fac)
    c = c_estimates(pu, gold, ff)
    plan = crossfit_plan(gold)
    check_columns(plan)
    gold.to_parquet(OUT / "gold_dev_pairs.parquet", index=False)
    gfac.to_parquet(OUT / "gold_dev_facility.parquet", index=False)
    pu.to_parquet(OUT / "pu_labels.parquet", index=False)
    c.to_parquet(OUT / "c_estimates.parquet", index=False)
    plan.to_parquet(OUT / "crossfit_plan.parquet", index=False)
    pr = gold[gold.primary]
    stats = dict(
        v3_dev_present=V3_DEV.exists(),
        gold_rows=len(gold), gold_primary=len(pr), by_version=gold.version.value_counts().to_dict(),
        dup_conflicts=int(gold[gold.primary].dup_conflict.sum()),
        gold_cites_list=int(pr.gold_cites_list.sum()),
        y_S=pr.groupby("service").y_S.agg(pos=lambda x: int((x == 1).sum()), neg=lambda x: int((x == 0).sum()), missing=lambda x: int(x.isna().sum())).to_dict("index"),
        y_S_by_version=pr.groupby("version").y_S.agg(pos=lambda x: int((x == 1).sum()), neg=lambda x: int((x == 0).sum()), missing=lambda x: int(x.isna().sum())).to_dict("index"),
        fac_rows=len(gfac), fac_by_src=gfac.src.value_counts().to_dict(),
        y_L=gfac.groupby("src").y_L.agg(pos=lambda x: int((x == 1).sum()), neg=lambda x: int((x == 0).sum()), missing=lambda x: int(x.isna().sum())).to_dict("index"),
        y_E=gfac[gfac.src == "gold_dev"].y_E.value_counts(dropna=False).to_dict(),
        y_E_strict=gfac[gfac.src == "gold_dev"].y_E_strict.value_counts(dropna=False).to_dict(),
        gold_groups=int(pr.leakage_group_id.nunique()), gold_states=int(pr.state.nunique()),
        pu=pu.groupby(["label_family", "service", "label"]).size().unstack(fill_value=0).reset_index().to_dict("records"),
        pu_pos_weight=pu[pu.label == "positive"].groupby(["label_family", "service"]).weight.sum().round(2).reset_index().to_dict("records"),
    )
    (OUT / "stats.json").write_text(json.dumps(stats, indent=1, default=str))
    print(json.dumps({k: v for k, v in stats.items() if k not in ("pu", "pu_pos_weight")}, indent=1, default=str))


if __name__ == "__main__":
    main()
