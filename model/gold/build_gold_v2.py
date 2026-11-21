"""Gold set v2: 140 new (facility, service) pairs, an overlap subset for double labeling, and dev/test splits.

Local only (Parquet snapshot plus frozen audit outputs); no warehouse calls, no web.
Run: /Users/karthikvattem/projects/datathon/.venv/bin/python build_gold_v2.py
Writes sample_v2.json, overlap_v2.json, splits.json and sample_v2_stats.json next to this script.

Services (gold key -> claims-audit key): dialysis, emergency_csection -> csection, nicu, cardiac_surgery,
mri, burn_care -> burns, trauma_emergency -> trauma. 20 pairs per service, 5 per stratum.

Detectors reused (read-only, from /Users/karthikvattem/projects/datathon/audit):
  claims/out/mentions.parquet  core service mentions per sentence, with non-offer cues (negation, referral,
                               future, partner, camp, past, hedge) and cross-state place flag `foreign`
  claims/out/grades.parquet    per (facility, service) aggregates: n_core, n_clean, n_fields_own, enum_hit,
                               scope_conflict, grade
  claims/services.py           scope_conflict (single-specialty names), prereq and related regexes per service (re-applied here to NON-mention sentences)
  merge/out/sentences_flagged.parquet  facility-name detector: has_foreign with context == "direct", has_sibling
  geo/out facility_geo.parquet d_pin_km (robust PIN centroid), state_vs_pin_mismatch, pin_vs_coord_state_mismatch,
                               coord_outside, city_match_pin / city_match_near
  geo/facility_district.parquet  district per facility
  identity/out/dup_groups.csv  grp_strong duplicate clusters (split grouping); chain_membership.csv (chains excluded)
  ground_truth/build_sample.py FLAGSHIP and GENERIC_NAME name filters, v1 service regexes, spread_quotes

Strata (my rules, applied per facility and service):
  geo_ok     d_pin_km <= 25, no stated-state vs PIN-state mismatch, no PIN vs coordinate state mismatch,
             coordinates inside India, stated city matches the PIN's or the nearest PIN's place names
  strong     geo_ok, own clean mentions in 2+ fields, at least one clinical prerequisite found in a sentence
             that is NOT itself a mention (or in the specialties enum), no non-offer cue on any mention,
             no named other facility, no cross-state place, no single-specialty scope conflict
  weak       geo_ok, exactly one mention sentence in the whole record, no specialty enum hit, no prerequisite
             and no related term in any other sentence, the mention is positive (no non-offer cue).
             Exception, emergency_csection: the obstetrics prerequisite and the related terms (maternity,
             delivery, labour room) are ignored, because nearly every record that mentions C-section is an
             obstetric record; only an operating theatre or anaesthesia sentence counts as corroboration
  suspect    a positive mention exists AND (a mention sentence names another facility or a sibling branch
             [merge detector], OR d_pin_km > 50, OR stated state differs from PIN state). Slots per service:
             2 named_other, 2 coord_far, 1 state_mismatch, falling back to any suspect kind when a pool is empty
  no_mention geo_ok, no core or enum mention of the service (claims audit) and no v1-regex hit in any text field,
             and (beds >= 50 or doctors >= 10 or a public / district hospital), excluding single-specialty
             names (claims scope_conflict) and cancer, TB, chest, psychiatric, leprosy and AYUSH institutes.
             2 slots public, 3 large
Mention fix: C-section mentions whose only core match is mid-word ("economic sections") are dropped
before stratifying (MENTION_FP); counts below are recomputed from the remaining mention sentences.
Eligible facilities: well-formed rows, name used once in the dataset, 2+ words, not FLAGSHIP (v1 list plus FLAGSHIP_EXTRA), not GENERIC_NAME,
not in a known chain, not one of the 36 v1 facilities or their duplicate clusters. One pair per facility.
Spread: greedy pick inside each shuffled pool, lowest (state count - bonus) first; bonus 2 for the focus
states (Bihar, UP, Jharkhand, Odisha, MP, Rajasthan, Assam). rural_pin (at least half of the PIN's post offices
are India Post branch offices, "BO", i.e. village offices) is reported, not selected on: a rural bonus of 0.5
pushed the sample to 104/140 rural PINs against 28% of all facilities, which would misstate precision for towns.
"""
import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

