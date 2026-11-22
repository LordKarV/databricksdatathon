"""Gold labels and evaluation integrity checks (model/gold v1 + v2 + end-to-end pool; never v3 TEST).

Each check_<name>() -> dict(name, status, metric, threshold, detail, examples). Read-only on every data layer.
Run all: /Users/karthikvattem/projects/datathon/.venv-viz/bin/python checks.py   (writes out/checks.json)
The URL re-check reads out/url_recheck.json written by recheck_urls.py plus judgments/url_judgments.csv.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from urllib.parse import urlparse

import pandas as pd

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from common import (D1, G, HERE, INFORMATIVE, NAME_ONLY, NOT_SEARCHED, OUT, PIN_DIR, ROOT, UF, e2e_not_run,  # noqa: E402
                    gold_pairs, label_files, labels, norm, pairs, raw, result, sha256, splits, taxonomy, wilson)

S2_SERVICE_MAP = {"dialysis": "dialysis", "emergency_csection": "csection", "nicu": "nicu", "mri": "mri",
                  "cardiac_surgery": "cardiac_surgery", "burn_care": "burns", "trauma_emergency": "trauma"}
TRAUMA_WORDS = re.compile(r"trauma|accident|injur|polytrauma|fracture|casualty", re.I)


def _primary() -> pd.DataFrame:
    """The label a consumer reads first: v1 web batches, v2 primary batches, e2e batches."""
    lab = labels()
    return lab[lab.kind.isin(["v1", "v2_primary", "e2e"])]


# ---------------------------------------------------------------- structure

def check_label_schema():
    lab = labels()
    bad = []
    for r in lab.itertuples():
        for f in ("exists", "location", "service", "confidence"):
            from common import ENUMS
            if getattr(r, f) not in ENUMS[f]:
                bad.append(f"{r.file}:{r.pair_id}:{f}={getattr(r, f)!r}")
        if not isinstance(r.pair_id, str) or not r.pair_id:
            bad.append(f"{r.file}:#{r.idx}:pair_id")
    n = len(lab) * 4
    return result("label_schema", "pass" if not bad else "fail", f"{len(bad)} bad of {n} enum fields in {len(lab)} records",
                  "0", f"{len(label_files())} label files; enums exists/location yes|no|unclear, service confirmed|contradicted|no_info, "
                  "confidence high|medium|low", bad)


def check_duplicate_label_records():
    lab = labels()
    within = lab.groupby(["file", "pair_id"]).size()
    within = within[within > 1]
    prim = _primary()
    across = prim.groupby("pair_id").file.nunique()
    across = across[across > 1]
    ov_file = set(json.loads((G / "overlap_v2.json").read_text()))
    ov_lab = set(lab[lab.kind == "v2_overlap"].pair_id)
    nr = set(e2e_not_run())
    e2e_both = nr & set(lab[lab.kind == "e2e"].pair_id)
    bad = [f"within {k}" for k in within.index] + [f"primary twice {k}" for k in across.index] + \
          [f"overlap label not in overlap_v2.json {k}" for k in sorted(ov_lab - ov_file)] + \
          [f"overlap_v2.json pair without overlap label {k}" for k in sorted(ov_file - ov_lab)] + \
          [f"e2e labelled and not_run {k}" for k in sorted(e2e_both)]
    return result("duplicate_label_records", "pass" if not bad else "fail", f"{len(bad)} duplicate or orphaned overlap records",
                  "0", f"{len(lab)} records; {len(prim)} primary; overlap labels {len(ov_lab)} vs overlap_v2.json {len(ov_file)}; "
                  f"e2e not_run {len(nr)}", bad)


def check_label_coverage():
    """Every sampled pair has exactly one primary label (or is listed not_run); every label has a sampled pair."""
    p = pairs()
    prim = _primary()
    known = set(p.pair_id)
    orphan = sorted(set(labels().pair_id) - known)
    have = set(prim.pair_id) | set(e2e_not_run())
    missing = p[~p.pair_id.isin(have)]
    sp = set(splits().pair_id)
    v12 = p[p.set.isin(["v1", "v2"])]
    split_missing = sorted(set(v12.pair_id) - sp)
    split_extra = sorted(sp - set(v12.pair_id))
    dup_pid = p.pair_id[p.pair_id.duplicated()].tolist()
    bad = [f"orphan label {x}" for x in orphan] + [f"unlabelled {x}" for x in missing.pair_id] + \
          [f"not in splits {x}" for x in split_missing] + [f"split without sample {x}" for x in split_extra] + \
          [f"pair_id reused {x}" for x in dup_pid]
    by = p.assign(lab=p.pair_id.isin(prim.pair_id)).groupby("set").lab.agg(["sum", "size"]).to_dict("index")
    return result("label_coverage", "pass" if not bad else "fail", f"{len(bad)} coverage defects",
                  "0", f"labelled/sampled per set {by}; e2e not_run {len(e2e_not_run())}", bad)


# ---------------------------------------------------------------- record identity

def check_unique_ids_usable():
    p = pairs()
    r = raw()
    loc = pd.read_parquet(D1 / "facility_location.parquet", columns=["unique_id"])
    fg = pd.read_parquet(D1 / "facility_groups.parquet", columns=["unique_id", "is_canonical", "dup_group_id"])
    raw_ids, clean_ids = set(r.unique_id), set(loc.unique_id)
    noncanon = set(fg[~fg.is_canonical].unique_id)
    raw_dup = set(r.unique_id[r.unique_id.duplicated()])
    ex = []
    rows = []
    for x in p.itertuples():
        why = []
        if x.unique_id not in raw_ids:
            why.append("not in raw")
        elif x.unique_id not in clean_ids:
            why.append("dropped by cleaning (not in the 9,959 usable records)")
        if x.unique_id in noncanon:
            why.append("non-canonical duplicate member")
        if x.unique_id in raw_dup:
            why.append("unique_id repeated in raw")
        if why:
            rows.append((x.set, x.pair_id, x.unique_id, "; ".join(why)))
    hard = [r_ for r_ in rows if "not in raw" in r_[3] or "dropped" in r_[3]]
    st = "fail" if hard else "warn" if rows else "pass"
    pd.DataFrame(rows, columns=["set", "pair_id", "unique_id", "why"]).to_csv(OUT / "unusable_ids.csv", index=False)
    return result("unique_ids_usable", st, f"{len(hard)} not usable, {len(rows) - len(hard)} non-canonical, of {len(p)} pairs",
                  "0 not usable", f"usable = present in derived/v1/facility_location (9,959); by set: "
                  f"{Counter(r_[0] for r_ in rows)}; list in out/unusable_ids.csv",
                  [f"{a}:{b} {c} ({d})" for a, b, c, d in rows])


def check_pair_metadata_matches_raw():
    """Sample name and PIN equal the raw record of the unique_id (guards a label pointing at the wrong row)."""
    p = pairs().merge(raw(), on="unique_id", how="left")
    bad = []
    for x in p.itertuples():
        if pd.isna(x.name_y):
            continue
        if norm(x.name_x) != norm(x.name_y):
            bad.append(f"{x.pair_id}: name {x.name_x!r} vs raw {x.name_y!r}")
        elif x.pin is not None and str(x.pin) != str(x.address_zipOrPostcode):
            bad.append(f"{x.pair_id}: pin {x.pin} vs raw {x.address_zipOrPostcode}")
    return result("pair_metadata_matches_raw", "pass" if not bad else "fail", f"{len(bad)} mismatches of {len(p)}", "0",
                  "name compared after lowercasing and stripping punctuation; PIN as string", bad)


def check_live_table_ids(run_sql: bool = False):
    """All gold unique_ids exist in the Marketplace table (one SELECT). Uses the cached result unless run_sql."""
    cache = OUT / "live_ids.json"
    ids = sorted(set(pairs().unique_id))
    if run_sql:
        import subprocess
        q = ("SELECT unique_id FROM databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities "
             "WHERE unique_id IN (" + ",".join(f"'{u}'" for u in ids) + ")")
        out = subprocess.run([str(ROOT / "sql.sh"), q], capture_output=True, text=True, timeout=300)
        found = sorted(set(re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", out.stdout)))
        cache.write_text(json.dumps(dict(n_queried=len(ids), found=found, rc=out.returncode, stderr=out.stderr[-500:])))
    if not cache.exists():
        return result("live_table_ids", "warn", "not run", "all present", "run with run_sql=True (one SELECT via sql.sh)")
    c = json.loads(cache.read_text())
    miss = sorted(set(ids) - set(c["found"]))
    if c.get("rc") or not c["found"]:
        return result("live_table_ids", "warn", "not run", "all present", f"sql.sh failed: {c.get('stderr')}")
    return result("live_table_ids", "pass" if not miss else "fail", f"{len(ids) - len(miss)} of {len(ids)} ids found live",
                  "all present", "SELECT unique_id ... WHERE unique_id IN (gold ids)", miss)


# ---------------------------------------------------------------- services

def check_services_in_taxonomy():
    tax = taxonomy()
    p = pairs()
    unmapped = sorted(set(p.service) - set(tax))
    s2 = {k: tax.get(v) for k, v in S2_SERVICE_MAP.items()}
    direct = {k: tax.get(k) for k in S2_SERVICE_MAP}
    diverge = {k: (direct[k], s2[k]) for k in S2_SERVICE_MAP if direct[k] != s2[k]}
    st = "fail" if unmapped else "warn" if diverge else "pass"
    return result("services_in_taxonomy", st, f"{len(unmapped)} unmapped; {len(diverge)} gold ids that map to different "
                  "taxonomy services via the taxonomy alias vs derived/v1 s2_gold SERVICE_MAP", "0 / 0",
                  f"gold services {sorted(set(p.service))}; divergent: {diverge} (taxonomy says trauma_emergency is an alias "
                  "of trauma_care; s2_gold maps it to the claims key 'trauma', an alias of emergency_24x7)",
                  unmapped + [f"{k}: taxonomy={a} derived_v1={b}" for k, (a, b) in diverge.items()])


def check_trauma_label_semantics():
    """trauma_emergency verdicts: how many confirmations rest only on generic 24x7 emergency evidence."""
    lab = _primary().merge(pairs()[["pair_id", "service"]].rename(columns={"service": "svc"}), on="pair_id")
    t = lab[(lab.svc == "trauma_emergency") & (lab.service == "confirmed")]
    # the quote when there is one, else the notes with negated mentions ("trauma level not stated") removed
    neg = re.compile(r"(no|not|without)\b[^.;]{0,40}(trauma|accident|injur)\w*|(trauma|accident)\w*[^.;]{0,20}not (stated|named|found)", re.I)
    text = [q if isinstance(q, str) and q.strip() else neg.sub(" ", nt) for q, nt in zip(t.quote, t.notes)]
    generic = t[[not TRAUMA_WORDS.search(x) for x in text]]
    n = len(t)
    st = "warn" if len(generic) else "pass"
    return result("trauma_label_semantics", st, f"{len(generic)} of {n} trauma_emergency confirmations cite no trauma, "
                  "accident or injury term", "0", "these confirm emergency_24x7, not trauma_care; label meaning depends on which "
                  "taxonomy id the consumer maps trauma_emergency to", [f"{r.pair_id}: {(r.quote or r.notes)[:90]}" for r in generic.itertuples()])


# ---------------------------------------------------------------- duplicates and conflicts

def _cmp(a, b, field):
    va, vb = a[field], b[field]
    inf = INFORMATIVE[field]
    if va in inf and vb in inf:
        return "agree" if va == vb else "conflict"
    if va in inf or vb in inf:
        return "one_informative"
    return "agree" if va == vb else "both_uninformative_differ"


def check_overlap_conflicts():
    lab = labels()
    prim = lab[lab.kind == "v2_primary"].set_index("pair_id")
    ov = lab[lab.kind == "v2_overlap"].set_index("pair_id")
    sp = splits().set_index("pair_id").split
    res, ex = defaultdict(Counter), []
    for pid in ov.index:
        a, b = prim.loc[pid], ov.loc[pid]
        for f in ("service", "exists", "location"):
            o = _cmp(a, b, f)
            res[f][o] += 1
            if o == "conflict":
                ex.append(f"{pid} ({sp.get(pid)}) {f}: {a[f]} vs {b[f]}")
    # Cohen's kappa on service, all three categories
    A, B = [prim.loc[p, "service"] for p in ov.index], [ov.loc[p, "service"] for p in ov.index]
    po = sum(x == y for x, y in zip(A, B)) / len(A)
    pe = sum(A.count(c) / len(A) * B.count(c) / len(B) for c in set(A) | set(B))
    kappa = round((po - pe) / (1 - pe), 3)
    n_conf = sum(c["conflict"] for c in res.values())
    return result("overlap_conflicts", "fail" if n_conf else "pass",
                  f"{n_conf} informative conflicts on {len(ov)} double-labelled pairs; service kappa {kappa} (agreement {po:.3f})",
                  "0 conflicts", {k: dict(v) for k, v in res.items()}.__repr__(), ex)


def check_same_facility_service_across_sets():
    """Same (unique_id, taxonomy service) labelled under more than one pair_id (v1, v2, e2e)."""
    tax = taxonomy()
    p = pairs().assign(tsvc=lambda d: d.service.map(tax))
    prim = _primary().set_index("pair_id")
    dup = p[p.duplicated(["unique_id", "tsvc"], keep=False)].sort_values(["unique_id", "tsvc"])
    groups, conflicts, ex = 0, 0, []
    for (u, s), g in dup.groupby(["unique_id", "tsvc"]):
        groups += 1
        labs = [prim.loc[x] for x in g.pair_id if x in prim.index]
        vs = {l_["service"] for l_ in labs} & INFORMATIVE["service"]
        tag = "CONFLICT" if len(vs) > 1 else ""
        conflicts += bool(tag)
        ex.append(f"{tag} {u[:8]} {s}: " + ", ".join(f"{x}={prim.loc[x, 'service'] if x in prim.index else 'unlabelled'}"
                                                      f"[{sp}]" for x, sp in zip(g.pair_id, g.split.fillna('e2e'))))
    ex.sort(key=lambda s: not s.startswith("CONFLICT"))
    pd.DataFrame(dict(line=ex)).to_csv(OUT / "same_facility_service.csv", index=False)
    st = "fail" if conflicts else "warn" if groups else "pass"
    return result("same_facility_service_across_sets", st, f"{groups} (facility, service) keys under 2+ pair_ids; "
                  f"{conflicts} with conflicting verdicts", "0 conflicts",
                  "e2e pairs re-label gold facilities; a gold TEST facility relabelled in the e2e pool is also a leak "
                  "if e2e labels are used for tuning (out/same_facility_service.csv)", ex)


def check_same_facility_conflicting_exists_location():
    """Records with several labels (any service): exists or location verdicts that disagree."""
    prim = _primary().merge(pairs()[["pair_id", "unique_id"]], on="pair_id")
    ex = []
    for f in ("exists", "location"):
        g = prim[prim[f].isin(INFORMATIVE[f])].groupby("unique_id")[f].agg(lambda s: tuple(sorted(set(s))))
        for u, v in g.items():
            if len(v) > 1:
                ex.append(f"{u} {f}: {v} via {list(prim[prim.unique_id == u].pair_id)}")
    return result("same_facility_conflicting_exists_location", "fail" if ex else "pass",
                  f"{len(ex)} records with disagreeing exists/location verdicts", "0", "primary labels across v1, v2, e2e", ex)


# ---------------------------------------------------------------- splits and leakage

def _split_map(v1_dev: bool):
    sp = splits()
    s = dict(zip(sp.pair_id, sp.split))
    if v1_dev:
        s.update({p: "dev" for p in sp[sp.version == "v1"].pair_id})
    return sp.assign(split_eff=sp.pair_id.map(s))


def _spanning(sp, key):
    g = sp.groupby(key).split_eff.nunique()
    return set(g[g > 1].index)


def check_split_leakage_unique_id():
    sp = _split_map(False)
    bad = _spanning(sp, "unique_id")
    bad_g = _spanning(sp, "group")
    ex = [f"{u}: {sp[sp.unique_id == u][['pair_id', 'split']].values.tolist()}" for u in bad]
    return result("split_leakage_unique_id", "pass" if not bad and not bad_g else "fail",
                  f"{len(bad)} unique_ids and {len(bad_g)} frozen groups in both splits", "0",
                  f"{sp.unique_id.nunique()} unique_ids, {sp.group.nunique()} frozen groups (grp_strong)", ex)


def _leak_groups_canonical():
    """Union-find over derived/v1 facility_groups: dup_group_id, possible_same_site, co_located_with."""
    fg = pd.read_parquet(D1 / "facility_groups.parquet")
    uf = UF()
    for u, g in zip(fg.unique_id, fg.dup_group_id):
        uf.find(u)
        if pd.notna(g):
            uf.union(u, "G:" + str(g))
    for col in ("possible_same_site", "co_located_with"):
        for u, xs in zip(fg.unique_id, fg[col]):
            for x in (xs if xs is not None else []):
                uf.union(u, x)
    return uf


def check_split_leakage_groups():
    """Groups wider than the frozen grp_strong: the model's leakage_group_id and the canonical facility_groups links."""
    out, ex = {}, []
    ff = pd.read_parquet(ROOT / "model/proto/fusion/features_facility.parquet", columns=["unique_id", "leakage_group_id"])
    lg = dict(zip(ff.unique_id, ff.leakage_group_id))
    uf = _leak_groups_canonical()
    for v1_dev in (False, True):
        sp = _split_map(v1_dev)
        sp = sp.assign(model_lg=sp.unique_id.map(lg), canon=sp.unique_id.map(uf.find))
        tag = "v1_as_dev" if v1_dev else "splits_json"
        for key in ("model_lg", "canon"):
            bad = _spanning(sp.dropna(subset=[key]), key)
            out[f"{tag}:{key}"] = len(bad)
            for k in sorted(bad):
                rows = sp[sp[key] == k]
                ex.append(f"[{tag}/{key}] " + "; ".join(f"{a}={b}" for a, b in zip(rows.pair_id, rows.split_eff)))
    ex = list(dict.fromkeys(ex))
    n = sum(out.values())
    return result("split_leakage_groups", "warn" if n else "pass", str(out), "0 groups spanning dev and test",
                  "model_lg = model/proto/fusion features_facility.leakage_group_id (grp_strong + phone/domain + chain + "
                  "source_content_id); canon = derived/v1 facility_groups dup_group_id + possible_same_site + co_located_with. "
                  "fit.py drops dev rows in test leakage groups; derived/v1 s4/s5 does not", ex)


