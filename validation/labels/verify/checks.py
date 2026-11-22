"""Verifier's independent recount of the gold-label audit (validation/labels). Read-only on every data layer.

Each check_<name>() -> dict(name, status, metric, threshold, detail, examples). Uses vload.py only (not the
auditor's common.py/checks.py). v3 is never opened. No network: the URL re-check is verified from the
auditor's saved page text (validation/labels/out/pages), not re-fetched.
Run: /Users/karthikvattem/projects/datathon/.venv-viz/bin/python checks.py   (writes out/checks.json)
"""
from __future__ import annotations

import gzip
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vload import D1, G, OUT, ROOT, gold_pairs, primary, recs, res, samples, split_tab, wilson  # noqa: E402

AUD = ROOT / "validation/labels"


def _dp(cols=("dp_id", "dp_type", "unique_id", "status", "gold_split", "q_ev", "score_model")) -> pd.DataFrame:
    return pd.read_parquet(D1 / "data_point_scores.parquet", columns=list(cols))


def _auc(y: np.ndarray, s: np.ndarray) -> float:
    p, n = s[y], s[~y]
    if not len(p) or not len(n):
        return float("nan")
    return round(float(((p[:, None] > n[None, :]).sum() + 0.5 * (p[:, None] == n[None, :]).sum()) / (len(p) * len(n))), 3)


def _test_points(dp_type: str) -> pd.DataFrame:
    dp = _dp()
    t = dp[(dp.gold_split == "test") & (dp.dp_type == dp_type) & dp.status.isin(["verified_true", "verified_false"])].copy()
    t["y"] = t.status == "verified_true"
    return t


# L1 ------------------------------------------------------------------------------------------------------
SEARCHED_NO_URL = ["nicu_weak_2", "v2_emergency_csection_strong_4", "v2_emergency_csection_no_mention_3",
                   "v2_cardiac_surgery_no_mention_5", "v2_nicu_weak_2", "v2_emergency_csection_suspect_4", "e2e_013", "e2e_039"]


def check_l1_never_searched():
    p = primary()
    ni = p[p.service == "no_info"]
    never = ni[ni.nurl == 0]
    gp = gold_pairs().copy()
    gp["n_merged"] = gp.evidence_urls.map(lambda s: len(json.loads(s)))
    gp["n_prim"] = gp.pair_id.map(p.set_index("pair_id").nurl)
    gni = gp[gp.service_verdict == "no_info"]
    by_prim = gni[gni.n_prim == 0].split.value_counts().to_dict()
    by_merged = gni[gni.n_merged == 0].split.value_counts().to_dict()
    # read by hand from out/noinfo_notes.txt: no URL kept although the note reports >= 1 search
    ok = set(SEARCHED_NO_URL) <= set(never.pair_id)
    return res("l1_never_searched", "fail", f"{len(never)} of {len(ni)} primary no_info have 0 URLs; gold_pairs no_info "
               f"{len(gni)}: {sum(by_prim.values())} by primary-URL rule {by_prim}, {sum(by_merged.values())} by its own merged "
               f"URL column {by_merged}; {len(SEARCHED_NO_URL)} no-URL notes report a search (hand read, ids present={ok})",
               "0 unflagged", "gold_pairs has no searched flag; 4 pairs were searched only by the overlap labeller",
               ["v2_nicu_no_mention_2", "v2_cardiac_surgery_weak_3", "v2_mri_weak_5", "v2_trauma_emergency_weak_3"] + SEARCHED_NO_URL[:1])


# L2 ------------------------------------------------------------------------------------------------------
def check_l2_v1_in_test():
    sp = split_tab()
    v1t = sp[(sp.version == "v1") & (sp.split == "test")]
    uids = set(v1t.unique_id)
    out = {}
    for ty in ("service_claim", "location", "existence"):
        t = _test_points(ty)
        v2 = t[~t.unique_id.isin(uids)]
        out[ty] = dict(n=len(t), from_v1=int(t.unique_id.isin(uids).sum()), neg=int((~t.y).sum()),
                       neg_from_v1=int((~t.y & t.unique_id.isin(uids)).sum()),
                       auc_all=(_auc(t.y.to_numpy(), t.q_ev.to_numpy(float)), _auc(t.y.to_numpy(), t.score_model.to_numpy(float))),
                       auc_v2only=(_auc(v2.y.to_numpy(), v2.q_ev.to_numpy(float)), _auc(v2.y.to_numpy(), v2.score_model.to_numpy(float))))
    tot = sum(v["n"] for v in out.values())
    fr = sum(v["from_v1"] for v in out.values())
    return res("l2_v1_in_test", "fail", f"{len(v1t)} of {(sp.version == 'v1').sum()} v1 pairs in test; {fr} of {tot} test gold "
               f"points from them; service negatives from v1 {out['service_claim']['neg_from_v1']} of {out['service_claim']['neg']}",
               "0 design-read pairs in test", json.dumps(out), sorted(v1t.pair_id))