AUDIT = Path("/Users/karthikvattem/projects/datathon/audit")
RAW = Path("/Users/karthikvattem/projects/datathon/data/raw")
OUT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # the imports below must not write .pyc files into the read-only audit tree
sys.path[:0] = [str(AUDIT / "claims"), str(AUDIT / "ground_truth")]
import services as cs  # noqa: E402  claims-audit detectors
from common import load  # noqa: E402  claims-audit loader (well-formed rows, parsed lists)
import build_sample as v1  # noqa: E402  v1 filters and helpers

SEED = 20261122
SPLIT_SALT = "vf-gold-split-v1"
SVC = {"dialysis": "dialysis", "emergency_csection": "csection", "nicu": "nicu", "cardiac_surgery": "cardiac_surgery",
       "mri": "mri", "burn_care": "burns", "trauma_emergency": "trauma"}
STRATA = ("strong", "weak", "suspect", "no_mention")
PER_STRATUM = 5
GEO_OK_KM, GEO_FAR_KM = 25.0, 50.0
FOCUS = {"BIHAR", "UTTAR PRADESH", "JHARKHAND", "ODISHA", "MADHYA PRADESH", "RAJASTHAN", "ASSAM"}
FOCUS_BONUS = 2
SUSPECT_SLOTS = ["named_other", "named_other", "coord_far", "coord_far", "state_mismatch"]
NOMENTION_SLOTS = ["public", "public", "large", "large", "large"]
PUBLIC_NAME = re.compile(r"\b(district|sadar|civil|zila|zilla|sub[- ]?divisional|referral|general|government|govt\.?)\b"
                         r".{0,30}\bhospital\b|\bgovernment medical college\b|\bgovt\.? medical college\b", re.I)
N_OVERLAP = 30
WEAK_IGNORE_PREREQ = {"emergency_csection": {"obstetrics"}}
WEAK_IGNORE_RELATED = {"emergency_csection"}
# Audit-detector false positive: "economic sections" matches the C-section core regex mid-word.
MENTION_FP = {"csection": re.compile(r"[a-z]c-? ?sections?", re.I)}
# no_mention probes exclude single-specialty and AYUSH institutions, where absence of the service is expected
NOMENTION_SCOPE = re.compile(r"cancer|onco|tubercul|\btb\b|chest|psychiatr|mental|leprosy|indian medicine|ayush"
                             r"|homoeo|homeo|ayurved|unani|siddha|naturopath", re.I)
# Hand-added to v1 FLAGSHIP after the first draw surfaced them: well-known teaching / brand institutions.
FLAGSHIP_EXTRA = re.compile(r"KIMS|Sher-?I-?Kashmir|\bSKIMS\b|BYL Nair|Niloufer|Patna Medical College|Father Muller"
                            r"|Christian Medical|St\.? John'?s Medical|\bPGI\b|\bIGIMS\b|Indira Gandhi Institute of Medical", re.I)


def h(s):
    return int(hashlib.sha256(f"{SPLIT_SALT}:{s}".encode()).hexdigest(), 16)


def sentences(r):
    """Same split as claims/audit.py and merge/common.py, so (field, text) keys join exactly."""
    for f in cs_fields():
        for s in getattr(r, f + "_l"):
            yield f, s
    for s in re.split(r"(?<=[.!?])\s+", r.description_s):
        if s.strip():
            yield "description", s.strip()


def cs_fields():
    return ["procedure", "equipment", "capability"]


def load_inputs():
    df = load()
    geo = pd.read_parquet(AUDIT / "geo/facility_geo.parquet")
    dist = pd.read_parquet(AUDIT / "geo/facility_district.parquet")[["unique_id", "district"]]
    df = df.merge(geo[["unique_id", "d_pin_km", "state_vs_pin_mismatch", "pin_vs_coord_state_mismatch", "coord_outside",
                       "city_match_pin", "city_match_near", "state_n", "pin_state", "pin"]], on="unique_id", how="left")
    df = df.merge(dist, on="unique_id", how="left")
    pdir = pd.read_parquet(RAW / "india_post_pincode_directory.parquet")
    bo_share = pdir.groupby("pincode").officetype.apply(lambda x: (x == "BO").mean())
    df["bo_share"] = df.pin.map(bo_share)
    df["rural_pin"] = df.bo_share >= 0.5
    df["state_key"] = df.state_n.where(df.state_n.notna() & (df.state_n != ""), df.pin_state).fillna("UNPARSED")
    grades = pd.read_parquet(AUDIT / "claims/out/grades.parquet")
    ment = pd.read_parquet(AUDIT / "claims/out/mentions.parquet")
    sf = pd.read_parquet(AUDIT / "merge/out/sentences_flagged.parquet",
                         columns=["unique_id", "field", "text", "has_foreign", "context", "has_sibling", "foreign_names", "sibling_names"])
    sf = sf[(sf.has_foreign & (sf.context == "direct")) | sf.has_sibling]
    named = {(u, f, t): (fn or sn) for u, f, t, fn, sn in sf[["unique_id", "field", "text", "foreign_names", "sibling_names"]].itertuples(index=False)}
    dup = pd.read_csv(AUDIT / "identity/out/dup_groups.csv")
    chain = pd.read_csv(AUDIT / "identity/out/chain_membership.csv")
    v1_pairs = json.loads((AUDIT / "ground_truth/sample.json").read_text())
    return df, grades, ment, named, dup, chain, v1_pairs