def check_v1_split_contract():
    """v1 pairs were read during design (MODEL_SPEC 4.1, fusion/gold.py) but splits.json and gold_pairs mark 17 as test."""
    sp = splits()
    v1t = sp[(sp.version == "v1") & (sp.split == "test")]
    gp = gold_pairs()
    gp_v1t = gp[gp.pair_id.isin(v1t.pair_id)]
    dp = pd.read_parquet(D1 / "data_point_scores.parquet", columns=["dp_id", "dp_type", "unique_id", "service", "status", "gold_split"])
    t = dp[(dp.gold_split == "test") & dp.status.isin(["verified_true", "verified_false"])]
    in_eval = t[t.unique_id.isin(v1t.unique_id)]
    by = in_eval.dp_type.value_counts().to_dict()
    tot = t.dp_type.value_counts().to_dict()
    return result("v1_split_contract", "fail" if len(v1t) else "pass",
                  f"{len(v1t)} of 36 v1 pairs marked test; {len(in_eval)} of {len(t)} derived/v1 test gold points come from them",
                  "0 design-read pairs in a held-out test",
                  f"derived/v1 evaluation.json test points by type from v1 pairs {by} of {tot}; model/proto treats all v1 as dev",
                  [f"{r.pair_id} ({r.unique_id[:8]})" for r in v1t.itertuples()])


