"""Independent recount of the integrity audit (validation/integrity) issues INT-01..INT-10, plus issues it missed.

Read-only. Written without importing the auditor's checks.py or common.py.
Run all: /Users/karthikvattem/projects/datathon/.venv-viz/bin/python validation/integrity/verify/checks.py
Writes validation/integrity/verify/results.json.
"""
from __future__ import annotations

import collections
import glob
import gzip
import json
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path("/Users/karthikvattem/projects/datathon")
V1 = ROOT / "derived" / "v1"
HERE = Path(__file__).resolve().parent


def res(name, status, metric, threshold, detail, examples):
    return {"name": name, "status": status, "metric": metric, "threshold": threshold, "detail": detail,
            "examples": [str(e) for e in examples][:5]}


@lru_cache(None)
def t(name, cols=None):
    return pd.read_parquet(V1 / f"{name}.parquet", columns=list(cols) if cols else None)


@lru_cache(None)
def packs():
    out = {}
    for f in sorted(glob.glob(str(ROOT / "app/packs/out/*.json.gz"))):
        out[Path(f).name] = json.load(gzip.open(f))
    return out


@lru_cache(None)
def planner():
    return json.load(gzip.open(ROOT / "planner/out/planner_v1.json.gz"))


@lru_cache(None)
def facts():
    return json.load(gzip.open(ROOT / "app/facts/out/facts.json.gz"))


def excluded():
    rt = t("record_trust", ("unique_id", "trust_level"))
    return set(rt.unique_id[rt.trust_level == "exclude_review"])


def check_int01_exclude_review_shipped():
    ex = excluded()
    ex8 = {u[:8] for u in ex}
    pack_rows = []
    for name, d in packs().items():
        fids = np.cumsum(d["ev"]["f"])
        for e, (fi, s) in enumerate(zip(fids, d["ev"]["s"])):
            u8 = d["fac"]["uid8"][fi]
            if u8 in ex8:
                pack_rows.append(f"{name} {u8} {d['services'][s]} p={d['ev']['p'][e]}")
    p = planner()
    ids = p["facilities"]["id"]
    cap_rows = [f"{cap} {ids[i][:8]} p={pp}" for cap, c in p["capabilities"].items()
                for i, pp in zip(c["i"], c["p"]) if ids[i] in ex]
    in_fac = sum(i in ex for i in ids)
    in_facts = sum(i in ex for i in facts()["fac"]["id"])
    n_rec = len({r.split()[1] for r in cap_rows} | {r.split()[1] for r in pack_rows})
    bad = len(pack_rows) + len(cap_rows)
    return res("int01_exclude_review_shipped", "fail" if bad else "pass",
               f"{len(pack_rows)} pack rows + {len(cap_rows)} planner capability rows, {n_rec} of {len(ex)} records; "
               f"{in_fac} in planner facility list, {in_facts} in facts.json", "0",
               "exclude_review records reachable from app exports", pack_rows + cap_rows)


def check_int02_test_gold_in_score():
    d = t("data_point_scores", ("dp_id", "dp_type", "status", "gold_split", "score", "score_model", "unique_id"))
    tv = d[(d.gold_split == "test") & d.status.str.startswith("verified")]
    ft = t("facility_trust", ("unique_id", "location_score", "location_reason_codes"))
    loc = tv[tv.dp_type == "location"]
    ft_hit = ft[ft.unique_id.isin(loc.unique_id) & ft.location_score.isin([0.97, 0.03])]
    return res("int02_test_gold_in_score", "warn" if len(tv) else "pass",
               f"{len(tv)} test points verified ({tv.dp_type.value_counts().to_dict()}); score != score_model on "
               f"{int((tv.score != tv.score_model).sum())}; facility_trust location_score overridden on {len(ft_hit)}",
               "documented (README: 'Verified by gold (dev or test)')",
               "facility_trust has no gold_split or pre-override column; only reason codes reveal it", tv.dp_id.head(5))