def group_keys(dup):
    """unique_id -> split group key: smallest unique_id in its grp_strong duplicate cluster, else itself."""
    d = dup[dup.grp_strong.notna()]
    rep = d.groupby("grp_strong").unique_id.min()
    return {u: rep[g] for u, g in zip(d.unique_id, d.grp_strong)}


def geo_ok(r):
    return (pd.notna(r.d_pin_km) and r.d_pin_km <= GEO_OK_KM and not r.state_vs_pin_mismatch
            and not r.pin_vs_coord_state_mismatch and not r.coord_outside
            and bool(r.city_match_pin or r.city_match_near))


def prereq_hits(spec, other, d):
    out = []
    for name, (prx, pset) in d["prereqs"].items():
        hit = next((s for _, s in other if prx.search(s)), None)
        if hit:
            out.append({"prereq": name, "field": next(f for f, s in other if s == hit), "text": hit[:300]})
        elif spec & {cs.norm_spec(x) for x in pset}:
            out.append({"prereq": name, "field": "specialties", "text": sorted(spec & {cs.norm_spec(x) for x in pset})[0]})
    return out


def analyse(r, gsvc, g, m, named):
    """Feature dict for one (facility, service), or None if the facility has no stratum for it."""
    key = SVC[gsvc]
    d = cs.SERVICES[key]
    sents = list(sentences(r))
    spec = {cs.norm_spec(x) for x in r.specialties_l}
    ok = geo_ok(r)
    far = pd.notna(r.d_pin_km) and r.d_pin_km > GEO_FAR_KM
    smis = bool(r.state_vs_pin_mismatch)
    base = dict(d_pin_km=None if pd.isna(r.d_pin_km) else round(float(r.d_pin_km), 1), geo_ok=ok,
                stated_state=r.state_n, pin_state=r.pin_state, state_mismatch=smis,
                city_match=bool(r.city_match_pin or r.city_match_near), rural_pin=bool(r.rural_pin),
                beds=None if pd.isna(r.beds) else r.beds, doctors=None if pd.isna(r.ndoc) else r.ndoc)
    if g is not None and m.empty and not g.enum_hit:
        g = None  # every audit mention was a detector false positive (MENTION_FP)
    if g is None:  # no core or enum mention in the claims audit
        if NOMENTION_SCOPE.search(r.name) or cs.scope_conflict(r.name, r.facilityTypeId, key):
            return None
        rx = re.compile(v1.SERVICES[gsvc][0], re.I) if gsvc in v1.SERVICES else d["core"]
        if any(rx.search(s) for _, s in sents) or not ok:
            return None
        public = bool(PUBLIC_NAME.search(r.name)) or (r.operatorTypeId in ("public", "government") and r.facilityTypeId == "hospital")
        large = (pd.notna(r.beds) and r.beds >= 50) or (pd.notna(r.ndoc) and r.ndoc >= 10)
        if not (public or large):
            return None
        related = [s[:300] for _, s in sents if d["related"].search(s)][:2]
        return dict(stratum="no_mention", kinds=(["public"] if public else []) + (["large"] if large else []),
                    claims=[], prereq=prereq_hits(spec, sents, d), related=related, n_fields_own=0, n_core=0, **base)
    clean = m[~m.nonoffer]
    own = clean[~clean.foreign]
    n_core, n_clean, n_fields_own, any_foreign = len(m), len(clean), own.field.nunique(), bool(m.foreign.any())
    mkeys = set(zip(m.field, m.sentence))
    other = [(f, s) for f, s in sents if (f, s) not in mkeys]
    named_hits = [{"field": f, "text": s, "names": named[(r.unique_id, f, s)]} for f, s in sorted(mkeys) if (r.unique_id, f, s) in named]
    pre = prereq_hits(spec, other, d)
    related = [s[:300] for _, s in other if d["related"].search(s)]
    claims = [{"field": f, "text": s} for f, s in zip(clean.field, clean.sentence)]
    claims += [{"field": "specialties", "text": x} for x in sorted(spec & d["spec_core"])]
    feat = dict(claims=claims, named_other=named_hits, prereq=pre, related=related[:2], n_core=n_core,
                n_clean=n_clean, n_fields_own=n_fields_own, enum_hit=bool(g.enum_hit),
                cross_state_place=any_foreign, scope_conflict=bool(g.scope_conflict), claims_grade=g.grade, **base)
    kinds = (["named_other"] if named_hits else []) + (["coord_far"] if far else []) + (["state_mismatch"] if smis else [])
    if n_clean >= 1 and kinds:
        return dict(feat, stratum="suspect", kinds=kinds)
    clean_record = ok and not named_hits and not any_foreign and n_clean == n_core
    if clean_record and n_fields_own >= 2 and pre and not g.scope_conflict:
        return dict(feat, stratum="strong", kinds=[])
    # ponytail: for C-section the department itself (obstetrics, maternity, delivery, labour room) is in almost
    # every record (3 of 199 single-mention records lack it), so only OT and anaesthesia count as corroboration.
    pre_w = [x for x in pre if x["prereq"] not in WEAK_IGNORE_PREREQ.get(gsvc, ())]
    related_w = [] if gsvc in WEAK_IGNORE_RELATED else related
    if clean_record and n_core == 1 and not g.enum_hit and not pre_w and not related_w:
        return dict(feat, stratum="weak", kinds=[])
    return None