def check_e2e_vs_gold_test():
    """e2e pool facilities that are also v2 TEST facilities or in their leakage groups."""
    p = pairs()
    ff = pd.read_parquet(ROOT / "model/proto/fusion/features_facility.parquet", columns=["unique_id", "leakage_group_id"])
    lg = dict(zip(ff.unique_id, ff.leakage_group_id))
    test = p[(p.set == "v2") & (p.split == "test")]
    tg = {lg.get(u) for u in test.unique_id}
    e = p[p.set == "e2e"]
    same = e[e.unique_id.isin(test.unique_id)]
    grp = e[e.unique_id.map(lg).isin(tg) & ~e.unique_id.isin(test.unique_id)]
    ex = [f"{r.pair_id} {r.unique_id[:8]} {r.service}" for r in pd.concat([same, grp]).itertuples()]
    return result("e2e_vs_gold_test", "warn" if ex else "pass", f"{len(same)} e2e pairs on a v2 test facility, {len(grp)} more in a "
                  "test leakage group, of 158", "0 if e2e labels ever feed model selection",
                  "harmless while e2e labels are only scored; a leak if they enter dev or calibration", ex)


# ---------------------------------------------------------------- never-searched vs no_info

def check_never_searched_vs_no_info():
    lab = _primary().copy()
    ni = lab[lab.service == "no_info"]
    url_rule = ni.n_urls == 0                     # model/proto/fusion/gold.py: unchecked
    note_rule = ni.notes.str.contains(NOT_SEARCHED)
    a = ni[url_rule & ~note_rule]                 # no URL but notes describe a real search that found nothing
    b = ni[~url_rule & note_rule]                 # URL present but notes say search stopped (budget)
    gp = gold_pairs()
    gp_ni = gp[gp.service_verdict == "no_info"]
    unchecked_ids = set(lab[(lab.service == "no_info") & (lab.n_urls == 0)].pair_id)
    gp_unch = gp_ni[gp_ni.pair_id.isin(unchecked_ids)]
    cols = set(gp.columns)
    has_flag = bool({"status", "searched", "label_status", "never_searched"} & cols)
    ex = [f"no URL, searched: {r.pair_id}: {r.notes[:80]}" for r in a.itertuples()] + \
         [f"URL, search stopped: {r.pair_id}: {r.notes[:80]}" for r in b.itertuples()]
    return result("never_searched_vs_no_info", "fail" if not has_flag else "warn",
                  f"{len(ni)} no_info primary labels: {int(url_rule.sum())} never searched by the URL rule; rule disagrees with "
                  f"notes on {len(a) + len(b)} ({len(a)} searched-without-URL, {len(b)} URL-but-stopped); gold_pairs has no "
                  f"searched flag and {len(gp_unch)} of its {len(gp_ni)} no_info rows were never searched "
                  f"(dev {int((gp_unch.split == 'dev').sum())}, test {int((gp_unch.split == 'test').sum())})",
                  "a searched flag on every no_info row", "no_info mixes 'searched, found nothing' with 'never searched'",
                  ex)