def check_int03_specialty_label_conflicts():
    m = pd.read_csv(ROOT / "kb/taxonomy/specialty_map.csv", keep_default_na=False)
    m["k"] = m.specialty.str.lower().str.replace("[^a-z]", "", regex=True)
    g = m.groupby("k").service_id.agg(lambda s: sorted(set(s)))
    multi = g[g.map(len) > 1]
    non = {"out_of_scope", "too_general", "not_a_service"}
    real = multi[multi.map(lambda lab: sum(x not in non for x in lab) >= 1)]
    sp = t("specialties", ("unique_id", "spec"))
    return res("int03_specialty_label_conflicts", "warn" if len(multi) else "pass",
               f"{len(multi)} keys with 2+ labels ({sp[sp.spec.isin(multi.index)].unique_id.nunique()} records); "
               f"{len(real)} involve a real service ({sp[sp.spec.isin(real.index)].unique_id.nunique()} records)", "0",
               "consumers (build_lexicon, specialty_weights) join on the raw spelling, so labels depend on spelling",
               [f"{k}: {v}" for k, v in real.items()])


def check_int04_url_repeats():
    u = t("source_urls", ("unique_id", "url", "domain"))
    dup = u.duplicated(["unique_id", "url"])
    near = u.assign(n=u.url.str.lower().str.rstrip("/")).duplicated(["unique_id", "n"])
    top = u[dup].unique_id.value_counts().head(4)
    return res("int04_url_repeats", "warn" if dup.any() else "pass",
               f"{int(dup.sum())} exact repeats of {len(u)} rows in {u[dup].unique_id.nunique()} records; "
               f"{int(near.sum())} ignoring case and trailing slash", "0",
               "README grain says one (record, URL) pair; repeats are kept to reproduce q1_results totals",
               [f"{k}: {v}" for k, v in top.items()])


def check_int05_facts_pins_dropped():
    g = t("pin_gazetteer", ("pin", "state", "district", "lat", "lon"))
    usable = set(g.dropna(subset=["state", "lat", "lon"]).pin.astype(int))
    miss = sorted(usable - set(facts()["pins"]["pin"]))
    fl = t("facility_location", ("unique_id", "pin"))
    n_fac = int(fl.pin.dropna().astype(int).isin(miss).sum())
    return res("int05_facts_pins_dropped", "warn" if miss else "pass",
               f"{len(miss)} of {len(usable)} PINs missing from facts.json; {n_fac} facilities sit in them", "0",
               "all missing PINs have null district (build.py pins() dropna)", miss[:5])


def check_int06_planner_grade_policy():
    d = t("data_point_scores", ("dp_type", "unique_id", "service", "grade", "status", "score"))
    s = d[d.dp_type == "service_claim"].set_index(["unique_id", "service"])
    caps = json.loads((ROOT / "kb/pathways/capabilities.json").read_text())["capabilities"]
    kb = {c["id"]: c["kb_service"] for c in caps if c["kb_status"] == "existing"}
    p = planner()
    ids = p["facilities"]["id"]
    grade, vf, both, above, ex = collections.Counter(), 0, 0, 0, []
    for cap, c in p["capabilities"].items():
        if cap not in kb:
            continue
        for i, pp in zip(c["i"], c["p"]):
            r = s.loc[(ids[i], kb[cap])]
            g_bad = r.grade in ("attributed_elsewhere", "counter_evidence")
            v_bad = r.status == "verified_false"
            grade[r.grade] += g_bad
            vf += v_bad
            both += g_bad and v_bad
            if g_bad or v_bad:
                above += pp > p["no_mention_p"]
                ex.append(f"{cap} {ids[i][:8]} {r.grade}/{r.status} p={pp}")
    n = sum(grade.values()) + vf - both
    return res("int06_planner_grade_policy", "warn" if n else "pass",
               f"{n} planner rows the packs and engine treat as unlikely: {dict(+grade)} by grade, {vf} verified_false "
               f"({both} overlap); {above} of them score above no_mention_p={p['no_mention_p']}", "0",
               "packs drop EXCLUDED_GRADES and verified_false; app/facts/engine.py:111 treats both as unlikely", ex)


NULL_STR = {"null", "Null", "NULL", "None", "nan", "NaN", "N/A", "n/a", "nil", "Nil", "NIL", "undefined"}


def check_int07_null_strings():
    cells = {}
    for f, c in [("kb/opendata/vf_candidates.parquet", "vf_type"), ("kb/opendata/vf_opendata_match.parquet", "vf_type"),
                 ("derived/v1/grades.parquet", "facilityTypeId"), ("derived/v1/grades_v1.parquet", "facilityTypeId")]:
        cells[f"{f}:{c}"] = int(pd.read_parquet(ROOT / f, columns=[c])[c].isin(NULL_STR).sum())
    c = t("claims", ("claim_id", "text"))
    ph = c[c.text.str.strip().str.fullmatch(r"(?i)(?:null|none|n/?a|nil|nan|undefined|-+)")]
    return res("int07_null_strings", "warn", f"{sum(cells.values())} string-null cells; {len(ph)} placeholder claims "
               f"({int((ph.text.str.strip() == '-').sum())} of them '-')", "0", json.dumps(cells),
               (ph.claim_id + " " + ph.text).tolist())