def quotes_for(a):
    """Suspect pairs show the sentence that names another facility first; then round-robin across fields."""
    first = [{"field": x["field"], "text": x["text"][:500]} for x in a.get("named_other", [])]
    rest = [c for c in v1.spread_quotes(a["claims"], k=4) if (c["field"], c["text"]) not in {(q["field"], q["text"]) for q in first}]
    return (first + rest)[:4]


def signals(a):
    p = [f"stratum_rule={a['stratum']}", f"kinds={'|'.join(a['kinds']) or 'none'}", f"mention_sentences={a['n_core']}",
         f"fields_own={a['n_fields_own']}", f"prereq={'|'.join(x['prereq'] for x in a['prereq']) or 'none'}",
         f"pin_centroid_km={a['d_pin_km']}", f"stated_state={a['stated_state']}", f"pin_state={a['pin_state']}",
         f"city_matches_pin={a['city_match']}", f"rural_pin={a['rural_pin']}", f"beds={a['beds']}", f"doctors={a['doctors']}"]
    if a.get("named_other"):
        p.append("other_facility_named=" + " | ".join(x["names"] for x in a["named_other"][:2]))
    if a.get("claims_grade"):
        p.append(f"claims_audit_grade={a['claims_grade']}")
    return "; ".join(p)


def build_pools(df, grades, ment, named, excluded):
    names = Counter(df.name.str.lower().str.strip())
    elig = df[df.name.map(lambda n: names[n.lower().strip()] == 1) & ~df.name.map(lambda n: bool(v1.FLAGSHIP.search(n) or FLAGSHIP_EXTRA.search(n)))
              & ~df.name.str.strip().str.match(v1.GENERIC_NAME) & (df.name.str.split().str.len() >= 2)
              & ~df.unique_id.isin(excluded)]
    gidx = {(u, s): g for u, s, g in zip(grades.unique_id, grades.service, grades.itertuples())}
    fp = ment.apply(lambda x: x.service in MENTION_FP and not cs.SERVICES[x.service]["core"].search(
        MENTION_FP[x.service].sub(" ", x.sentence)), axis=1)
    ment = ment[~fp]
    midx = {k: g for k, g in ment.groupby(["unique_id", "service"])}
    pools = defaultdict(list)
    for r in elig.itertuples():
        for gsvc, key in SVC.items():
            a = analyse(r, gsvc, gidx.get((r.unique_id, key)), midx.get((r.unique_id, key), ment.iloc[:0]), named)
            if a:
                pools[(gsvc, a["stratum"])].append((r, a))
    return pools, len(elig)


