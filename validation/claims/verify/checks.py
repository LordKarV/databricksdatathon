"""Adversarial re-verification of the validation/claims audit (claims, attribution, taxonomy mapping).

Independent code: nothing is imported from validation/claims/checks.py (rerun_auditor.py re-runs that file separately,
with its output redirected here). Read-only on every data layer; writes only verify/out/.
Every check_<name>() returns dict(name, status, metric, threshold, detail, examples).
Run: /Users/karthikvattem/projects/datathon/.venv-viz/bin/python -B checks.py [name ...]
"""
from __future__ import annotations

import functools
import gzip
import json
import math
import os
import re
import sys

import pandas as pd

ROOT = "/Users/karthikvattem/projects/datathon"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
LAB = os.path.join(HERE, "labels")
V1 = f"{ROOT}/derived/v1"
UUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
ARR = ("procedure", "equipment", "capability")


def res(name, status, metric, threshold, detail, examples=()):
    return dict(name=name, status=status, metric=metric, threshold=threshold, detail=detail, examples=list(examples)[:5])


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0, c - h), 3), round(min(1, c + h), 3))


# ---------------------------------------------------------------- loaders (cached)

@functools.lru_cache(None)
def raw():
    return pd.read_parquet(f"{ROOT}/data/raw/facilities.parquet")


@functools.lru_cache(None)
def kept():
    r = raw()
    return r[(r.source == "kie") & r.unique_id.astype(str).str.match(UUID)].drop_duplicates("unique_id")


@functools.lru_cache(None)
def claims():
    return pd.read_parquet(f"{V1}/claims.parquet")


@functools.lru_cache(None)
def ctext():
    return claims().set_index("claim_id").text


@functools.lru_cache(None)
def lexicon():
    return json.load(open(f"{ROOT}/kb/taxonomy/lexicon.json"))


@functools.lru_cache(None)
def matches():
    return pd.read_parquet(f"{ROOT}/kb/taxonomy/out/lexicon_matches.parquet")


@functools.lru_cache(None)
def shared_cues():
    return {k: re.compile(v, re.I) for k, v in lexicon()["shared_cues"]["nonoffer"].items()}


@functools.lru_cache(None)
def planner():
    return json.load(gzip.open(f"{ROOT}/planner/out/planner_v1.json.gz", "rt"))


@functools.lru_cache(None)
def caps():
    return {c["id"]: c for c in json.load(open(f"{ROOT}/kb/pathways/capabilities.json"))["capabilities"]}


@functools.lru_cache(None)
def planner_rows() -> pd.DataFrame:
    """One row per (capability, facility) in planner_v1, with p and cited claim ids."""
    p = planner()
    ids = p["facilities"]["id"]
    rows = [(cap, ids[i], pp, tuple(e)) for cap, v in p["capabilities"].items() for i, pp, e in zip(v["i"], v["p"], v["e"])]
    d = pd.DataFrame(rows, columns=["cap", "uid", "p", "ids"])
    d["status"] = d.cap.map(lambda c: caps()[c]["kb_status"])
    return d


@functools.lru_cache(None)
def planner_cited() -> pd.DataFrame:
    d = planner_rows()
    return pd.DataFrame([(r.cap, r.uid, r.status, cid) for r in d.itertuples() for cid in r.ids], columns=["cap", "uid", "status", "cid"])


@functools.lru_cache(None)
def facts():
    return json.load(gzip.open(f"{ROOT}/app/facts/out/facts.json.gz", "rt"))


@functools.lru_cache(None)
def app_pairs() -> pd.DataFrame:
    f = facts()
    ids = f["fac"]["id"]
    return pd.DataFrame([(s, ids[r[0]], r[1], r[4], tuple(r[9])) for s, lst in f["pairs"].items() for r in lst],
                        columns=["svc", "uid", "grade", "score", "ids"])


def ftype():
    k = kept()
    return k.set_index("unique_id").facilityTypeId, k.set_index("unique_id").name


# ---------------------------------------------------------------- re-verification of the auditor's passes