def check_int08_location_keys():
    fl = t("facility_location")
    gz = set(t("pin_gazetteer", ("pin",)).pin.astype(int))
    ip = pd.read_parquet(ROOT / "data/raw/india_post_pincode_directory.parquet", columns=["pincode"])
    post = set(pd.to_numeric(ip.pincode, errors="coerce").dropna().astype(int))
    p = fl.dropna(subset=["pin"])
    bad = p[~p.pin.astype(int).isin(gz | post)]
    mis = fl[fl.district_state.notna() & (fl.district_state != fl.state_final)]
    ap = int(((mis.state_final == "ANDHRA PRADESH") & (mis.district_state == "TELANGANA")).sum())
    return res("int08_location_keys", "warn", f"{len(bad)} of {len(p)} PINs invalid; {len(mis)} of {len(fl)} "
               f"district_state != state_final ({ap} are Andhra Pradesh vs Telangana)", "0", "",
               (bad.unique_id + " " + bad.pin.astype(int).astype(str)).tolist()[:3] + mis.unique_id.head(2).tolist())


def check_int09_opendata_dup():
    f = pd.read_parquet(ROOT / "kb/opendata/vf_opendata_facts.parquet")
    d = f[f.astype(str).duplicated()]
    return res("int09_opendata_dup", "warn" if len(d) else "pass", f"{len(d)} of {len(f)}", "0", "",
               (d.unique_id + " " + d.source_id + " " + d.value.astype(str)).tolist())


def check_int10_orphans_ranges():
    lh = pd.read_parquet(ROOT / "kb/web_evidence/out/llm_hours.parquet")
    hc = pd.read_parquet(ROOT / "kb/web_evidence/out/hour_candidates.parquet")
    orph = lh[~lh.cand_key.isin(hc.cand_key)]
    fl = t("facility_location", ("unique_id", "raw_lat", "raw_lon"))
    out = fl[(fl.raw_lat < 6) | (fl.raw_lat > 37.5) | (fl.raw_lon < 68) | (fl.raw_lon > 97.5)]
    raw = pd.read_parquet(ROOT / "data/raw/facilities.parquet", columns=["unique_id", "yearEstablished"])
    y = raw[raw.unique_id.isin(set(fl.unique_id))].drop_duplicates("unique_id").yearEstablished
    y = y[y.notna() & (y.astype(str) != "null")].astype(str)
    noyear = y[~y.str.contains(r"(?:1[6-9]|20)\d\d")]
    return res("int10_orphans_ranges", "warn", f"{len(orph)} orphan llm_hours rows (keep={orph.keep.tolist()}); "
               f"{len(out)} raw coords outside India; {len(noyear)} of {len(y)} years with no year", "0", "",
               orph.cand_key.tolist() + out.unique_id.head(3).tolist() + noyear.tolist())


def check_m01_duplicate_groups_in_packs():
    """s4_groups.py promises 'the app shows one card per group'; the pack top-3 lists do not collapse groups."""
    fg = t("facility_groups", ("unique_id", "dup_group_id", "is_canonical"))
    grp = dict(zip(fg.unique_id.str[:8], fg.dup_group_id))
    canon = dict(zip(fg.unique_id.str[:8], fg.is_canonical))
    n_lists = n_bad = n_entries = n_bad_entries = n_rows = n_nc = 0
    ex = []
    for name, d in packs().items():
        fac, fids = d["fac"]["uid8"], np.cumsum(d["ev"]["f"])
        n_rows += len(fids)
        n_nc += sum(not canon[fac[i]] for i in fids)
        bad = set()
        for li, lst in enumerate(d["lists"]):
            gs = [grp[fac[fids[e]]] for e in lst if isinstance(grp[fac[fids[e]]], str)]
            n_lists += 1
            if len(gs) != len(set(gs)):
                bad.add(li)
                if len(ex) < 5:
                    ex.append(f"{name} list {li}: {[fac[fids[e]] for e in lst]}")
        n_bad += len(bad)
        for s in d["services"]:
            n_entries += len(d["index"][s])
            n_bad_entries += sum(x in bad for x in d["index"][s])
    return res("m01_duplicate_groups_in_packs", "warn" if n_bad else "pass",
               f"{n_bad} of {n_lists} distinct lists hold 2+ records of one duplicate group; {n_bad_entries} of "
               f"{n_entries} (service, PIN) entries; {n_nc} of {n_rows} pack evidence rows are non-canonical copies",
               "0", "build_packs.top_lists ranks every record; facts.json does not export dup_group_id", ex)