def pick(pools, rng):
    used, state_count, pairs = set(), Counter(), []
    cells = sorted(pools, key=lambda c: (len(pools[c]), c))  # scarce cells choose first
    for gsvc, stratum in cells:
        pool = list(pools[(gsvc, stratum)])
        rng.shuffle(pool)
        slots = SUSPECT_SLOTS if stratum == "suspect" else NOMENTION_SLOTS if stratum == "no_mention" else [None] * PER_STRATUM
        for n, slot in enumerate(slots, 1):
            cand = [(i, ra) for i, ra in enumerate(pool) if ra[0].unique_id not in used]
            want = [c for c in cand if slot in c[1][1]["kinds"]] or cand
            if not want:
                raise SystemExit(f"pool exhausted: {gsvc} {stratum}")
            score = lambda c: (state_count[c[1][0].state_key] - FOCUS_BONUS * (c[1][0].state_key in FOCUS), c[0])
            r, a = min(want, key=score)[1]
            used.add(r.unique_id)
            state_count[r.state_key] += 1
            pairs.append(dict(
                pair_id=f"v2_{gsvc}_{stratum}_{n}", unique_id=r.unique_id, name=r.name, city=r.address_city,
                state=r.address_stateOrRegion, pin=r.address_zipOrPostcode, district=r.district, state_key=r.state_key,
                service=gsvc, stratum=stratum, slot=slot, claim_quotes=quotes_for(a),
                prereq_quotes=a["prereq"][:3], related_quotes=a["related"],
                website=None if v1.is_null(r.officialWebsite) else r.officialWebsite,
                source_urls=list(dict.fromkeys(r.source_urls_l))[:3], signals=signals(a),
                features={k: a[k] for k in ("kinds", "n_core", "n_fields_own", "d_pin_km", "geo_ok", "state_mismatch",
                                            "city_match", "rural_pin", "beds", "doctors")}))
    order = {(s, t): i for i, (s, t) in enumerate((s, t) for s in SVC for t in STRATA)}
    return sorted(pairs, key=lambda p: (order[(p["service"], p["stratum"])], p["pair_id"]))


def overlap(pairs):
    """One pair per (service, stratum) cell (lowest hash), then the 2 lowest-hash remaining pairs from distinct services."""
    by_cell = defaultdict(list)
    for p in pairs:
        by_cell[(p["service"], p["stratum"])].append(p)
    chosen = [min(v, key=lambda p: h(p["pair_id"]))["pair_id"] for _, v in sorted(by_cell.items())]
    rest = sorted((p for p in pairs if p["pair_id"] not in chosen), key=lambda p: h(p["pair_id"]))
    extra_svcs = set()
    for p in rest:
        if len(chosen) == N_OVERLAP:
            break
        if p["service"] not in extra_svcs:
            chosen.append(p["pair_id"])
            extra_svcs.add(p["service"])
    return chosen


def splits(all_pairs, gkey):
    """Grouped, stratified, deterministic dev/test assignment.

    Group = duplicate cluster of the facility (identity grp_strong), else the unique_id. Cells = (service, stratum).
    Walk cells in sorted order; inside a cell walk groups by sha256(salt:group). An unassigned group goes to the
    split with fewer pairs in that cell so far (ties: hash parity), and all its pairs, in any cell, move with it.
    """
    grp = {p["pair_id"]: gkey.get(p["unique_id"], p["unique_id"]) for p in all_pairs}
    cells = defaultdict(list)
    for p in all_pairs:
        cells[(p["service"], p["stratum"])].append(p)
    assign, count = {}, defaultdict(Counter)
    for cell in sorted(cells):
        for p in sorted(cells[cell], key=lambda p: (h(grp[p["pair_id"]]), p["pair_id"])):
            g = grp[p["pair_id"]]
            if g in assign:
                continue
            c = count[cell]
            assign[g] = ("dev" if h(g) % 2 == 0 else "test") if c["dev"] == c["test"] else min(("dev", "test"), key=lambda s: c[s])
            for q in all_pairs:
                if grp[q["pair_id"]] == g:
                    count[(q["service"], q["stratum"])][assign[g]] += 1
    out = {p["pair_id"]: assign[grp[p["pair_id"]]] for p in all_pairs}
    for g in set(grp.values()):  # invariant: a facility group never spans both splits
        assert len({out[k] for k, v in grp.items() if v == g}) == 1
    return out, grp, count