def check_verdicts_without_web_evidence():
    """Informative verdicts with no evidence URL, and name-only or PIN-directory-only judgments."""
    lab = _primary()
    sv = lab[lab.service.isin(INFORMATIVE["service"]) & (lab.n_urls == 0)]
    name_only = sv[sv.notes.str.contains(NAME_ONLY)]
    loc = lab[lab.location.isin(INFORMATIVE["location"]) & (lab.n_urls == 0)]
    loc_pin = loc[loc.notes.str.contains(PIN_DIR)]
    ex_ = lab[lab.exists.isin(INFORMATIVE["exists"]) & (lab.n_urls == 0)]
    conf_noquote = lab[(lab.service == "confirmed") & (lab.kind != "v1") & (lab.quote.fillna("").str.strip() == "")]
    pd.concat([sv.assign(why="service verdict, no URL"), loc.assign(why="location verdict, no URL"),
               conf_noquote.assign(why="confirmed, empty quote")])[["file", "pair_id", "why", "service", "location", "exists", "notes"]] \
        .to_csv(OUT / "verdicts_without_evidence.csv", index=False)
    by = sv.groupby("kind").size().to_dict()
    n = len(sv) + len(loc)
    return result("verdicts_without_web_evidence", "fail" if len(sv) else "warn" if n else "pass",
                  f"{len(sv)} service verdicts with no URL ({len(name_only)} name-only) by set {by}; {len(loc)} location verdicts "
                  f"with no URL ({len(loc_pin)} from the local PIN directory); {len(ex_)} exists verdicts with no URL; "
                  f"{len(conf_noquote)} v2/e2e confirmations with an empty quote", "0 service verdicts without a URL",
                  "name-only contradictions restate the scope feature the model already uses (circular); PIN-directory "
                  "location verdicts restate the dataset's own PIN (out/verdicts_without_evidence.csv)",
                  [f"{r.pair_id}={r.service}: {r.notes[:70]}" for r in name_only.itertuples()] +
                  [f"{r.pair_id} loc={r.location}: {r.notes[:70]}" for r in loc_pin.itertuples()])