def check_claims_arrays_rebuilt():
    """Array items rebuilt with Python json + str.strip (wider than RE2); keys and texts must equal claims exactly."""
    exp, off, recs = {}, 0, set()
    for u, *vals in kept()[["unique_id", *ARR]].itertuples(index=False):
        for f, j in zip(ARR, vals):
            try:
                it = json.loads(j) if isinstance(j, str) else None
            except ValueError:
                it = None
            if not isinstance(it, list):
                continue
            k = 0
            for pos, x in enumerate(it):
                if x is None or not str(x).strip():
                    continue
                exp[(u, f, k)] = str(x).strip()
                if k != pos:
                    off += 1
                    recs.add(u)
                k += 1
    c = claims()
    a = c[c.field != "description"]
    got = dict(zip(zip(a.unique_id, a.field, a.idx), a.text))
    miss = set(exp) - set(got)
    extra = set(got) - set(exp)
    diff = [k for k in got.keys() & exp.keys() if got[k] != exp[k]]
    bad = len(miss) + len(extra) + len(diff)
    return res("claims_arrays_rebuilt", "pass" if bad == 0 else "fail",
               f"{len(exp)} raw array items; missing {len(miss)}, extra {len(extra)}, text differs {len(diff)}", "0",
               f"idx differs from raw position for {off} claims in {len(recs)} records (CL-9 recount)", [str(k) for k in list(miss)[:3]] + diff[:2])


def check_claims_description_rebuilt():
    """Description sentences rebuilt with a lookbehind split (different construction from the builder's replace+split)."""
    sp = re.compile(r"(?<=[.!?])[\t\n\f\r ]+")
    exp = {}
    for u, d in kept()[["unique_id", "description"]].itertuples(index=False):
        if not isinstance(d, str) or d == "null":
            continue
        k = 0
        for s in sp.split(d):
            t = s.strip("\t\n\f\r ")
            if t:
                exp[(u, k)] = t
                k += 1
    c = claims()
    a = c[c.field == "description"]
    got = dict(zip(zip(a.unique_id, a.idx), a.text))
    bad = len(set(exp) ^ set(got)) + sum(got[k] != exp[k] for k in got.keys() & exp.keys())
    return res("claims_description_rebuilt", "pass" if bad == 0 else "fail", f"{bad} differences over {len(exp)} sentences", "0",
               "lookbehind split on RE2 whitespace after . ! ?")


def check_split_records_recount():
    """CL-4: UUID rows with source null (record heads) and non-UUID fragment rows; heads absent from every v1 table."""
    r = raw()
    isu = r.unique_id.astype(str).str.match(UUID)
    heads = r[isu & (r.source != "kie")]
    frags = r[~isu]
    present = {t: len(set(heads.unique_id) & set(pd.read_parquet(f"{V1}/{t}.parquet", columns=["unique_id"]).unique_id))
               for t in ("facility_location", "record_trust", "facility_trust", "grades", "claims")}
    adjacent = int(sum(1 for i in heads.index if i + 1 in frags.index))
    items = 0
    for row in frags.itertuples(index=False):
        for v in row:
            if isinstance(v, str) and v.lstrip().startswith("["):
                try:
                    it = json.loads(v)
                except ValueError:
                    continue
                if isinstance(it, list):
                    items += sum(1 for x in it if isinstance(x, str) and x.strip())
    return res("split_records_recount", "warn" if len(heads) else "pass",
               f"{len(heads)} heads, {len(frags)} fragment rows, present in v1 tables {present}", "0",
               f"fragment JSON array items {items} (all arrays, incl. specialties); heads followed by a fragment row in file order: {adjacent} "
               "(fragments sort to the top, so stitching needs a content key, not adjacency); live table: 10088 rows, 9971 non-null source",
               heads.unique_id.head(5).tolist())


# ---------------------------------------------------------------- CL-1 and the non-offer gaps