# L3 ------------------------------------------------------------------------------------------------------
STATE_ONLY_LOC_NO = ["v2_emergency_csection_suspect_5", "v2_nicu_suspect_5"]  # notes: city and PIN right, state field wrong


def check_l3_no_web_evidence():
    d = recs()
    sv = d[d.service.isin(["confirmed", "contradicted"]) & (d.nurl == 0)]
    lo = d[(d.location == "no") & (d.nurl == 0)]
    sp = split_tab().set_index("pair_id")
    t = _test_points("location")
    uid = sp.unique_id
    pin_only_test = [x for x in lo.pair_id if sp.split.get(x) == "test"]
    drop = {uid[x] for x in pin_only_test + STATE_ONLY_LOC_NO}
    keep = t[~t.unique_id.isin(drop)]
    return res("l3_no_web_evidence", "fail", f"{len(sv)} service verdicts with 0 URLs {sv.groupby('kind').size().to_dict()}; "
               f"{len(lo)} location=no with 0 URLs {lo.pair_id.map(sp.split).fillna('e2e').value_counts().to_dict()}; "
               f"test location negatives not showing a wrong location: {len(pin_only_test)} PIN-only + {len(STATE_ONLY_LOC_NO)} state-only "
               f"of {int((~t.y).sum())}", "0",
               f"location test AUC q_ev/model all {_auc(t.y.to_numpy(), t.q_ev.to_numpy(float))}/"
               f"{_auc(t.y.to_numpy(), t.score_model.to_numpy(float))}; without those 5 "
               f"{_auc(keep.y.to_numpy(), keep.q_ev.to_numpy(float))}/{_auc(keep.y.to_numpy(), keep.score_model.to_numpy(float))} "
               f"(n_neg {int((~keep.y).sum())})", list(sv.pair_id[:2]) + pin_only_test + STATE_ONLY_LOC_NO[:1])


# L4 ------------------------------------------------------------------------------------------------------
def check_l4_url_recheck():
    j = pd.read_csv(AUD / "judgments/url_judgments.csv")
    k, n = int((j.agree == "yes").sum()), int(j.agree.isin(["yes", "no"]).sum())
    pages = {"emergency_csection_strong_1": r"caesar|cesar|c-section|lscs",
             "v2_emergency_csection_strong_5": r"cesarean"}
    found = {}
    for pid, pat in pages.items():
        txt = " ".join(gzip.open(f, "rt").read() for f in sorted((AUD / "out/pages" / pid).glob("*.txt.gz")))
        found[pid] = bool(re.search(pat, txt, re.I))
    dp = _dp(("dp_id", "status", "gold_split"))
    sp = split_tab().set_index("pair_id")
    svc = {"emergency_csection_strong_1": "csection", "v2_burn_care_suspect_1": "burns",
           "v2_emergency_csection_strong_5": "csection", "v2_dialysis_no_mention_1": "dialysis"}
    st = {p: dp[dp.dp_id == f"svc:{sp.unique_id[p]}:{s}"].status.tolist() for p, s in svc.items()}
    ok = found == {"emergency_csection_strong_1": False, "v2_emergency_csection_strong_5": True}
    return res("l4_url_recheck", "warn", f"agreement {k}/{n} Wilson95 {wilson(k, n)}", ">= 0.95",
               f"page text: caesarean named {found}; data point status {st}", list(j[j.agree == "no"].pair_id)) | (
        {} if ok else {"status": "fail"})


# L5 ------------------------------------------------------------------------------------------------------
MISATTRIB = ["cardiac_surgery_suspect_1", "mri_suspect_1", "nicu_suspect_2", "cardiac_surgery_weak_1", "mri_suspect_2",
             "v2_emergency_csection_suspect_1", "v2_dialysis_suspect_2", "v2_burn_care_suspect_1"]
NO_ABSENCE = ["v2_emergency_csection_suspect_1", "v2_dialysis_suspect_2", "v2_burn_care_suspect_1"]