def self_check():
    assert PUBLIC_NAME.search("Sadar Hospital, Gaya") and PUBLIC_NAME.search("District Hospital Koraput")
    assert not PUBLIC_NAME.search("Shanti Nursing Home")
    assert MENTION_FP["csection"].search("all economic sections") and not MENTION_FP["csection"].search("LSCS / C-section")
    assert h("a") == h("a") and h("a") != h("b")
    toy = [dict(pair_id=f"p{i}", unique_id=f"u{i % 3}", service="s", stratum="t") for i in range(6)]
    out, _, _ = splits(toy, {})
    assert {out["p0"]} == {out["p3"]} and Counter(out.values())["dev"] in (2, 4)


def main():
    self_check()
    df, grades, ment, named, dup, chain, v1_pairs = load_inputs()
    gkey = group_keys(dup)
    v1_ids = {p["unique_id"] for p in v1_pairs}
    v1_groups = {gkey.get(u, u) for u in v1_ids}
    excluded = v1_ids | {u for u, g in gkey.items() if g in v1_groups} | set(chain[chain.chain.notna()].unique_id)
    pools, n_elig = build_pools(df, grades, ment, named, excluded)
    pairs = pick(pools, random.Random(SEED))
    assert len(pairs) == 140 and len({p["unique_id"] for p in pairs}) == 140
    assert not {(p["unique_id"], p["service"]) for p in pairs} & {(p["unique_id"], p["service"]) for p in v1_pairs}
    ov = overlap(pairs)
    assert len(ov) == N_OVERLAP and len(set(ov)) == N_OVERLAP
    for p in pairs:
        p["double_label"] = p["pair_id"] in ov
    all_pairs = [dict(p, version="v1") for p in v1_pairs] + [dict(p, version="v2") for p in pairs]
    split, grp, count = splits(all_pairs, gkey)

    states = Counter(p["state_key"] for p in pairs)
    stats = dict(
        seed=SEED, split_salt=SPLIT_SALT, wellformed_rows=len(df), eligible_facilities=n_elig, excluded_ids=len(excluded),
        pool_sizes={f"{s}_{t}": len(pools.get((s, t), [])) for s in SVC for t in STRATA},
        pool_suspect_kinds={s: dict(Counter(k for _, a in pools.get((s, "suspect"), []) for k in a["kinds"])) for s in SVC},
        picked_slot_fill={f"{p['service']}_{p['stratum']}_{p['slot']}": p["slot"] in p["features"]["kinds"]
                          for p in pairs if p["slot"]},
        states=len(states), state_counts=dict(states.most_common()),
        focus_state_pairs={s: states.get(s, 0) for s in sorted(FOCUS)},
        rural_pin_pairs=sum(p["features"]["rural_pin"] for p in pairs),
        overlap_by_stratum=dict(Counter(p["stratum"] for p in pairs if p["double_label"])),
        overlap_by_service=dict(Counter(p["service"] for p in pairs if p["double_label"])),
        split_totals=dict(Counter(split.values())),
        split_by_version={v: dict(Counter(split[p["pair_id"]] for p in all_pairs if p["version"] == v)) for v in ("v1", "v2")},
        split_by_cell={f"{c[0]}_{c[1]}": dict(v) for c, v in sorted(count.items())},
        multi_pair_groups=sum(1 for g, n in Counter(grp.values()).items() if n > 1),
    )
    assert stats["states"] >= 15, stats["states"]
    assert all(stats["focus_state_pairs"][s] >= 1 for s in FOCUS), stats["focus_state_pairs"]

    (OUT / "sample_v2.json").write_text(json.dumps(pairs, indent=2, ensure_ascii=True))
    (OUT / "overlap_v2.json").write_text(json.dumps(ov, indent=2))
    (OUT / "splits.json").write_text(json.dumps(dict(
        method=("Grouped by facility duplicate cluster (identity grp_strong, else unique_id), stratified by "
                "(service, stratum), deterministic from sha256('" + SPLIT_SALT + ":' + group key). "
                "Test is frozen: never inspect or tune on it."),
        counts=stats["split_totals"], by_cell=stats["split_by_cell"],
        pairs=[dict(pair_id=p["pair_id"], version=p["version"], unique_id=p["unique_id"], service=p["service"],
                    stratum=p["stratum"], group=grp[p["pair_id"]], split=split[p["pair_id"]]) for p in all_pairs]),
        indent=1))
    (OUT / "sample_v2_stats.json").write_text(json.dumps(stats, indent=1, default=str))
    print(json.dumps({k: stats[k] for k in ("eligible_facilities", "pool_sizes", "states", "focus_state_pairs",
                                            "rural_pin_pairs", "split_totals", "split_by_version", "overlap_by_stratum")}, indent=1))


if __name__ == "__main__":
    main()