def check_planner_cited_any_shared_cue():
    """CL-1 widened: apply the kb shared non-offer cues to EVERY planner-cited sentence, not only kb-lexicon-matched ones.
    Verdicts read by hand in labels/planner_cued_all_verdicts.csv."""
    d = planner_cited().drop_duplicates(["cap", "cid"]).copy()
    d["text"] = d.cid.map(ctext())
    cues = shared_cues()
    d["cue"] = d.text.map(lambda t: "|".join(k for k, r in cues.items() if r.search(t)))
    hit = d[d.cue != ""]
    lab = pd.read_csv(f"{LAB}/planner_cued_all_verdicts.csv")
    same = sorted(zip(lab.cap, lab.cid)) == sorted(zip(hit.cap, hit.cid))
    v = lab.verdict.value_counts().to_dict() if same else "labels stale"
    ex = [f"{r.cap} <- {r.cid} [{r.verdict}] {r.text[:60]!r}" for r in lab[lab.verdict.isin(["nonoffer", "camp"])].tail(5).itertuples()]
    return res("planner_cited_any_shared_cue", "fail" if len(hit) else "pass",
               f"{len(hit)} cited (capability, claim) pairs over {hit.cid.nunique()} sentences carry a kb shared non-offer cue; {len(d)} citations",
               "0", f"by status {hit.status.value_counts().to_dict()}; by cue {hit.cue.value_counts().to_dict()}; hand verdicts {v}", ex)


FUTURE_GAP = re.compile(r"\bplans? to (introduce|expand|implement|upgrade|begin|commence|offer|provide|create|construct|acquire|procure)"
                        r"|\b(aims?|intends?) to (establish|start|open|introduce|set up|launch|build)|\bopening soon"
                        r"|\bexpected to (be )?(complete|open|start|operational|commission)|\bwill (soon )?(be )?(introduc|commenc|begin)"
                        r"|\bin the near future\b", re.I)


def check_kb_future_cue_gap():
    """kb shared 'future' cue misses 'plans to introduce / offer / expand / construct'. These stay positive evidence in kb
    (read by model #11), in grades (cleaning cue is narrower still) and in planner citations."""
    fut = shared_cues()["future"]
    m = matches().join(ctext(), on="claim_id")
    x = m[(m.nonoffer_cue == "") & m.text.map(lambda t: bool(FUTURE_GAP.search(t)))]
    pc = planner_cited().drop_duplicates(["cap", "cid"])
    pc = pc[pc.cid.map(lambda c: bool(FUTURE_GAP.search(ctext()[c])) and not fut.search(ctext()[c]))]
    ex = [f"{r.claim_id} {r.service}: {r.text[:70]!r}" for r in x.drop_duplicates("claim_id").head(5).itertuples()]
    return res("kb_future_cue_gap", "warn" if len(x) else "pass",
               f"{len(x)} kb positive pairs over {x.claim_id.nunique()} sentences; {len(pc)} planner citations "
               f"({pc.status.value_counts().to_dict()})", "0", f"by service {x.service.value_counts().to_dict()}", ex)


def check_app_pairs_cite_plans():
    """App pairs whose cited evidence is a plan sentence (kb future cue or the gap pattern above)."""
    a = app_pairs()
    fut = shared_cues()["future"]
    t = ctext()
    rows = [(r.svc, r.uid, r.grade, cid) for r in a.itertuples() for cid in r.ids
            if fut.search(t[cid]) or FUTURE_GAP.search(t[cid])]
    allplan = [(r.svc, r.uid[:8], r.grade) for r in a.itertuples()
               if r.ids and all(fut.search(t[c]) or FUTURE_GAP.search(t[c]) for c in r.ids)]
    return res("app_pairs_cite_plans", "fail" if allplan else ("warn" if rows else "pass"),
               f"{len(rows)} cited plan sentences in {len({(s, u) for s, u, _, _ in rows})} app pairs; {len(allplan)} pairs cite only plans",
               "0", f"pairs citing only plans: {allplan}", [f"{s} {u[:8]} {g} {c}: {t[c][:60]!r}" for s, u, g, c in rows])


# ---------------------------------------------------------------- CL-2, CL-3, CL-6, CL-7