def check_contradicted_semantics():
    """'contradicted' should mean the facility does not offer the service; some mean only 'the claim is about another facility'."""
    lab = _primary()
    c = lab[lab.service == "contradicted"]
    rx = re.compile(r"another facility|other facility|belongs to|claim belongs|attributes the|names? (?:a |another )|"
                    r"different (?:facility|hospital|institution)", re.I)
    absent = re.compile(r"no (?:imaging|burns|dialysis|nicu|mri)|not offer|does not (?:list|mention)|no .{0,20}listed|"
                        r"lists? only|ART Level|fertility", re.I)
    m = c[c.notes.str.contains(rx)]
    only = m[~m.notes.str.contains(absent)]
    return result("contradicted_semantics", "warn" if len(only) else "pass",
                  f"{len(m)} of {len(c)} contradicted labels rest on misattribution; {len(only)} of them give no evidence the "
                  "service is absent", "0", "misattribution is a location/attribution fact; as a service y=0 it teaches the model "
                  "that a real hospital lacks a service nobody checked", [f"{r.pair_id}: {r.notes[:110]}" for r in only.itertuples()])


def check_evidence_urls_wellformed():
    lab = labels()
    bad = []
    for r in lab.itertuples():
        for u in r.evidence_urls:
            pu = urlparse(u)
            if pu.scheme not in ("http", "https") or not pu.netloc or " " in u:
                bad.append(f"{r.pair_id}: {u}")
            if "google." in pu.netloc and "/search" in pu.path:
                bad.append(f"{r.pair_id}: search page {u}")
    n = int(lab.n_urls.sum())
    return result("evidence_urls_wellformed", "warn" if bad else "pass", f"{len(bad)} of {n} URLs malformed (space or no scheme)",
                  "0", "spaces must be %20-encoded for a re-fetch", bad)


