"""Adversarial re-verification of the web_facts audit (validation/web_facts). Independent code: nothing is imported
from the auditor's checks.py. Read-only on every data layer; writes only verify/out/.

Run all:   /Users/karthikvattem/projects/datathon/.venv-viz/bin/python checks.py      (writes out/checks.json)
Run some:  ... checks.py check_v_clock_times check_v_weak_pairs

Every check_<name>() returns dict(name, status, metric, threshold, detail, examples).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
import sys
from collections import defaultdict
from functools import lru_cache

import pandas as pd

ROOT = "/Users/karthikvattem/projects/datathon"
WE = f"{ROOT}/kb/web_evidence/out"
VF = f"{ROOT}/kb/vf_details/out"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
AUD = os.path.dirname(HERE)  # the audited auditor's directory (read only)
MODEL_SVC = {"dialysis", "emergency_csection", "nicu", "cardiac_surgery", "mri", "burn_care", "trauma_care"}  # viz/features/build_features.py:34-35


def wilson(k, n, z=1.96):
    if not n:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 3), round(c + h, 3))


def res(name, status, metric, threshold, detail, examples):
    return {"name": name, "status": status, "metric": metric, "threshold": threshold, "detail": detail, "examples": list(examples)[:5]}


@lru_cache(None)
def T(name):
    base = VF if name in ("facts", "facility_details") else WE
    return pd.read_parquet(f"{base}/{name}.parquet")


@lru_cache(None)
def pages():
    return pd.read_parquet(f"{ROOT}/kb/crawl/pages.parquet")


@lru_cache(None)
def doc(path):
    with gzip.open(os.path.join(ROOT, path), "rt", encoding="utf-8") as fh:
        return json.load(fh)


def usable(df):
    return df[df.attributable & df.status.isin(["ok", "flagged"]) & (df.polarity == "positive")]


# ------------------------------------------------------------------ quotes (re-done with own code)
def check_v_web_quotes():
    """Each fact row: quote occurs inside the stored field at an offset within [seg_start, seg_start+len(segment)]."""
    bad, n, ex, files = 0, 0, [], set()
    for t, seg in (("web_services", "segment"), ("web_hours", "source_text"), ("web_details", "source_text")):
        df = T(t)
        for path, field, q, s, st in zip(df.path, df.field, df.quote, df[seg], df.seg_start):
            n += 1
            files.add(path)
            txt = doc(path).get(field) or ""
            i = txt.find(q, int(st))
            if not q or i < 0 or i + len(q) > int(st) + len(s) or txt[int(st):int(st) + len(s)] != s:
                bad += 1
                ex.append(f"{t} {path} {field}@{st} {q[:50]!r}")
    return res("v_web_quotes", "pass" if bad == 0 else "fail", {"rows": n, "files": len(files), "bad": bad}, "0",
               "quote found at or after seg_start and inside the segment window", ex)


def check_v_identity_quotes():
    """site_identity quotes against the page their *_page_id names (via page_identity), not via sha1(url)."""
    pi = T("page_identity")
    pid_path = dict(zip(pi.page_id, pi.path))
    si = T("site_identity")
    n = bad = nopage = 0
    ex = []
    for qc, fc, pc, uc in (("name_quote", "name_field", "name_page_id", "name_url"), ("pin_quote", "pin_field", "pin_page_id", "pin_url"),
                           ("locality_quote", "locality_field", "locality_page_id", "locality_url")):
        for r in si[si[qc].notna()][[qc, fc, pc, uc, "unique_id"]].itertuples(index=False):
            n += 1
            p = pid_path.get(r[2])
            if p is None:
                nopage += 1
                continue
            d = doc(p)
            if r[0] not in (d.get(r[1]) or "") or d.get("url_final") != r[3]:
                bad += 1
                ex.append(f"{r.unique_id} {qc} {r[0][:50]!r}")
    for qc, fc in (("name_quote", "name_field"), ("pin_quote", "pin_field"), ("loc_quote", "loc_field")):
        for r in pi[pi[qc].notna()][[qc, fc, "path"]].itertuples(index=False):
            n += 1
            if r[0] not in (doc(r[2]).get(r[1]) or ""):
                bad += 1
    return res("v_identity_quotes", "pass" if bad == 0 else "fail", {"quotes": n, "bad": bad, "page_id_not_in_page_identity": nopage}, "0",
               "site_identity via *_page_id -> page_identity.path, url_final must equal the cited url; page_identity in own field", ex)


def check_v_vf_chain():
    """vf facts: quote in source_text, source_text == derived/v1 claim text, claim text inside some raw row of that record."""
    f = T("facts")
    cl = pd.read_parquet(f"{ROOT}/derived/v1/claims.parquet", columns=["claim_id", "unique_id", "field", "text"]).set_index("claim_id")
    raw = pd.read_parquet(f"{ROOT}/data/raw/facilities.parquet", columns=["unique_id", "procedure", "capability", "equipment", "description"])
    blob = defaultdict(str)
    for r in raw.itertuples(index=False):
        for c in ("procedure", "capability", "equipment", "description"):
            v = getattr(r, c)
            if isinstance(v, str):
                if c != "description":
                    try:
                        j = json.loads(v)
                        v = "\n".join(x for x in j if isinstance(x, str)) if isinstance(j, list) else v
                    except ValueError:
                        pass
                blob[(r.unique_id, c)] += "\n" + v
    q_bad = sum(not (isinstance(q, str) and q in s) for q, s in zip(f.quote, f.source_text))
    t = f[f.claim_id.notna()]
    j = t.join(cl, on="claim_id", rsuffix="_c")
    nojoin = int(j.text.isna().sum())
    neq = int((j.text.notna() & ((j.text != j.source_text) | (j.unique_id != j.unique_id_c) | (j.field != j.field_c))).sum())
    rawbad = [cid for cid, u, fl, tx in zip(j.claim_id, j.unique_id, j.field, j.text) if isinstance(tx, str) and tx not in blob[(u, fl)]]
    st = f[f.claim_id.isna()]
    m = {"facts": len(f), "text_facts": len(t), "structured_facts": len(st), "quote_not_in_source": q_bad, "claim_missing": nojoin,
         "claim_text_or_owner_differs": neq, "claim_not_in_raw": len(set(rawbad)), "structured_methods": st.method.value_counts().to_dict()}
    nb = q_bad + nojoin + neq + len(rawbad)
    return res("v_vf_chain", "pass" if nb == 0 else "fail", m, "0", "concatenated raw rows per record so duplicate raw rows do not hide a match", rawbad[:5])


# ------------------------------------------------------------------ WF-1 clock times
CLOCK = re.compile(r"(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})")


def check_v_clock_times():
    """Every hh:mm-hh:mm in a schedule value: hh <= 24, mm <= 59, total <= 24:00. Count rows, usable, model-visible, records."""
    out, ex = {}, []
    for t in ("web_hours", "facts"):
        df = T(t)
        b = df[df.value_text.fillna("").map(lambda v: any(int(a) * 60 + int(b) > 1440 or int(b) > 59 or int(c) * 60 + int(d) > 1440 or int(d) > 59
                                                          for a, b, c, d in CLOCK.findall(v)))]
        u = b[b.status.isin(["ok", "flagged"]) & (b.polarity == "positive")]
        o = {"rows": len(b), "usable_any_attr": len(u)}
        if "attributable" in b:
            ua = u[u.attributable]
            o |= {"usable_attributable": len(ua), "model_visible_status_ok_attr": int(((b.status == "ok") & b.attributable).sum()),
                  "records_usable_attr": ua.unique_id.nunique(), "by_method": u.method.value_counts().to_dict()}
        out[t] = o
        ex += [f"{t} {r.fact_id} {r.value_text} <- {r.quote[:60]!r}" for r in u.sample(min(3, len(u)), random_state=11).itertuples()]
    for t in ("web_facility_details", "facility_details"):
        df = T(t)
        b = df[(df.n_usable > 0) & df.value_text.fillna("").map(lambda v: any(int(a) > 24 or int(b) > 59 or int(c) > 24 or int(d) > 59 for a, b, c, d in CLOCK.findall(v)))]
        out[t] = {"facility_values": len(b), "records": b.unique_id.nunique()}
    # model-visible e_web_hours_found records that rest only on invalid-clock rows
    wh = T("web_hours")
    m = wh[(wh.status == "ok") & wh.attributable]
    badrow = m.value_text.fillna("").map(lambda v: any(int(a) > 24 or int(c) > 24 or int(b) > 59 or int(d) > 59 for a, b, c, d in CLOCK.findall(v)))
    only = m.assign(b=badrow).groupby("unique_id").b.all()
    out["e_web_hours_found_records_only_invalid"] = int(only.sum())
    return res("v_clock_times", "warn" if out["web_hours"]["rows"] else "pass", out, "0", "own regex over value_text", ex)


def check_v_schedule_sanity():
    """Schedules that pass the plausibility rule but are odd: zero-length, open at or before 03:00 that is not 24h, closes after 23:00 for OPD."""
    wh = usable(T("web_hours"))
    o = wh[wh.fact_type == "opd_hours"]
    ents = o.value_text.fillna("").map(CLOCK.findall)
    zero = o[ents.map(lambda e: any(a == c and b == d for a, b, c, d in e))]
    early = o[ents.map(lambda e: any(0 < int(a) * 60 + int(b) <= 180 for a, b, c, d in e))]
    late = o[ents.map(lambda e: any(int(c) * 60 + int(d) > 23 * 60 + 30 and int(c) <= 24 for a, b, c, d in e))]
    unk = o[o.value_text.fillna("").str.contains(r"days\?")]
    wf = T("web_facility_details")
    wfo = wf[(wf.fact_type == "opd_hours") & (wf.n_usable > 0)]
    m = {"usable_attr_opd_rows": len(o), "zero_length_entry": len(zero), "opens_00:01-03:00": len(early), "closes_after_23:30": len(late),
         "rows_with_days?": len(unk), "facility_opd_values": len(wfo), "facility_opd_values_with_days?": int(wfo.value_text.fillna("").str.contains(r"days\?").sum())}
    ex = [f"{r.fact_id} {r.value_text} <- {r.quote[:60]!r}" for r in pd.concat([zero.head(2), early.head(2), late.head(1)]).itertuples()]
    return res("v_schedule_sanity", "warn" if len(zero) + len(early) else "pass", m, "0 zero-length or 01:00-03:00 openings", "usable attributable opd_hours", ex)


# ------------------------------------------------------------------ WF-2 facility value vs cited row
def _fv(fd, facts, web):
    f = facts.drop_duplicates("fact_id").set_index("fact_id")
    x = fd[fd.n_usable > 0].copy()
    c = f.reindex(x.best_fact_id)
    x["cv_t"] = c.value_text.values
    x["cv_n"] = c.value_num.values
    same_t = (x.value_text.fillna("<na>").astype(str) == x.cv_t.fillna("<na>").astype(str).values)
    same_n = (x.value_num.fillna(-9e9) == pd.Series(x.cv_n, index=x.index).fillna(-9e9))
    d = x[~(same_t & same_n)]
    # could the shown value have been cited? a usable row of the same key carrying the shown value
    u = facts[facts.status.isin(["ok", "flagged"]) & (facts.polarity == "positive")]
    if web:
        u = u[u.attributable]
    keyv = set(zip(u.unique_id, u.fact_type, u.attribute, u.value_text.fillna("<na>").astype(str), u.value_num.fillna(-9e9)))
    fixable = sum((a, b, c_, str(t) if pd.notna(t) else "<na>", n if pd.notna(n) else -9e9) in keyv
                  for a, b, c_, t, n in zip(d.unique_id, d.fact_type, d.attribute, d.value_text, d.value_num))
    # attributable check on the best row (web only)
    na = 0
    if web:
        att = f.attributable.reindex(x.best_fact_id)
        na = int((~att.fillna(False).astype(bool)).sum())
    return x, d, fixable, na


def check_v_facility_value():
    out, ex = {}, []
    for name, fd, facts, web in (("web", T("web_facility_details"), pd.concat([T("web_hours"), T("web_details")]), True),
                                 ("vf", T("facility_details"), T("facts"), False)):
        x, d, fixable, na = _fv(fd, facts, web)
        tl = d.value_text.fillna("").astype(str).str.lower() == pd.Series(d.cv_t, index=d.index).fillna("").astype(str).str.lower()
        case_only = int((tl & (d.value_text.fillna("").astype(str) != pd.Series(d.cv_t, index=d.index).fillna("").astype(str))).sum())
        num_only = int((d.value_text.fillna("").astype(str) == pd.Series(d.cv_t, index=d.index).fillna("").astype(str)).sum())
        out[name] = {"usable_facility_facts": len(x), "value_differs": len(d), "case_only_text_diff": case_only, "same_text_count_differs": num_only,
                     "share": round(len(d) / len(x), 4), "shown_value_has_own_usable_row": fixable,
                     "best_row_not_attributable": na, "n_distinct_values_gt1_among_differs": int((d.n_distinct_values > 1).sum()),
                     "top": d.groupby(["fact_type", "attribute"]).size().sort_values(ascending=False).head(5).to_dict()}
        out[name]["top"] = {f"{a}:{b}": int(v) for (a, b), v in out[name]["top"].items()}
        ex += [f"{name} {r.unique_id} {r.fact_type}:{r.attribute} shown={r.value_text if pd.notna(r.value_text) else r.value_num} cited={r.cv_t if pd.notna(r.cv_t) else r.cv_n} q={r.best_quote[:50]!r}"
               for r in d.sample(3, random_state=5).itertuples()]
    return res("v_facility_value", "warn", out, "0", "value_text/value_num of the facility row vs the row named by best_fact_id", ex)


# ------------------------------------------------------------------ WF-3 weak pairs, cell A
def check_v_weak_pairs():
    ss = T("web_service_summary")
    att = set(T("site_identity").query("attributable").unique_id)
    p = ss[ss.web_positive & ss.unique_id.isin(att)]
    weak = p[~p.web_positive_strong]
    w1 = weak[weak.n_pages_positive == 1]
    pm = p[p.service_id.isin(MODEL_SVC)]
    wm = pm[~pm.web_positive_strong]
    m = {"positive_pairs": len(p), "weak": len(weak), "weak_single_page": len(w1), "model_services_positive_pairs": len(pm), "model_services_weak": len(wm),
         "model_services_weak_single_page": int((wm.n_pages_positive == 1).sum()), "model_weak_by_service": wm.service_id.value_counts().to_dict()}
    return res("v_weak_pairs", "warn", m, "informational", "e_web_service only reads the 7 model services (build_features.py:34-35, 276-285)", [])


def _cells(s):
    ss = T("web_service_summary").set_index(["unique_id", "service_id"])
    k = list(zip(s.unique_id, s["item"]))
    x = ss.reindex(k)
    strong = x.web_positive_strong.values.astype(bool)
    pages_ = x.n_pages_positive.values
    item = (s.line_kind == "item").values
    return pd.Series(["A" if st and pg >= 2 else "B" if st and it else "C" if st else "D" if pg >= 2 else "E" for st, pg, it in zip(strong, pages_, item)], index=s.index)


def check_v_cell_A():
    from scipy.stats import fisher_exact
    sys.path.insert(0, AUD)
    from labels import LABELS  # the auditor's verdicts are the object under test
    s = pd.read_csv(f"{AUD}/out/sample.csv", keep_default_na=False)
    s = s[s.group == "svc"].copy()
    s["ok"] = s.n.map(lambda n: LABELS[n][0])
    s["cell"] = _cells(s)
    q = pd.read_csv(f"{ROOT}/kb/web_evidence/qa/out/sample_scored.csv", keep_default_na=False)
    q = q[q.stratum.str.startswith("svc")].copy()
    q["ok"] = q.correct.astype(str).str.lower().eq("true")
    q["cell"] = _cells(q)
    a = s.groupby("cell").ok.agg(["sum", "size"])
    b = q.groupby("cell").ok.agg(["sum", "size"])
    ka, na_ = int(a.loc["A", "sum"]), int(a.loc["A", "size"])
    kb, nb_ = int(b.loc["A", "sum"]), int(b.loc["A", "size"])
    p = fisher_exact([[ka, na_ - ka], [kb, nb_ - kb]])[1]
    m = {"auditor_by_cell": {c: f"{int(r['sum'])}/{int(r['size'])}" for c, r in a.iterrows()},
         "qa_by_cell_recomputed_now": {c: f"{int(r['sum'])}/{int(r['size'])}" for c, r in b.iterrows()},
         "cell_A_auditor": f"{ka}/{na_} {wilson(ka, na_)}", "cell_A_qa": f"{kb}/{nb_} {wilson(kb, nb_)}", "fisher_two_sided_p": round(p, 4),
         "pooled_A": f"{ka + kb}/{na_ + nb_} {wilson(ka + kb, na_ + nb_)}"}
    wrongA = [f"auditor item {r.n} {r.item}: {LABELS[r.n][2]}" for r in s[(s.cell == "A") & ~s.ok].itertuples()]
    return res("v_cell_A", "warn", m, "informational", "cells recomputed from web_service_summary (strength, n_pages_positive) and the best quote's line_kind", wrongA)


def check_v_sense_errors_population():
    """Population size of the service sense errors the auditor found by sampling (detox, stroke thrombolysis, eye trauma)."""
    s = T("web_services")
    p = s[s.positive & s.attributable]
    seg = p.segment.str.lower()
    rules = {
        "de_addiction_detox_without_addiction_word": (p.service_id == "de_addiction") & seg.str.contains(r"detox") & ~seg.str.contains(r"addict|alcohol|drug|de-?addiction|substance|rehab|nasha|tobacco|smok"),
        "stemi_thrombolysis_with_stroke_word": (p.service_id == "stemi_thrombolysis") & seg.str.contains(r"stroke|brain|cerebr|neuro") & ~seg.str.contains(r"heart|cardiac|stemi|myocard|coronary"),
        "trauma_care_eye_or_cataract": (p.service_id == "trauma_care") & seg.str.contains(r"traumatic cataract|ocular trauma|eye (?:trauma|injur)|trauma[^.;,]{0,25}\beyes?\b|orbital|maxillofacial trauma|dental trauma|psycholog|emotional trauma"),
        "cataract_surgery_knee_or_arthroscopy": (p.service_id == "cataract_surgery") & seg.str.contains(r"knee|arthroscop"),
    }
    m, ex = {}, []
    for k, mask in rules.items():
        r = p[mask]
        g = p.assign(b=mask).groupby(["unique_id", "service_id"]).b
        sub = g.all()
        m[k] = {"rows": len(r), "pairs_any": int(g.any().sum()), "pairs_only": int(sub.sum())}
        ex += [f"{k}: {x.unique_id} {x.quote[:70]!r}" for x in r.head(1).itertuples()]
    return res("v_sense_errors_population", "warn", m, "informational", "positive attributable web_services rows", ex)


# ------------------------------------------------------------------ WF-4 medium identity
def check_v_medium_identity():
    si = T("site_identity")
    med = si[(si.kind == "site") & (si.confidence == "medium")]
    att = si[si.attributable]
    only_med = att.groupby("unique_id").confidence.agg(lambda c: (c == "medium").all())
    noplace = med[~med.pin_found.astype(bool) & ~med.locality_found.astype(bool)]
    # facts riding on medium-only records
    om = set(only_med[only_med].index)
    ss = T("web_service_summary")
    wh = T("web_hours")
    m = {"medium_own_sites": len(med), "medium_any_kind": int((si.confidence == "medium").sum()), "medium_attributable": int((att.confidence == "medium").sum()),
         "records_only_medium": len(om), "medium_own_sites_no_pin_no_locality": len(noplace), "name_how_of_medium": med.name_how.value_counts().to_dict(),
         "positive_pairs_on_medium_only_records": int((ss.web_positive & ss.unique_id.isin(om)).sum()),
         "model_service_pairs_on_medium_only": int((ss.web_positive & ss.unique_id.isin(om) & ss.service_id.isin(MODEL_SVC)).sum()),
         "e_web_24x7_emergency_records_medium_only": int(wh[(wh.status == "ok") & wh.attributable & (wh.fact_type == "hours_24x7") & (wh.attribute == "emergency") & wh.unique_id.isin(om)].unique_id.nunique())}
    ex = [f"{r.unique_id} {r.target_id} name_how={r.name_how} q={str(r.name_quote)[:50]!r}" for r in noplace.sample(4, random_state=9).itertuples()]
    return res("v_medium_identity", "warn", m, "informational", "kind == 'site' is the README's 'own site'", ex)


# ------------------------------------------------------------------ WF-5 shared pages / templates, with duplicate-record groups
def check_v_shared_pages():
    s = T("web_services")
    p = s[s.positive & s.attributable]
    fg = pd.read_parquet(f"{ROOT}/derived/v1/facility_groups.parquet", columns=["unique_id", "dup_group_id"])
    grp = dict(zip(fg.unique_id, fg.dup_group_id.fillna(fg.unique_id)))
    recs = p.groupby("path").unique_id.agg(lambda u: set(u))
    ngrp = recs.map(lambda u: len({grp.get(x, x) for x in u}))
    nrec = recs.map(len)
    shared = p.path.map(nrec) >= 2
    shared_distinct = p.path.map(ngrp) >= 2
    pairs = p.assign(a=shared, b=shared_distinct).groupby(["unique_id", "service_id"])
    sites = p.groupby("quote").target_id.nunique()
    tmpl = p.quote.map(sites) >= 10
    pt = p.assign(t=tmpl).groupby(["unique_id", "service_id"]).t.all()
    m = {"positive_pairs": pairs.ngroups, "pairs_only_on_pages_shared_by_2plus_records": int(pairs.a.all().sum()),
         "same_but_2plus_distinct_dup_groups": int(pairs.b.all().sum()), "pairs_only_on_quote_positive_on_10plus_sites": int(pt.sum()),
         "template_only_pairs_in_model_services": int(pt[pt].reset_index().service_id.isin(MODEL_SVC).sum())}
    return res("v_shared_pages", "warn", m, "informational", "duplicate records (derived/v1/facility_groups.dup_group_id) sharing a page is correct, not an error", [])


# ------------------------------------------------------------------ WF-6 bio cues, doctor profile URLs
BIO2 = re.compile(r"\bdr\.?\s+[a-z]+\s+(?:is|has|was|completed|did|worked|holds)\b|\b(?:his|her)\s+(?:mbbs|md|ms|training|career|fellowship|residency)|years of (?:clinical )?experience|\bm\.?b\.?b\.?s\b|\bfellowship\b", re.I)
DOC_URL = re.compile(r"/(?:doctors?|dr-|team|our-team|consultants?|faculty|profile|specialists?)[/-]", re.I)


def check_v_bio_and_profile_pages():
    s = T("web_services")
    p = s[s.positive & s.attributable]
    bio = p.segment.str.contains(BIO2)
    g = p.assign(b=bio).groupby(["unique_id", "service_id"]).b
    d = usable(T("web_details"))
    dp = d[d.final_url.fillna("").str.contains(DOC_URL)]
    nabh = d[(d.fact_type == "accreditation") & (d.attribute == "NABH")]
    nabh_doc = nabh[nabh.final_url.fillna("").str.contains(DOC_URL)]
    rec_nabh = nabh.assign(b=nabh.final_url.fillna("").str.contains(DOC_URL)).groupby("unique_id").b.all()
    m = {"positive_service_rows_bio_cue_own_regex": int(bio.sum()), "pairs_any": int(g.any().sum()), "pairs_only": int(g.all().sum()),
         "usable_detail_rows_on_doctor_profile_urls": len(dp), "by_type": dp.fact_type.value_counts().to_dict(),
         "nabh_usable_rows_on_profile_urls": len(nabh_doc), "nabh_records_only_from_profile_urls": int(rec_nabh.sum())}
    ex = [f"{r.unique_id} {r.fact_type}:{r.attribute} {r.final_url} {r.quote[:50]!r}" for r in dp.sample(min(4, len(dp)), random_state=4).itertuples()]
    return res("v_bio_and_profile_pages", "warn", m, "informational", f"own bio regex; doctor-profile URL regex {DOC_URL.pattern}", ex)


# ------------------------------------------------------------------ WF-7 phone-cue emergency
def check_v_emergency_phone():
    wh = T("web_hours")
    em = wh[(wh.status == "ok") & wh.attributable & (wh.fact_type == "hours_24x7") & (wh.attribute == "emergency")]
    narrow = re.compile(r"\b(?:call|helpline|hotline|whatsapp|booking|book an?|support|guidance|tele-?consult|enquir|customer care|toll.?free)\b|\[phone\]", re.I)
    clinical = re.compile(r"\b(?:department|ward|casualty|unit|services?|care|centre|center|room|trauma|doctor|icu)\b", re.I)
    ph = em.source_text.str.contains(narrow) & ~em.source_text.str.contains(clinical)
    only = em.assign(p=ph).groupby("unique_id").p.all()
    m = {"model_emergency_rows": len(em), "records": em.unique_id.nunique(), "rows_phone_cue_no_clinical_word": int(ph.sum()), "records_only_such_rows": int(only.sum())}
    ex = [f"{r.unique_id} {r.source_text[:80]!r}" for r in em[ph].sample(min(5, int(ph.sum())), random_state=3).itertuples()]
    return res("v_emergency_phone", "warn" if only.sum() else "pass", m, "0", "status ok + attributable (exactly the model filter, build_features.py:287-290)", ex)


# ------------------------------------------------------------------ WF-8 headcount bands
def check_v_headcount_bands():
    out, ex = {}, []
    band = re.compile(r"\b\d{1,5}\s*(?:to|-|–)\s*\d{1,5}\s+(?:employees|staff|people)\b|\b\d{1,5}\+?\s+employees\b", re.I)
    for t in ("facts", "web_details"):
        df = T(t)
        st = df[(df.fact_type == "staffing") & df.status.isin(["ok", "flagged"]) & (df.polarity == "positive")]
        if "attributable" in st:
            st = st[st.attributable]
        b = st[st.quote.str.contains(band)]
        out[t] = {"usable_staffing": len(st), "headcount_band_quotes": len(b), "by_attr": b.attribute.value_counts().to_dict(), "ok_only": int((b.status == "ok").sum())}
        ex += [f"{t} {r.fact_id} {r.attribute}={r.value_num} <- {r.quote[:60]!r}" for r in b.head(2).itertuples()]
    return res("v_headcount_bands", "warn", out, "0", "quote names an employee band or 'N employees'", ex)


# ------------------------------------------------------------------ WF-9 phones in quotes
PH = re.compile(r"(?<![\d/.-])(?:\+91[\s-]?)?(?:0\d{2,4}[\s-]{0,3}\d{6,8}|[6-9]\d{9}|[6-9]\d{4}[\s-]\d{5})(?![\d/.-])")


def check_v_phones():
    qs = pd.concat([T(t)[["quote"]].assign(t=t) for t in ("web_services", "web_hours", "web_details")]).drop_duplicates()
    hit = qs[qs.quote.str.contains(PH)]
    mob = hit[hit.quote.str.contains(r"(?<!\d)(?:\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")]
    idq = pd.concat([T("site_identity")[c].dropna() for c in ("name_quote", "pin_quote", "locality_quote")]).drop_duplicates()
    idhit = idq[idq.str.contains(PH)]
    m = {"distinct_fact_quotes": len(qs), "with_phone": len(hit), "by_table": hit.t.value_counts().to_dict(), "of_which_mobile_pattern": len(mob),
         "identity_quotes_with_phone": len(idhit)}
    ex = [repr(q[:80]) for q in mob.quote.head(3)] + [repr(q[:80]) for q in idhit.head(2)]
    return res("v_phones", "warn" if len(hit) + len(idhit) else "pass", m, "0", f"own regex {PH.pattern}", ex)


# ------------------------------------------------------------------ WF-10 provenance
def check_v_provenance():
    pg = pages().dropna(subset=["path"])
    g = pg.groupby("path").agg(n=("target_id", "size"), nh=("text_hash", "nunique"), nt=("target_id", "nunique"))
    shared = g[g.n >= 2]
    rows_diff_t = rows_diff_f = 0
    for t in ("web_services", "web_hours", "web_details"):
        df = T(t)
        meta = {p: (doc(p).get("target_id"), doc(p).get("fetched_at")) for p in set(df.path)}
        rows_diff_t += sum(meta[p][0] != x for p, x in zip(df.path, df.target_id))
        rows_diff_f += sum(meta[p][1] != x for p, x in zip(df.path, df.fetched_at))
    m = {"page_rows_with_path": len(pg), "files_shared": len(shared), "shared_files_with_2plus_text_hashes": int((shared.nh > 1).sum()),
         "shared_files_with_2plus_targets": int((shared.nt > 1).sum()), "fact_rows_target_differs": rows_diff_t, "fact_rows_fetched_at_differs": rows_diff_f}
    return res("v_provenance", "warn" if rows_diff_t else "pass", m, "0 text-hash conflicts", "pages.parquet grouped by path", [])


# ------------------------------------------------------------------ WF-11 coming soon (precision of the auditor's cue)
def check_v_coming_soon():
    s = T("web_services")
    p = s[s.positive & s.attributable]
    strict = re.compile(r"coming soon|opening soon|launching soon|will be (?:operational|started|launched|commissioned|available)|under construction", re.I)
    loose = re.compile(r"upcoming|shortly", re.I)
    a = p.segment.str.contains(strict)
    b = p.segment.str.contains(loose) & ~a
    g = p.assign(a=a).groupby(["unique_id", "service_id"]).a
    m = {"strict_rows": int(a.sum()), "strict_pairs_only": int(g.all().sum()), "loose_only_rows_(upcoming|shortly)": int(b.sum())}
    ex = [f"loose: {x.unique_id} {x.segment[:80]!r}" for x in p[b].head(3).itertuples()]
    return res("v_coming_soon", "warn" if g.all().sum() else "pass", m, "0", "auditor's SOON regex also matches 'upcoming' and 'shortly'", ex)


# ------------------------------------------------------------------ WF-12 NABH values
def check_v_nabh_values():
    wf = T("web_facility_details")
    n = wf[(wf.fact_type == "accreditation") & (wf.attribute == "NABH") & (wf.n_usable > 0)]
    d = usable(pd.concat([T("web_details")]))
    nr = d[(d.fact_type == "accreditation") & (d.attribute == "NABH")]
    full = set(nr[nr.value_text == "accredited"].unique_id)
    m = {"records": len(n), "facility_value_counts": n.value_text.value_counts(dropna=False).to_dict(),
         "records_no_usable_row_valued_accredited": len(set(n.unique_id) - full),
         "row_value_counts": nr.value_text.value_counts(dropna=False).to_dict()}
    ex = [f"{r.unique_id} {r.value_text} {r.best_quote[:60]!r}" for r in n[~n.unique_id.isin(full)].head(4).itertuples()]
    return res("v_nabh_values", "warn", m, "0", "e_web_nabh_claim filters n_usable > 0 only (build_features.py:292)", ex)


# ------------------------------------------------------------------ missed-issue hunts
def check_v_row_vs_site_identity():
    """attributable fact rows must belong to an attributable (target, record) site_identity row; off-site pages must name the facility."""
    si = T("site_identity").set_index(["target_id", "unique_id"])
    out, ex = {}, []
    for t in ("web_services", "web_hours", "web_details"):
        df = T(t)
        a = df[df.attributable]
        k = si.reindex(list(zip(a.target_id, a.unique_id)))
        bad = a[~k.attributable.fillna(False).astype(bool).values]
        conf_mis = a[(k.confidence.values != a.identity_conf.values)]
        out[t] = {"attributable": len(a), "site_identity_missing_or_not_attributable": len(bad), "identity_conf_differs": len(conf_mis)}
        ex += [f"{t} {r.unique_id} {r.target_id} {r.identity_conf}" for r in bad.head(2).itertuples()]
    nb = sum(v["site_identity_missing_or_not_attributable"] for v in out.values())
    return res("v_row_vs_site_identity", "pass" if nb == 0 else "fail", out, "0", "join on (target_id, unique_id)", ex)


def check_v_facility_tables_scope():
    """web_facility_details built only from attributable rows; n_usable recounts."""
    facts = pd.concat([T("web_hours"), T("web_details")])
    u = usable(facts)
    rc = u.groupby(["unique_id", "fact_type", "attribute"]).size()
    wf = T("web_facility_details").set_index(["unique_id", "fact_type", "attribute"])
    x = wf[wf.n_usable > 0]
    r = rc.reindex(x.index).fillna(0)
    mism = x[r.values != x.n_usable.values]
    extra = rc.index.difference(wf.index)
    allfacts_att = facts.set_index("fact_id").attributable
    best_na = x[~allfacts_att.reindex(x.best_fact_id).fillna(False).astype(bool).values]
    m = {"usable_facility_rows": len(x), "n_usable_recount_differs": len(mism), "usable_keys_missing_from_table": len(extra), "best_fact_not_attributable": len(best_na)}
    ex = [f"{i} n_usable={r_.n_usable} recount={rc.get(i, 0)}" for i, r_ in mism.head(3).iterrows()]
    return res("v_facility_tables_scope", "pass" if len(mism) + len(extra) + len(best_na) == 0 else "warn", m, "0", "usable = attributable, ok/flagged, positive", ex)


def check_v_record_ids():
    fl = pd.read_parquet(f"{ROOT}/derived/v1/facility_location.parquet", columns=["unique_id"])
    raw = set(pd.read_parquet(f"{ROOT}/data/raw/facilities.parquet", columns=["unique_id"]).unique_id)
    known = set(fl.unique_id)
    out = {}
    for t in ("web_services", "web_hours", "web_details", "site_identity", "facts", "web_facility_details", "facility_details"):
        u = set(T(t).unique_id)
        out[t] = {"records": len(u), "not_in_raw": len(u - raw), "not_in_derived_v1_facility_location": len(u - known)}
    nb = sum(v["not_in_raw"] for v in out.values())
    return res("v_record_ids", "pass" if nb == 0 else "fail", out, "0 unknown ids", "", [])


MOJI = re.compile(r"Ã.|â€|Â |�|ï¿½")


def check_v_text_encoding():
    out, ex = {}, []
    for t in ("web_services", "web_hours", "web_details", "facts"):
        q = T(t).quote.drop_duplicates()
        b = q[q.str.contains(MOJI)]
        out[t] = {"distinct_quotes": len(q), "mojibake": len(b), "placeholder_[phone]": int(q.str.contains(r"\[phone\]").sum())}
        ex += [repr(s[:70]) for s in b.head(2)]
    nb = sum(v["mojibake"] for v in out.values())
    return res("v_text_encoding", "pass" if nb == 0 else "warn", out, "0 mojibake", "UTF-8 decoded as cp1252 markers and U+FFFD", ex)


def check_v_value_plausibility():
    """Counts that a reader would not believe: beds and doctors vs facility type and size."""
    raw = pd.read_parquet(f"{ROOT}/data/raw/facilities.parquet", columns=["unique_id", "facilityTypeId"]).drop_duplicates("unique_id").set_index("unique_id").facilityTypeId
    out, ex = {}, []
    for name, fd in (("web", T("web_facility_details")), ("vf", T("facility_details"))):
        x = fd[fd.n_usable > 0]
        beds = x[(x.fact_type == "total_beds") | ((x.fact_type == "beds") & (x.attribute == "total"))]
        b = x[x.attribute.astype(str).str.contains("total") & x.fact_type.astype(str).str.contains("bed")]
        typ = b.unique_id.map(raw)
        big_clinic = b[(typ.isin(["clinic", "dentist", "doctor"])) & (b.value_num > 100)]
        huge = b[b.value_num > 3000]
        unit = x[(x.fact_type == "unit_beds")]
        tot = b.set_index("unique_id").value_num
        over = unit[unit.value_num > unit.unique_id.map(tot)]
        amb = x[(x.fact_type == "ambulance") & (x.value_num == 24)]
        out[name] = {"total_bed_values": len(b), "clinic_or_dentist_over_100_beds": len(big_clinic), "over_3000_beds": len(huge),
                     "unit_beds_over_total": len(over), "ambulance_count_24": len(amb), "fact_types": sorted(x.fact_type.unique().tolist())}
        ex += [f"{name} {r.unique_id} {r.attribute}={r.value_num} {r.best_quote[:50]!r}" for r in pd.concat([big_clinic.head(1), huge.head(1), over.head(1), amb.head(1)]).itertuples()]
    return res("v_value_plausibility", "warn", out, "0", "facility-level usable values", ex)


def check_v_llm_hours_rule():
    """LLM-kept web hour rows: every clock hour in the value appears as a number in the quote."""
    wh = usable(T("web_hours"))
    l = wh[wh["flags"].fillna("").str.contains("llm_extracted") | (wh.method == "llm")]

    def ok(v, q):
        nums = {int(x) for x in re.findall(r"\d{1,2}", q)}
        for a, b, c, d in CLOCK.findall(v or ""):
            for h, mm in ((int(a), int(b)), (int(c), int(d))):
                if not ({h, h % 12, 12 if h % 12 == 0 else h % 12, h - 12 if h > 12 else h} & nums):
                    return False
        return True
    bad = l[[not ok(v, q) for v, q in zip(l.value_text, l.quote)]]
    m = {"llm_usable_rows": len(l), "hour_not_in_quote": len(bad)}
    ex = [f"{r.fact_id} {r.value_text} <- {r.quote[:60]!r}" for r in bad.head(5).itertuples()]
    return res("v_llm_hours_rule", "pass" if len(bad) == 0 else "warn", m, "0", "loose numeric check (12h or 24h form)", ex)


def check_v_clock_causes():
    """Root causes of the invalid clock rows: the pm bug in patterns.py:152 is only part of them."""
    wh = T("web_hours")
    b = wh[wh.value_text.fillna("").map(lambda v: any(int(a) > 24 or int(c) > 24 or int(bb) > 59 or int(d) > 59 for a, bb, c, d in CLOCK.findall(v)))]

    def cls(q):
        if re.search(r"\d{1,2}[./]\d{1,2}[./]\d{2,4}", q):
            return "date_range_read_as_hours"
        if re.search(r"\b(1[3-9]|2[0-3])[:.]\d{2}\s*p\.?m", q, re.I):
            return "24h_time_plus_pm_(patterns.py:152)"
        if re.search(r"(?<![\d:.])\d{1,2}-[0-5]\d\s*(?:am|pm|a\.m|p\.m)", q, re.I):
            return "dash_as_minute_separator"
        if re.search(r"\b\d{3,4}\s*(?:am|pm)", q, re.I):
            return "hhmm_without_separator"
        return "other (5::30, 90:00 AM ...)"
    c = b.quote.map(cls)
    o = wh[(wh.fact_type == "opd_hours")]
    dash = o[o.status.isin(["ok", "flagged"]) & o.attributable & o.quote.str.contains(r"(?<![\d:.])\d{1,2}-[0-5]\d\s*(?:am|pm|a\.m|p\.m)", case=False)]
    m = {"invalid_rows": len(b), "by_cause": c.value_counts().to_dict(), "usable_attr_rows_with_dash_minute_any_value": len(dash),
         "of_which_value_looks_valid": int((~dash.index.isin(b.index)).sum())}
    ex = [f"{r.fact_id} {r.value_text} <- {r.quote[:50]!r}" for r in dash[~dash.index.isin(b.index)].head(3).itertuples()]
    return res("v_clock_causes", "warn", m, "0", "dash-minute rows ('09-00pm' -> 09:00-12:00) are wrong but pass any clock-range test", ex)


FOREIGN = re.compile(r"\b(?:USA|United States|Nashua|Nepal|Kathmandu|Sri Lanka|Malaysia|United Kingdom)\b")


def check_v_foreign_site_titles():
    """Attributable own sites whose page titles name a foreign country or city (screen; read by hand)."""
    si = T("site_identity")
    att = si[si.attributable]
    pg = pages().dropna(subset=["path"])
    t = pg[pg.target_id.isin(set(att.target_id)) & pg.title.fillna("").str.contains(FOREIGN)]
    x = att[att.target_id.isin(set(t.target_id))]
    m = {"attributable_rows_flagged": len(x), "by_confidence": x.confidence.value_counts().to_dict(), "targets": sorted(set(x.target_id))}
    return res("v_foreign_site_titles", "warn" if len(x) else "pass", m, "0 (screen)", "hand read: stjosephhospital.com (Nashua NH), greencityhospital.org (Kathmandu), "
               "royalhospitals.com (Sri Lanka), columbiaasia.com/malaysia, myfamilydentalcare.com (USA), ivf.net (UK portal, high)", [])


def check_v_portal_ivf_net():
    """ivf.net, a UK news and jobs portal, is the 'own site' (high) of Santasa IVF Mysore; its usable facts."""
    u = usable(pd.concat([T("web_hours"), T("web_details")]))
    x = u[u.target_id == "ivf.net"]
    s = T("web_services")
    sv = s[(s.target_id == "ivf.net") & s.positive & s.attributable]
    m = {"usable_fact_rows": len(x), "by_attr": (x.fact_type + ":" + x.attribute).value_counts().to_dict(), "positive_service_rows": len(sv)}
    ex = [f"{r.unique_id} {r.fact_type}:{r.attribute}={r.value_num if pd.notna(r.value_num) else r.value_text} <- {r.quote[:70]!r}" for r in x.drop_duplicates("quote").itertuples()]
    return res("v_portal_ivf_net", "warn" if len(x) + len(sv) else "pass", m, "0", "site_identity high via one training-programme page carrying PIN 570004", ex)


def check_v_databricks_copy():
    """The Unity Catalog copies (databricks/tables.yaml) have the local row counts and carry the WF-1 rows. One SELECT."""
    import subprocess
    tabs = {"web_site_identity": "site_identity", "web_services": "web_services", "web_hours": "web_hours", "web_facts": "web_details",
            "web_facility_details": "web_facility_details", "facility_details": "facility_details", "vf_facts": "facts", "web_service_summary": "web_service_summary"}
    q = " UNION ALL ".join(f"SELECT '{k}' t, count(*) n FROM workspace.referral_saathi.{k}" for k in tabs)
    q += " UNION ALL SELECT 'web_hours_bad_clock', count(*) FROM workspace.referral_saathi.web_hours WHERE value_text RLIKE '(^|[^0-9])(2[5-9]|[3-9][0-9]):[0-9]{2}'"
    for _ in range(3):
        try:
            r = subprocess.run([f"{ROOT}/sql.sh", q], capture_output=True, text=True, timeout=120)
            if r.returncode == 0:
                break
        except subprocess.TimeoutExpired:
            continue
    else:
        return res("v_databricks_copy", "warn", "not run", "", "sql.sh failed 3 times", [])
    got = dict(line.split("\t") for line in r.stdout.strip().splitlines()[1:])
    diff = {k: (int(got.get(k, -1)), len(T(v))) for k, v in tabs.items() if int(got.get(k, -1)) != len(T(v))}
    m = {"remote": got, "count_mismatches": diff}
    return res("v_databricks_copy", "pass" if not diff else "fail", m, "0 mismatches", "row counts only, not content", [])


ALL = [v for k, v in sorted(globals().items()) if k.startswith("check_") and callable(v)]

if __name__ == "__main__":
    pick = set(sys.argv[1:])
    out = []
    for fn in ALL:
        if pick and fn.__name__ not in pick:
            continue
        try:
            r = fn()
        except Exception as e:  # reported, never silent
            import traceback
            r = res(fn.__name__[6:], "fail", "error", "", f"{type(e).__name__}: {e} {traceback.format_exc()[-400:]}", [])
        out.append(r)
        print(json.dumps(r, default=str, ensure_ascii=False)[:2500], flush=True)
    os.makedirs(OUT, exist_ok=True)
    json.dump(out, open(os.path.join(OUT, "checks.json" if not pick else "checks_partial.json"), "w"), indent=1, default=str)