def check_mri_therapy_recount():
    """CL-2: MRI pairs whose text is a magnetic resonance THERAPY device; facilities with no other MRI evidence; app rows."""
    t = ctext()
    ther = re.compile(r"QMRT|quantum magnetic|magnetic resonance therap|RFQMR", re.I)
    m = matches()
    mm = m[m.service == "mri"]
    bad = mm[mm.claim_id.map(lambda c: bool(ther.search(t[c])))]
    only = set(bad.unique_id) - set(mm[~mm.claim_id.isin(bad.claim_id)].unique_id)
    a = app_pairs()
    app = a[(a.svc == "mri") & a.uid.isin(only)]
    return res("mri_therapy_recount", "fail" if len(app) else "pass",
               f"{len(bad)} kb mri pairs; {len(only)} facilities MRI only through them; {len(app)} shown in app pairs.mri",
               "0", f"app grades {app.grade.tolist()}; e7795a4f is EMRT, abe799fb is RFQMR (Cytotron), cd8b64e1 QMRT",
               [f"{u[:8]} {g} {s}" for u, g, s in zip(app.uid, app.grade, app.score)])


def check_ultrasound_3d_alternative():
    """CL-3: remove the '(3|4|5)D (scan|ultrasound)' alternative from the kb include and see which pairs no longer match."""
    inc = lexicon()["services"]["ultrasound"]["include"]
    alt = r"|\b(3|4|5)D (scan|ultrasound)"
    if alt not in inc:
        return res("ultrasound_3d_alternative", "not_run", "alternative not found in lexicon.json", "", "")
    r2 = re.compile(inc.replace(alt, ""), re.I)
    m = matches()
    u = m[m.service == "ultrasound"].join(ctext(), on="claim_id")
    only = u[~u.text.map(lambda s: bool(r2.search(s)))]
    ft, nm = ftype()
    dentaleye = only.unique_id.map(lambda x: bool(re.search(r"dental|dent|smile|teeth|tooth|ortho|eye|prosthet|maxillofacial|oromax", str(nm.get(x)), re.I))
                                   or ft.get(x) == "dentist")
    lost = set(only[dentaleye].unique_id) - set(u[~u.claim_id.isin(only[dentaleye].claim_id)].unique_id)
    return res("ultrasound_3d_alternative", "warn" if dentaleye.any() else "pass",
               f"{len(only)} pairs match only through the 3D alternative; {int(dentaleye.sum())} at dental, eye or prosthetics facilities "
               f"({only[dentaleye].unique_id.nunique()} facilities); {len(lost)} facilities have ultrasound only from those", "0",
               "facility name/type rule, independent of the auditor's hand labels", only[dentaleye].claim_id.head(5).tolist())


def check_negation_technique_recount():
    """CL-6: kb negation-cued pairs that no non-technique negation alternative explains."""
    rest = re.compile(r"\bnot (available|offered|provided|present|performed|listed|done|equipped)|\bdo(es)? not (have|offer|provide|list|perform)"
                      r"|n't (have|offer|provide)|unavailable|\bno [a-z ]{0,25}(facility|facilities|services?|units?|available|on[- ]?site)\b"
                      r"|\bwithout dialysis|\bno burns?\b", re.I)
    m = matches().join(ctext(), on="claim_id")
    n = m[m.nonoffer_cue == "negation"]
    only = n[~n.text.map(lambda s: bool(rest.search(s)))]
    wrong_match = only[only.service.isin(["de_addiction"]) | only.text.str.contains("Ayurveda", case=False)]
    return res("negation_technique_recount", "warn" if len(only) else "pass",
               f"{len(only)} / {len(n)} negation-cued pairs fired only by technique wording; {len(wrong_match)} of them are wrong matches the cue happens to remove",
               "0", f"by service {only.service.value_counts().to_dict()}", only.claim_id.head(5).tolist())