# ---------------------------------------------------------------- derived/v1 gold_pairs

def _s2_rebuild() -> pd.DataFrame:
    """Re-implementation of pipelines/source_scoring/s2_gold.py on the current label files (same merge rule)."""
    CONF = {"high": 3, "medium": 2, "low": 1}
    INF = {"exists": {"yes", "no"}, "location_ok": {"yes", "no"}, "service": {"confirmed", "contradicted"}}
    by = defaultdict(list)
    for f in label_files():
        for r in json.loads(f.read_text())["results"]:
            by[r["pair_id"]].append({**r, "location_ok": r.get("location_ok", r.get("location_matches")),
                                     "label_file": str(f.relative_to(ROOT))})

    def mf(ls, field):
        vals = [(CONF.get(x.get("confidence"), 0), x[field]) for x in ls if x.get(field) in INF[field]]
        if not vals:
            return ls[0].get(field) or "unclear"
        return "conflict" if len({v for _, v in vals}) > 1 else max(vals)[1]

    rows = []
    for p in json.loads((G / "splits.json").read_text())["pairs"]:
        ls = by.get(p["pair_id"])
        if not ls:
            continue
        ls = sorted(ls, key=lambda x: -CONF.get(x.get("confidence"), 0))
        rows.append(dict(pair_id=p["pair_id"], unique_id=p["unique_id"], service=S2_SERVICE_MAP[p["service"]],
                         stratum=p["stratum"], split=p["split"], n_labels=len(ls), exists=mf(ls, "exists"),
                         location_ok=mf(ls, "location_ok"), service_verdict=mf(ls, "service"),
                         confidence=ls[0].get("confidence"),
                         evidence_urls=json.dumps(sorted({u for x in ls for u in x.get("evidence_urls") or []})[:6]),
                         label_files="|".join(sorted({x["label_file"] for x in ls}))))
    return pd.DataFrame(rows)