def check_l5_contradicted_semantics():
    p = primary()
    c = p[p.service == "contradicted"]
    n_unknown = int(c[c.pair_id.isin(NO_ABSENCE)].notes.str.contains(r"unknown|confirms or denies|found no|Two searches", case=False).sum())
    t = _test_points("service_claim")
    sp = split_tab()
    u2p = dict(zip(sp.unique_id, sp.pair_id))
    negs = sorted(u2p[u] for u in t[~t.y].unique_id)
    return res("l5_contradicted_semantics", "warn", f"{len(MISATTRIB)} of {len(c)} contradicted rest on misattribution (hand read); "
               f"{len(NO_ABSENCE)} show no absence ({n_unknown} say so in the note)", "0 without absence evidence",
               f"derived/v1 service test negatives: {negs}", NO_ABSENCE)


# L6 ------------------------------------------------------------------------------------------------------
def check_l6_trauma():
    s = samples().drop_duplicates("pair_id").set_index("pair_id")
    d = primary()
    d = d[d.pair_id.map(s.service) == "trauma_emergency"]
    conf = d[d.service == "confirmed"]
    strict = conf[~(conf.notes + " " + conf.quote.fillna("")).str.contains(r"trauma|accident|injur|fracture", case=False)]
    tax = json.loads((ROOT / "kb/taxonomy/services.json").read_text())
    alias = {a: sv["id"] for c in tax["categories"] for sv in c["services"] for a in (sv.get("aliases") or [])}
    hand = ["v2_trauma_emergency_strong_3", "v2_trauma_emergency_no_mention_2", "e2e_003"]  # hand read: ED or casualty only
    assert set(hand) <= set(conf.pair_id)
    return res("l6_trauma", "warn", f"{len(hand)} of {len(conf)} trauma confirmations are ED/casualty-only (hand read); regex on "
               f"notes+quote finds {len(strict)} (notes mention 'trauma level not stated')", "0", f"taxonomy alias trauma_emergency->{alias.get('trauma_emergency')}, "
               f"trauma->{alias.get('trauma')}; pairs by set {s[s.service == 'trauma_emergency'].set.value_counts().to_dict()}",
               hand)


# L7 ------------------------------------------------------------------------------------------------------
def check_l7_two_readers():
    p = primary().set_index("pair_id")
    rows = [(pid, g.split, a) for pid, g in gold_pairs().set_index("pair_id").iterrows()
            for a, b in (("exists", "exists"), ("location_ok", "location"), ("service_verdict", "service")) if g[a] != p.at[pid, b]]
    x = pd.DataFrame(rows, columns=["pair", "split", "field"])
    sv = x[x.field == "service_verdict"]
    return res("l7_two_readers", "warn", f"{len(x)} fields over {x.pair.nunique()} pairs; service {len(sv)} "
               f"({sv.split.value_counts().to_dict()})", "0", "gold_pairs (merged with o1/o2) vs primary labels read by fusion/gold.py",
               list(sv.pair))


# L8 ------------------------------------------------------------------------------------------------------
def check_l8_leakage():
    ff = pd.read_parquet(ROOT / "model/proto/fusion/features_facility.parquet", columns=["unique_id", "leakage_group_id"])
    lg = ff.set_index("unique_id").leakage_group_id
    sp = split_tab().assign(lg=lambda x: x.unique_id.map(lg))
    a = sp.groupby("lg").split.nunique()
    b = sp.assign(s=sp.split.where(sp.version == "v2", "dev")).groupby("lg").s.nunique()
    e = samples()
    e = e[e.set == "e2e"].assign(lg=lambda x: x.unique_id.map(lg))
    v2t = sp[(sp.version == "v2") & (sp.split == "test")]
    on_uid = e[e.unique_id.isin(v2t.unique_id)]
    on_lg = e[e.lg.isin(v2t.lg) & ~e.unique_id.isin(v2t.unique_id)]
    return res("l8_leakage", "warn", f"groups across splits {int((a > 1).sum())} (v1-as-dev {int((b > 1).sum())}); e2e on v2 test "
               f"uid {len(on_uid)}, in v2 test group {len(on_lg)} of {len(e)}", "0", "", list(on_uid.pair_id) + list(on_lg.pair_id[:1]))