def check_spine_neuro_recount():
    """CL-7 recount plus the documented rationale."""
    sm = pd.read_csv(f"{ROOT}/kb/taxonomy/specialty_map.csv", keep_default_na=False)
    loc = set(pd.read_parquet(f"{V1}/facility_location.parquet", columns=["unique_id"]).unique_id)
    rows = [(u, s) for u, j in kept()[["unique_id", "specialties"]].itertuples(index=False)
            if isinstance(j, str) and j.startswith("[") for s in json.loads(j) if isinstance(s, str)]
    sp = pd.DataFrame(rows, columns=["u", "s"])
    sp = sp[sp.u.isin(loc)].drop_duplicates()
    neu = set(sm[sm.service_id.str.split(";").map(lambda x: "neurosurgery" in x)].specialty)
    spine = set(sp[sp.s == "spineNeurosurgery"].u)
    other = set(sp[sp.s.isin(neu - {"spineNeurosurgery"})].u) | set(matches().query("service == 'neurosurgery'").unique_id)
    doc = "spineNeurosurgery stays neurosurgery" in open(f"{ROOT}/kb/taxonomy/TAXONOMY.md").read()
    return res("spine_neuro_recount", "pass" if doc else "warn", f"{len(spine - other)} / {len(spine)} facilities", "documented decision",
               f"TAXONOMY.md item 11 documents the label: {doc}; evidence weight 0.4166 is fitted from 284/687 text positives")


# ---------------------------------------------------------------- CL-5, CL-8

ALIASES = [{"bijapur", "vijayapura"}, {"pondicherry", "puducherry"}, {"bombay", "mumbai", "mumbai suburban", "mumbai city"}, {"madras", "chennai"},
           {"calcutta", "kolkata"}, {"bangalore", "bengaluru", "bangalore urban", "bengaluru urban", "bangalore rural"}, {"gurgaon", "gurugram"},
           {"trivandrum", "thiruvananthapuram"}, {"cochin", "kochi", "ernakulam"}, {"calicut", "kozhikode"}, {"poona", "pune"},
           {"baroda", "vadodara"}, {"allahabad", "prayagraj"}, {"belgaum", "belagavi"}, {"gulbarga", "kalaburagi"}, {"mysore", "mysuru"},
           {"mangalore", "mangaluru", "dakshina kannada"}, {"orissa", "odisha"}, {"tanjore", "thanjavur"}, {"shimoga", "shivamogga"},
           {"hubli", "hubballi", "dharwad"}, {"tumkur", "tumakuru"}, {"bellary", "ballari"}, {"aurangabad", "chhatrapati sambhajinagar"},
           {"ahmednagar", "ahilyanagar"}, {"faizabad", "ayodhya"}, {"kadapa", "ysr", "cuddapah"},
           {"new delhi", "delhi", "south delhi", "south west delhi", "west delhi", "north delhi", "east delhi", "central delhi",
            "north west delhi", "north east delhi", "shahdara", "south east delhi"},
           {"rangareddy", "ranga reddy", "hyderabad"}, {"medchal", "medchal malkajgiri", "hyderabad"}]


def check_other_facility_own_place_recount():
    """CL-5: place-only other_facility sentences whose every place is the record's own city/district/state (literal, alias,
    pre-2014 Andhra Pradesh for Telangana, or a road name). Written independently; sample of 20 hits read by hand: 20/20 own place."""
    c = claims()
    f = pd.read_parquet(f"{V1}/facility_location.parquet", columns=["unique_id", "address_city", "district", "state_final", "address_stateOrRegion"])
    o = c[(c.attribution == "other_facility") & (c.foreign_names == "") & (c.sibling_names == "")].join(f.set_index("unique_id"), on="unique_id")
    n = lambda s: re.sub(r"[^a-z ]", "", str(s).lower()).strip()  # noqa: E731
    hits, literal = [], 0
    for r in o.itertuples():
        places = [p for p in (r.places_other_state + "; " + r.places_other_district).split("; ") if p]
        mine = {n(r.address_city), n(r.district), n(r.state_final), n(r.address_stateOrRegion)} - {"", "nan", "none"}
        lit = all(p in mine for p in places)
        for g in ALIASES:
            if mine & g:
                mine |= g
        t = r.text.lower()
        ok = all(p in mine or (p == "andhra pradesh" and str(r.state_final).upper() == "TELANGANA")
                 or re.search(re.escape(p) + r"\w*\s+(bapat\s+)?(road|rd|marg|nagar|colony|street|chowk|lane|layout|gate)\b", t) for p in places)
        if ok:
            hits.append(r.claim_id)
            literal += lit
    h = o[o.claim_id.isin(hits)]
    h[["claim_id", "unique_id", "text", "places_other_state", "places_other_district", "district"]].to_csv(f"{OUT}/own_place_recount.csv", index=False)
    aud = pd.read_csv(f"{ROOT}/validation/claims/out/other_facility_own_place_alias.csv")
    return res("other_facility_own_place_recount", "warn" if hits else "pass",
               f"{len(hits)} / {len(c[c.attribution == 'other_facility'])} other_facility sentences in {h.unique_id.nunique()} records "
               f"({literal} name the record's own district or city literally)", "0",
               f"place-only other_facility sentences {len(o)}; auditor reported 126 in 52 records, its CSV has {len(aud)} rows in "
               f"{aud.unique_id.nunique()} records and no saved code writes it", hits[:5])