def check_gold_pairs_matches_labels():
    gp = gold_pairs().set_index("pair_id").sort_index()
    rb = _s2_rebuild().set_index("pair_id").sort_index()
    diffs = []
    if set(gp.index) != set(rb.index):
        diffs.append(f"pair sets differ: {sorted(set(gp.index) ^ set(rb.index))[:5]}")
    cols = [c for c in rb.columns if c in gp.columns]
    for pid in gp.index.intersection(rb.index):
        for c in cols:
            a, b = gp.at[pid, c], rb.at[pid, c]
            if str(a) != str(b):
                diffs.append(f"{pid}.{c}: parquet={a} rebuilt={b}")
    man = json.loads((D1 / "MANIFEST.json").read_text())["other_input_sha256"]
    stale = [f"{k} hash changed" for k, v in man.items() if ("gold" in k) and sha256(ROOT / k) != v]
    unhashed = [str(f.relative_to(ROOT)) for f in label_files() if f.parent == ROOT / "audit/ground_truth"
                and str(f.relative_to(ROOT)) not in man]
    st = "fail" if diffs or stale else "warn" if unhashed else "pass"
    return result("gold_pairs_matches_labels", st, f"{len(diffs)} cell diffs over {len(gp)} rows x {len(cols)} cols; "
                  f"{len(stale)} stale input hashes; {len(unhashed)} label inputs not hashed in MANIFEST", "0 / 0 / 0",
                  f"rebuilt with s2_gold rules from current files; unhashed: {unhashed}", diffs + stale)


def check_gold_pairs_vs_model_loader():
    """derived/v1 merges overlap labels (o1, o2) into the verdict; model/proto/fusion/gold.py reads primary p labels only."""
    gp = gold_pairs().set_index("pair_id")
    prim = labels()[labels().kind.isin(["v1", "v2_primary"])].set_index("pair_id")
    ex = []
    for pid, r in gp.iterrows():
        if pid not in prim.index:
            continue
        for a, b in (("service_verdict", "service"), ("location_ok", "location"), ("exists", "exists")):
            if r[a] != prim.at[pid, b]:
                ex.append(f"{pid} [{r.split}] {a}: gold_pairs={r[a]} model={prim.at[pid, b]}")
    return result("gold_pairs_vs_model_loader", "warn" if ex else "pass", f"{len(ex)} fields where derived/v1 and the model "
                  f"read different verdicts for the same pair (of {len(gp)} pairs)", "0",
                  "two consumers of the same labels disagree; dev q_ev and test metrics in derived/v1 use the merged value", ex)


def check_gold_attach_to_datapoints():
    """Each informative gold_pairs verdict reaches a data point in derived/v1/data_point_scores."""
    gp = gold_pairs()
    dp = pd.read_parquet(D1 / "data_point_scores.parquet", columns=["dp_id", "gold_split", "status"])
    have = set(dp[dp.gold_split.notna()].dp_id)
    sv = gp[gp.service_verdict.isin(["confirmed", "contradicted"])]
    miss = sv[~("svc:" + sv.unique_id + ":" + sv.service).isin(have)]
    split_bad = []
    m = dp.set_index("dp_id")
    for r in sv.itertuples():
        k = f"svc:{r.unique_id}:{r.service}"
        if k in m.index and m.at[k, "gold_split"] != r.split:
            split_bad.append(f"{k} split {m.at[k, 'gold_split']} vs {r.split}")
    return result("gold_attach_to_datapoints", "warn" if len(miss) else "pass",
                  f"{len(miss)} of {len(sv)} informative service verdicts reach no service_claim data point; {len(split_bad)} split mismatches",
                  "0 / 0", f"missing by stratum/verdict {miss.groupby(['stratum', 'service_verdict']).size().to_dict()}: "
                  "unclaimed services (no grade row) are invisible to evaluation.json, so it measures claim precision only",
                  [f"{r.pair_id} [{r.split}] {r.service_verdict}" for r in miss.itertuples()] + split_bad)


# ---------------------------------------------------------------- derived/v2 contract (design only)