# L9 ------------------------------------------------------------------------------------------------------
def check_l9_minor():
    gp = gold_pairs()
    ids = set(_dp(("dp_id",)).dp_id)
    inf = gp[gp.service_verdict.isin(["confirmed", "contradicted"])]
    miss = inf[~("svc:" + inf.unique_id + ":" + inf.service).isin(ids)]
    fg = pd.read_parquet(D1 / "facility_groups.parquet").set_index("unique_id").is_canonical
    s = samples().drop_duplicates("pair_id")
    nc = s[s.unique_id.map(fg) == False]  # noqa: E712
    urls = [(r.pair_id, u) for r in recs().itertuples() for u in r.urls]
    sp_ = sorted({p for p, u in urls if re.search(r"\s", u)})
    return res("l9_minor", "warn", f"unattached {len(miss)} of {len(inf)} ({miss.stratum.value_counts().to_dict()}); non-canonical "
               f"{len(nc)} of {len(s)}; URLs with whitespace {sum(bool(re.search(r'[\s]', u)) for _, u in urls)} of {len(urls)}",
               "0", "", list(miss.pair_id[:2]) + list(nc.pair_id[:2]) + sp_[:1])


# missed issues ---------------------------------------------------------------------------------------------
NOT_FOUND = r"found no|no (?:\w+[ \-]?){0,6}(?:found|listing)|not found|could not (?:find|locate)|no page (?:found|for)|returned nothing"


def check_m1_existence_no_negatives():
    d = recs()
    nf = primary()
    nf = nf[(nf.exists == "unclear") & nf.notes.str.contains(NOT_FOUND, case=False, regex=True)]
    rules = pd.read_parquet(D1 / "evidence_rules.parquet").set_index("rule")
    ft = pd.read_parquet(D1 / "facility_trust.parquet", columns=["existence_score"]).existence_score
    dp = _dp(("dp_type", "status", "gold_split"))
    ex = dp[(dp.dp_type == "existence") & dp.gold_split.notna()].status.value_counts().to_dict()
    return res("m1_existence_no_negatives", "fail", f"exists=no in {int((d.exists == 'no').sum())} of {len(d)} label records; "
               f"{len(nf)} searched-not-found coded unclear; EXISTS_DEFAULT dev {rules.at['EXISTS_DEFAULT', 'dev_true']}/"
               f"{rules.at['EXISTS_DEFAULT', 'dev_false']} q_ev {rules.at['EXISTS_DEFAULT', 'q_ev']:.3f}; facility_trust existence_score "
               f"min {ft.min():.3f} max {ft.max():.3f} over {len(ft)}", ">= 1 negative class",
               f"existence gold points {ex}; model/proto/fusion/fit.py existence_rows codes exists=unclear as y=0",
               list(nf.pair_id))


def check_m2_service_test_negatives():
    t = _test_points("service_claim")
    sp = split_tab()
    u2p = dict(zip(sp.unique_id, sp.pair_id))
    ver = dict(zip(sp.pair_id, sp.version))
    negs = [u2p[u] for u in t[~t.y].unique_id]
    clean = [p for p in negs if ver[p] == "v2" and p not in NO_ABSENCE]
    return res("m2_service_test_negatives", "fail", f"{len(negs)} negatives in derived/v1 service test; {sum(ver[p] == 'v1' for p in negs)} "
               f"design-read v1, {len(negs) - len(clean) - sum(ver[p] == 'v1' for p in negs)} with no absence evidence, {len(clean)} clean",
               ">= 5 clean negatives", "evaluation.json service_claim AUC 0.826/0.819 has no clean negative", negs)


def check_m3_confirm_from_record_sources():
    raw = pd.read_parquet(ROOT / "data/raw/facilities.parquet", columns=["unique_id", "source_urls"]).dropna()
    raw = raw.drop_duplicates("unique_id").set_index("unique_id").source_urls

    def norm(u):
        return re.sub(r"^https?://(www\.)?", "", u.strip().lower()).rstrip("/")

    s = samples().drop_duplicates("pair_id").set_index("pair_id")
    c = primary()
    c = c[c.service == "confirmed"]
    hits = []
    for r in c.itertuples():
        src = {norm(u) for u in json.loads(raw.get(s.unique_id[r.pair_id], "[]")) if u}
        ev = {norm(u) for u in r.urls}
        hits.append((r.pair_id, len(ev & src), len(ev)))
    anyh = [p for p, h, n in hits if h]
    allh = [p for p, h, n in hits if h and h == n]
    return res("m3_confirm_from_record_sources", "warn", f"{len(anyh)} of {len(c)} confirmations cite a record source URL; "
               f"{len(allh)} cite only record source URLs", "independent evidence", "exact URL match after scheme/www/slash normalisation",
               allh)


def main():
    import inspect
    out = []
    for n, f in inspect.getmembers(sys.modules[__name__], inspect.isfunction):
        if n.startswith("check_"):
            r = f()
            out.append(r)
            print(r["name"], r["status"], "|", r["metric"])
    OUT.mkdir(exist_ok=True)
    (OUT / "checks.json").write_text(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    assert wilson(22, 25) == (0.7, 0.958)
    main()