def check_description_fragments_recount():
    """CL-8: description sentences cut at a title or company abbreviation, or 3 chars or fewer; 'etc.' endings excluded."""
    d = claims()[claims().field == "description"]
    ab = d.text.str.contains(r"(?:^|\s)\(?(?:Dr|Mr|Mrs|Ms|St|No|Pvt|Ltd|Co|Sr|Jr|Prof|Rd|Hon|Smt|Shri|Sri|Govt|Dept|Vol|vs|e\.g|i\.e|M\.D|M\.S)\.$")
    short = d.text.str.len() <= 3
    etc = d.text.str.endswith("etc.")
    bad = d[ab | short]
    return res("description_fragments_recount", "warn" if len(bad) else "pass",
               f"{len(bad)} / {len(d)} ({len(bad) / len(d):.1%}) description sentences", "< 1%",
               f"abbreviation ends {int(ab.sum())}, short {int(short.sum())}, 'etc.' endings not counted {int(etc.sum())}; 'Dr.' alone ends "
               f"{int(d.text.str.endswith('Dr.').sum())}", bad.claim_id.head(5).tolist())


# ---------------------------------------------------------------- missed issues

def check_cleaning_csection_word_section():
    """cleaning/claims/lexicon.py csection core 'c-? ?section' has no left word boundary, so 'economic sections',
    'paediatric section', 'Prosthetic Section' and 'IPC sections' are tagged C-section. kb fixed it (lexicon_src.py:289) but
    derived/v1 grades, data_point_scores, app/facts and the planner's comprehensive_emoc read the cleaning tags."""
    c = claims()
    tagged = c[c.services.str.split("|").map(lambda s: "csection" in s)]
    bad = tagged[tagged.text.str.contains(r"[a-z]c[- ]?sections?\b", case=False) & ~tagged.text.str.contains(r"\bc-? ?section|caesar|cesar|LSCS", case=False)]
    good = set(tagged[~tagged.claim_id.isin(bad.claim_id) & (tagged.attribution != "other_facility") & ~tagged.nonoffer].unique_id)
    only = set(bad.unique_id) - good
    a = app_pairs()
    app = a[(a.svc == "emergency_csection") & a.uid.isin(only)]
    pr = planner_rows()
    pl = pr[(pr.cap == "comprehensive_emoc") & pr.uid.isin(only)]
    return res("cleaning_csection_word_section", "fail" if len(app) else "pass",
               f"{len(bad)} sentences; {len(only)} facilities whose only C-section evidence is these; {len(app)} in app pairs.emergency_csection "
               f"(grades {app.grade.value_counts().to_dict()}); {len(pl)} planner comprehensive_emoc rows (p {sorted(pl.p.round(2).tolist())})",
               "0", "kb lexicon.json has '\\bc-? ?section' and 0 such matches",
               [f"{r.claim_id}: {r.text[:70]!r}" for r in bad.head(5).itertuples()])