ABBR = r"(?:\b(?:Dr|Mr|Mrs|Ms|Prof|Smt|Pvt|Ltd|No|St|Sr|Jr|Co|Inc|Rs)|(?:^|\s|\()[A-Z])\.$"


def check_m02_description_split_at_abbreviations():
    c = t("claims", ("claim_id", "unique_id", "field", "text"))
    d = c[c.field == "description"]
    br = d[d.text.str.strip().str.contains(ABBR)]
    alone = br[br.text.str.strip().str.fullmatch(r"(?:Dr|Mr|Mrs|Ms|Prof|Smt|Pvt|Ltd|No|St|[A-Z])\.")]
    return res("m02_description_split_at_abbreviations", "warn" if len(br) else "pass",
               f"{len(br)} of {len(d)} description sentences end at an abbreviation ({br.unique_id.nunique()} records); "
               f"{len(alone)} are a bare fragment like 'Dr.'", "0",
               "cleaning/claims/build_claims.py:44 splits on '([.!?])\\s+' with no abbreviation guard",
               (br.claim_id + " " + br.text).sample(5, random_state=20261121).tolist())


def check_m03_auditor_suite_order():
    """The auditor's check_enums reads outputs/schema_profile.csv, written by check_schema_profile, which the
    runner calls later (alphabetical). On a clean outputs/ dir check_enums crashes."""
    src = (ROOT / "validation/integrity/checks.py").read_text()
    body = src[src.index("def check_enums"):]
    body = body[:body.index("\ndef ", 10)]
    reads = "schema_profile" in body
    order = sorted(n for n in re.findall(r"^def (check_\w+)", src, re.M))
    before = order.index("check_enums") < order.index("check_schema_profile")
    return res("m03_auditor_suite_order", "warn" if reads and before else "pass",
               f"check_enums reads schema_profile output: {reads}; runs before check_schema_profile: {before}", "",
               "reproduced: a clean rerun reported check_enums FileNotFoundError", [])


def check_m04_pin_dtype():
    a = str(pq.read_schema(V1 / "facility_location.parquet").field("pin").type)
    b = str(pq.read_schema(V1 / "pin_gazetteer.parquet").field("pin").type)
    return res("m04_pin_dtype", "warn" if a != b else "pass", f"facility_location.pin {a}, pin_gazetteer.pin {b}",
               "same type", "a PIN stored as double prints 112001.0 in a Delta table or Genie answer", [])


def check_m05_uncited_service_points():
    """Service points with no cited sentence: tag_only is by design; G_amb 'weak' with n_mentions >= 1 is not."""
    d = t("data_point_scores", ("dp_id", "dp_type", "original_value", "grade"))
    e = d[(d.dp_type == "service_claim") & (d.original_value == "")]
    weak = e[e.grade == "weak"]
    n_rows = n_noq = 0
    for d2 in packs().values():
        n_rows += len(d2["ev"]["q1"])
        n_noq += sum(q == -1 for q in d2["ev"]["q1"])
    return res("m05_uncited_service_points", "warn" if len(weak) or n_noq else "pass",
               f"{len(e)} service points cite no sentence ({e.grade.value_counts().to_dict()}); {len(weak)} graded weak; "
               f"{n_noq} of {n_rows} pack evidence rows carry no quote", "weak = 0",
               "G_amb grades count ambiguous mentions but cite_evidence keeps only own sentences", weak.dp_id.head(5))


if __name__ == "__main__":
    out = []
    for n in sorted(k for k in dir() if k.startswith("check_")):
        r = globals()[n]()
        out.append(r)
        print(f"[{r['status']}] {r['name']}: {r['metric']}")
        for e in r["examples"]:
            print("     ", e[:200])
    (HERE / "results.json").write_text(json.dumps(out, indent=1, default=str))