def check_derived_v2_gold_contract():
    """Contract for the coming derived/v2 gold table. Does not judge contents; reports not run while absent."""
    d2 = ROOT / "derived/v2"
    cands = sorted(d2.glob("*gold*.parquet")) if d2.exists() else []
    if not cands:
        return result("derived_v2_gold_contract", "warn", "not run", "contract holds",
                      "derived/v2 has no gold table yet; contract: one row per pair_id, service in the 36 taxonomy ids, "
                      "label_status in {checked, unchecked}, unchecked never used as y=0, v1 pairs not in test, no leakage group "
                      "in both splits")
    g = pd.read_parquet(cands[0])
    bad = []
    if "pair_id" in g and not g.pair_id.is_unique:
        bad.append("pair_id not unique")
    if "service" in g and not g.service.isin(set(taxonomy().values())).all():
        bad.append("service outside taxonomy ids")
    if not ({"label_status", "status", "searched"} & set(g.columns)):
        bad.append("no searched/unchecked flag")
    if {"split", "pair_id"} <= set(g.columns):
        if g[g.pair_id.isin(splits()[splits().version == "v1"].pair_id) & (g.split == "test")].shape[0]:
            bad.append("v1 pairs in test")
    return result("derived_v2_gold_contract", "fail" if bad else "pass", f"{len(bad)} contract breaks in {cands[0].name}",
                  "0", "structural only", bad)


# ---------------------------------------------------------------- URL re-check

def check_url_recheck():
    f = OUT / "url_recheck.json"
    j = HERE / "judgments/url_judgments.csv"
    if not f.exists() or not j.exists():
        return result("url_recheck", "warn", "not run", ">= 0.8 agreement", "run recheck_urls.py, then write judgments")
    import gzip
    from rapidfuzz import fuzz
    rc = pd.DataFrame(json.loads(f.read_text())["rows"])
    jd = pd.read_csv(j)
    d = rc.merge(jd, on="pair_id", how="left")
    n = len(d)
    reach = int((d.any_page_ok).sum())
    judged = d[d.agree.isin(["yes", "no"])]
    k = int((judged.agree == "yes").sum())

    def frag_found(r):
        """Labellers stitch quotes with '...'; every fragment must appear (partial_ratio >= 90) on one saved page."""
        frags = [norm(x) for x in re.split(r"\.\.\.|…", r.quote) if len(norm(x)) >= 8]
        texts = [norm(gzip.decompress((OUT / "pages" / r.pair_id / f"{i}.txt.gz").read_bytes()).decode())
                 for i in range(len(r.pages))]
        return bool(frags) and any(all(fuzz.partial_ratio(fr, t) >= 90 for fr in frags) for t in texts if t)

    qn = d[d.quote_checkable]
    qk = int(sum(frag_found(r) for r in qn.itertuples()))
    lo, hi = wilson(k, len(judged))
    st = "pass" if len(judged) and lo >= 0.8 else "warn" if len(judged) and k / len(judged) >= 0.8 else "fail"
    return result("url_recheck", st, f"verdict agreement {k}/{len(judged)} = {k / max(len(judged), 1):.2f} [95% Wilson {lo}, {hi}]; "
                  f"pages reachable {reach}/{n}; quote found {qk}/{len(qn)} [{wilson(qk, len(qn))}]",
                  "Wilson lower bound >= 0.8",
                  f"{n} labels, seed fixed, v2 TEST excluded; {n - len(judged)} not judgeable (no page reachable)",
                  [f"{r.pair_id} label={r.label_service} -> {r.agree}: {r.reason}" for r in d[d.agree == "no"].itertuples()])


CHECKS = [check_label_schema, check_duplicate_label_records, check_label_coverage, check_unique_ids_usable,
          check_pair_metadata_matches_raw, check_live_table_ids, check_services_in_taxonomy, check_trauma_label_semantics,
          check_overlap_conflicts, check_same_facility_service_across_sets, check_same_facility_conflicting_exists_location,
          check_split_leakage_unique_id, check_split_leakage_groups, check_v1_split_contract, check_e2e_vs_gold_test,
          check_never_searched_vs_no_info, check_verdicts_without_web_evidence, check_contradicted_semantics, check_evidence_urls_wellformed,
          check_gold_pairs_matches_labels, check_gold_pairs_vs_model_loader, check_gold_attach_to_datapoints,
          check_derived_v2_gold_contract, check_url_recheck]


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    res = []
    for c in CHECKS:
        try:
            r = c()
        except Exception as e:  # a crashing check is reported, never hidden
            r = result(c.__name__[6:], "fail", "error", "-", f"{type(e).__name__}: {e}")
        res.append(r)
        print(f"{r['status']:5} {r['name']}: {r['metric']}")
    (OUT / "checks.json").write_text(json.dumps(res, indent=1, default=str))