def check_cleaning_vs_kb_tag_drift():
    """The 8 cleaning services feed v1 grades and the app; kb copies feed model #11. lexicon.json says they were copied
    unchanged, but kb later added exclusions. Sentences tagged by cleaning and not by kb, and the app pairs that rest on them."""
    mp = {"dialysis": "dialysis", "csection": "emergency_csection", "mri": "mri", "icu": "icu", "nicu": "nicu", "burns": "burn_care",
          "cardiac_surgery": "cardiac_surgery"}
    app_map = {"csection": "emergency_csection", "burns": "burn_care"}
    c = claims()
    m = matches()
    a = app_pairs()
    out, ex, napp = {}, [], 0
    for s, k in mp.items():
        tagged = c[c.services.str.split("|").map(lambda x: s in x)]
        only = set(tagged.claim_id) - set(m[m.service == k].claim_id)
        kbonly = set(m[m.service == k].claim_id) - set(tagged.claim_id)
        good = set(tagged[~tagged.claim_id.isin(only) & (tagged.attribution != "other_facility") & ~tagged.nonoffer].unique_id)
        lost = set(tagged[tagged.claim_id.isin(only)].unique_id) - good
        inapp = a[(a.svc == app_map.get(s, s)) & a.uid.isin(lost)]
        napp += len(inapp)
        out[s] = dict(cleaning_only=len(only), kb_only=len(kbonly), facilities_only_from_these=len(lost), in_app=len(inapp))
        ex += [f"{s} {u[:8]} {g}" for u, g in zip(inapp.uid, inapp.grade)]
    return res("cleaning_vs_kb_tag_drift", "warn" if napp else "pass", f"{napp} app pairs rest only on sentences kb no longer tags", "0",
               json.dumps(out) + "; trauma is split into emergency_24x7 and trauma_care in kb by design and is left out", ex)


DENTAL = r"dental|dentist|teeth|tooth|smile|orthodont"


def check_planner_dental_scope():
    """Planner proposed capabilities come from evidence-word matches with no facility-type scope rule, so dental clinics get
    general_surgery_ot ('dental surgeon', 'anesthesia'), ct_scan (CBCT 'computed tomography'), orthopaedics ('dentofacial
    orthopaedics') and laboratory ('dental laboratory') at p 0.71-0.78."""
    d = planner_rows()
    d = d[d.status == "proposed"]
    ft, nm = ftype()
    dental = d.uid.map(lambda u: ft.get(u) == "dentist" or bool(re.search(DENTAL, str(nm.get(u)), re.I)))
    x = d[dental]
    hard = x[x.cap.isin(["general_surgery_ot", "ct_scan", "orthopaedics", "laboratory", "plastic_surgery", "neurosurgery", "trauma_centre",
                         "ventilator", "iv_fluid_resuscitation", "pci_cath_lab", "nephrology", "blood_transfusion"])]
    t = ctext()
    ex = [f"{r.cap} {nm.get(r.uid)[:28]}: {t[r.ids[0]][:50]!r}" for r in hard.sample(min(5, len(hard)), random_state=1).itertuples()]
    return res("planner_dental_scope", "fail" if len(hard) else "pass",
               f"{len(x)} proposed (capability, facility) rows at {x.uid.nunique()} dental facilities; {len(hard)} are hospital capabilities",
               "0", f"by capability {x.cap.value_counts().to_dict()}; planner/data_v1.py _match has no scope rule "
               "(cleaning/claims/lexicon.py scope_conflict exists but is not used)", ex)


def check_planner_proposed_precision_handread():
    """Seeded sample (seed 20261121) of 50 distinct proposed-capability citations, read by hand."""
    lab = pd.read_csv(f"{LAB}/planner_proposed_sample50.csv", keep_default_na=False)
    pc = planner_cited()
    pc = pc[pc.status == "proposed"][["cap", "cid"]].drop_duplicates()
    regen = pc.sample(50, random_state=20261121)
    stale = sorted(zip(regen.cap, regen.cid)) != sorted(zip(lab.cap, lab.cid))
    k = int((lab.verdict == "correct").sum())
    n = len(lab)
    return res("planner_proposed_precision_handread", "warn" if stale or k / n < 0.9 else "pass",
               f"{k}/{n} = {k / n:.2f} Wilson {wilson(k, n)}; wrong {int((lab.verdict == 'wrong').sum())}, unclear {int((lab.verdict == 'unclear').sum())}",
               ">= 0.90", "sample stale" if stale else f"population {len(pc)} distinct citations; errors are dental or ENT clinics matching broad words",
               [f"{r.cap} {r.cid}: {r.note}" for r in lab[lab.verdict == "wrong"].head(5).itertuples()])


def check_planner_echo_promotion():
    """A proposed capability gets p_two (0.783) instead of p_one (0.715) when two or more own sentences match. Recompute the
    planner match and count facilities whose 'two or more' are echoes of one sentence (same normalised text)."""
    c = claims()
    c = c[(c.attribution != "other_facility") & ~c.nonoffer]
    norm = c.text.str.lower().str.replace(r"[^a-z0-9]+", " ", regex=True).str.strip()
    pr = planner_rows()
    promoted, ex = 0, []
    for cap, cd in caps().items():
        if cd["kb_status"] != "proposed":
            continue
        w = cd["evidence_words"]
        strict = [x for x in w if x.isupper() and len(x) <= 5]
        loose = [x for x in w if x not in strict]
        parts = ([r"(?i:\b(?:" + "|".join(map(re.escape, loose)) + r")\b)"] if loose else []) + \
                ([r"\b(?:" + "|".join(map(re.escape, strict)) + r")\b"] if strict else [])
        hit = c.text.str.contains("|".join(parts), regex=True)
        g = pd.DataFrame({"u": c.unique_id[hit], "n": norm[hit]}).groupby("u").n.agg(["size", "nunique"])
        e = g[(g["size"] >= 2) & (g["nunique"] == 1)]
        pp = pr[(pr.cap == cap) & pr.uid.isin(e.index)].p
        promoted += int((pp == pr[pr.status == "proposed"].p.max()).sum())
        ex += [f"{cap} {u[:8]}" for u in e.index[:1]]
    two = int((pr[pr.status == "proposed"].p == pr[pr.status == "proposed"].p.max()).sum())
    return res("planner_echo_promotion", "warn" if promoted else "pass",
               f"{promoted} proposed (capability, facility) rows reach p_two (planner p checked) only through repeated identical sentences", "0",
               f"rows at p_two in planner_v1: {two}; planner/data_v1.py capability_p counts matches without dup_in_record", ex)


def check_auditor_rerun_identical():
    """The auditor's checks.py, re-run by rerun_auditor.py into verify/out, must reproduce its results.json."""
    p = f"{OUT}/auditor_rerun.json"
    if not os.path.exists(p):
        return res("auditor_rerun_identical", "not_run", "run rerun_auditor.py first", "", "")
    a = {x["name"]: (x["status"], x["metric"]) for x in json.load(open(f"{ROOT}/validation/claims/out/results.json"))}
    b = {x["name"]: (x["status"], x["metric"]) for x in json.load(open(p))}
    diff = [k for k in a.keys() | b.keys() if a.get(k) != b.get(k)]
    return res("auditor_rerun_identical", "pass" if not diff else "fail", f"{len(diff)} of {len(a)} checks differ", "0", "", diff)


CHECKS = [v for k, v in sorted(globals().items()) if k.startswith("check_") and callable(v)]


def main(only=None):
    os.makedirs(OUT, exist_ok=True)
    out = []
    for f in CHECKS:
        if only and f.__name__[6:] not in only:
            continue
        try:
            r = f()
        except Exception as e:  # reported, never skipped
            r = res(f.__name__[6:], "fail", "check crashed", "", f"{type(e).__name__}: {e}")
        out.append(r)
        print(f"[{r['status']:7}] {r['name']}: {r['metric']}", flush=True)
    json.dump(out, open(f"{OUT}/results.json" if not only else f"{OUT}/results_partial.json", "w"), indent=1, default=str)
    return out


if __name__ == "__main__":
    main(set(sys.argv[1:]) or None)
