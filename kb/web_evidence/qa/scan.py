"""Population-wide checks behind QA.md, over every row of kb/web_evidence/out (read-only):

1. quotes: every fact and identity quote is re-checked, independently of build_web_evidence.verify_quotes, against the stored
   gz field it names; facility-level best quotes and values are checked against the fact row they cite; quote shape is counted.
2. error patterns: how many attributable positive service rows and (record, service) pairs each pattern found in the hand
   sample touches, and how many hour and detail facility facts.
3. fixes: for each candidate rule, the positive pairs or facility facts it would drop in the population, and in the scored
   sample the wrong items it removes and the correct items it loses.
Writes qa/out/scan.json. Run: /Users/karthikvattem/projects/datathon/.venv/bin/python scan.py   (about 2 minutes)
"""
from __future__ import annotations

import gzip
import warnings
import json
import os
import re
import sys
from collections import defaultdict

import pandas as pd

ROOT = "/Users/karthikvattem/projects/datathon"
OUT = f"{ROOT}/kb/web_evidence/out"
QA_OUT = f"{ROOT}/kb/web_evidence/qa/out"
sys.path.insert(0, f"{ROOT}/kb/web_evidence")
from compare_dataset import wilson  # noqa: E402

warnings.filterwarnings("ignore", message="This pattern is interpreted")

# Candidate service-row filters, read on the whole stored line (`segment`), not the clause. Each names the error pattern it targets.
SVC_RULES: dict[str, re.Pattern] = {
    "doctor_bio": re.compile(r"\b(he|she) (has|had|was|is|completed|did|trained|worked|presented|holds)\b|\bpresented at\b|\bCME\b|\bfounding member\b|"
                             r"\bex-?consultant\b|\bformer(ly)? (consultant|professor|head)\b|\byears of (clinical )?experience\b|\bfellowship (in|at|from)\b|"
                             r"\b(MBBS|DNB|FRCS|MRCP|M\.?Ch|D\.?M\.?)\b.{0,40}\b(from|at)\b", re.I),
    "educational": re.compile(r"\brefers to\b|\bis (a|an) (type|form|condition|disease|disorder|procedure|test|branch|group)\b|\bmay (include|cause|affect|lead)\b|"
                              r"\bcan (be caused|cause|lead to)\b|\bcaused by\b|\bsymptoms? (of|include)\b|\bpatients (may )?need\b|\bindividuals\b|\bis used to\b|"
                              r"\bassociated with\b|\bit is (often|usually|commonly) (recommended|used)\b|\bresponse to\b|\bcan help\b", re.I),
    "coming_soon": re.compile(r"coming soon|will be (operational|started|launched|available|commissioned|set up)|\bupcoming\b|launching soon|"
                              r"to be (started|launched|commissioned)|under construction|\bproposed\b", re.I),
    "testimonial": re.compile(r"\b(thank(s| you)?|grateful|highly recommend|my (mother|father|mom|dad|wife|husband|son|daughter|baby|child)|"
                              r"i (was|had|visited|am|got)|we (were|had|visited))\b", re.I),
}
TRAUMA_SENSE = re.compile(r"emotion|anxiety|grief|psycholog|hypno|traumatic (event|circumstance|experience|memor)|\beye\b|ocular|ophthalm", re.I)
EVENT_URL = re.compile(r"/(events?|event-item|view-articles?|category|tags?|press(-release)?s?|media(-coverage)?|newsletter|gallery)(/|$|\.)", re.I)
HELPLINE = re.compile(r"\bcall (us|now|on|at)\b|appointment|\bbook|visiting|visitors|parents|helpline|whatsapp|\bchat\b|enquir|\bphone\b|support (line|desk|team)|customer care", re.I)
UNIT_24 = re.compile(r"\b(ICU|ICCU|HDU|NICU|PICU|CCU|pharmacy|chemist|lab|laborator|ambulance|dialysis|blood|radiolog|imaging|x-?ray|CT|MRI)\b", re.I)
UNIT_BEDS = re.compile(r"\b(ICU|ICCU|AMCU|HDU|NICU|PICU|CCU|SICU|MICU|dialysis|emergency|casualty|ward|unit|cabin|day ?care)\b", re.I)
GROUP = re.compile(r"\bgroup\b|\bacross\b|\bbranches\b|\bcent(re|er)s\b|\blocations\b|\bnetwork\b|\bhospitals\b|\bfacilities in\b|\bunits\b", re.I)


def norm(t: str) -> str:
    t = t.lower().replace("&", " and ")
    t = re.sub(r"\b(sree|shri|shree|sri|shree)\b", "sri", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def load_doc(path: str, cache: dict) -> dict:
    if path not in cache:
        cache[path] = json.load(gzip.open(os.path.join(ROOT, path)))
    return cache[path]


def check_quotes(tabs: dict[str, pd.DataFrame], pi: pd.DataFrame) -> dict:
    """Independent re-check: every (path, field, quote) must be a substring of that stored field."""
    need: dict[str, set] = defaultdict(set)
    for t in tabs.values():
        for p, f, q in zip(t.path, t.field, t.quote):
            need[p].add((f, q))
    for qcol, fcol in (("name_quote", "name_field"), ("pin_quote", "pin_field"), ("loc_quote", "loc_field")):
        x = pi[pi[qcol].notna()]
        for p, f, q in zip(x.path, x[fcol], x[qcol]):
            need[p].add((f, q))
    bad, n = [], 0
    for p, items in need.items():
        d = json.load(gzip.open(os.path.join(ROOT, p)))
        for f, q in items:
            n += 1
            if not (isinstance(q, str) and q and q in (d.get(f) or "")):
                bad.append((p, f, str(q)[:80]))
    return {"triples_checked": n, "files": len(need), "not_substring": len(bad), "examples": bad[:5]}


def quote_shape(svc: pd.DataFrame, facts: pd.DataFrame) -> dict:
    q = pd.concat([svc.quote, facts.quote])
    words = q.str.split().str.len()
    seg_cut = (svc.quote != svc.segment.str.strip()).mean()
    return {"n_quotes": len(q), "with_newline": round(q.str.contains("\n").mean(), 3), "with_redaction_token": round(q.str.contains(r"\[(phone|email)\]").mean(), 3),
            "three_words_or_fewer": round((words <= 3).mean(), 3), "service_quote_is_window_of_longer_line": round(float(seg_cut), 3),
            "ellipsis_in_quote": round(q.str.contains(r"\.\.\.|…").mean(), 3)}


def facility_value_check(fd: pd.DataFrame, facts: pd.DataFrame) -> dict:
    f = facts.drop_duplicates("fact_id").set_index("fact_id")
    x = fd[fd.n_usable > 0].join(f[["quote", "value_text", "value_num"]].rename(columns=lambda c: "best_" + c if c != "quote" else "fact_quote"), on="best_fact_id")
    quote_ok = (x.best_quote == x.fact_quote)
    same_txt = (x.value_text.fillna("") == x.best_value_text.fillna(""))
    same_num = (x.value_num.isna() & x.best_value_num.isna()) | (x.value_num == x.best_value_num)
    mism = ~(same_txt & same_num)
    by = x[mism].groupby("fact_type").size().to_dict()
    days_unknown = x.value_text.fillna("").str.contains(r"days\?")
    return {"facility_facts_usable": len(x), "best_quote_equals_fact_quote": int(quote_ok.sum()),
            "value_differs_from_best_fact_row": int(mism.sum()), "value_differs_by_fact_type": by,
            "opd_value_with_unknown_days": int((days_unknown & (x.fact_type == "opd_hours")).sum()), "opd_facts": int((x.fact_type == "opd_hours").sum()),
            "examples": x[mism][["fact_type", "attribute", "value_text", "value_num", "best_value_text", "best_value_num", "best_quote"]].head(6).to_dict("records")}


def service_patterns(svc: pd.DataFrame, sample: pd.DataFrame) -> dict:
    pos = svc[svc.attributable & svc.positive & (svc.scope != "chain_home")].copy()
    pairs = pos.groupby(["unique_id", "service_id"]).size().rename("n_rows")
    hits = {k: pos.segment.str.contains(rx) for k, rx in SVC_RULES.items()}
    hits["trauma_sense"] = pos.service_id.isin(["trauma_care", "orthopaedic_trauma_surgery", "emergency_24x7"]) & pos.segment.str.contains(TRAUMA_SENSE)
    hits["event_or_article_url"] = pos.final_url.str.contains(EVENT_URL)
    tmpl = pos[pos.line_kind == "item"].groupby(["service_id", "quote"]).target_id.nunique()
    shared = set(tmpl[tmpl >= 10].index)
    hits["template_item_10plus_sites"] = pd.Series([(s, q) in shared for s, q in zip(pos.service_id, pos.quote)], index=pos.index)
    hits["chrome_text_only"] = pos.field == "chrome_text"
    sample_svc = sample[sample.group == "svc"]
    out = {"positive_rows": len(pos), "positive_pairs": len(pairs), "rules": {}}
    all_hit = pd.Series(False, index=pos.index)
    for k, h in hits.items():
        if k not in ("chrome_text_only", "template_item_10plus_sites"):  # both lose correct items and remove no wrong ones in the sample
            all_hit |= h
        out["rules"][k] = rule_effect(pos, h, pairs, sample_svc)
    out["rules"]["ALL_TEXT_RULES_COMBINED"] = rule_effect(pos, all_hit, pairs, sample_svc)
    return out


def rule_effect(pos: pd.DataFrame, hit: pd.Series, pairs: pd.Series, sample_svc: pd.DataFrame) -> dict:
    survive = pos[~hit].groupby(["unique_id", "service_id"]).size()
    dropped = set(pairs.index) - set(survive.index)
    in_s = [(u, i) in dropped for u, i in zip(sample_svc.unique_id, sample_svc["item"])]
    s = sample_svc[in_s]
    return {"rows_hit": int(hit.sum()), "pairs_dropped": len(dropped), "share_pairs_dropped": round(len(dropped) / len(pairs), 3),
            "sample_wrong_removed": int((~s.correct).sum()), "sample_right_lost": int(s.correct.sum()), "sample_removed_n": [int(x) for x in s.n]}


def fact_patterns(fd: pd.DataFrame, sample: pd.DataFrame) -> dict:
    x = fd[fd.n_usable > 0]
    q = x.best_quote.fillna("")
    sx = sample[sample.group.isin(["hrs", "det"])]
    rules = {
        "hours_24x7_facility_with_helpline_or_visiting_cue": (x.fact_type == "hours_24x7") & (x.attribute.isin(["facility", "emergency"])) & q.str.contains(HELPLINE),
        "hours_24x7_facility_quote_names_a_unit": (x.fact_type == "hours_24x7") & (x.attribute == "facility") & q.str.contains(UNIT_24),
        "total_beds_quote_names_a_unit": (x.fact_type == "unit_beds") & (x.attribute == "total") & q.str.contains(UNIT_BEDS),
        "beds_or_accreditation_quote_with_group_cue": x.fact_type.isin(["unit_beds", "accreditation"]) & q.str.contains(GROUP),
        "ambulance_count_from_24_hours": (x.fact_type == "ambulance") & (x.value_num == 24),
        "only_flagged_rows_no_ok_row": (x.n_ok == 0) & (x.n_flagged > 0),
    }
    out = {"facility_facts_usable": len(x), "rules": {}}
    for k, h in rules.items():
        keys = set(zip(x[h].unique_id, x[h].fact_type + ":" + x[h].attribute))
        s = sx[[(u, i) in keys for u, i in zip(sx.unique_id, sx["item"])]]
        out["rules"][k] = {"facts_hit": int(h.sum()), "of_type": int(x.fact_type.isin(x[h].fact_type.unique()).sum()),
                           "sample_wrong_removed": int((~s.correct).sum()), "sample_right_lost": int(s.correct.sum()), "sample_removed_n": [int(v) for v in s.n]}
    det = pd.read_parquet(f"{OUT}/web_details.parquet", columns=["unique_id", "fact_type", "attribute", "match", "quote", "status", "attributable", "polarity"])
    pi_ = det[(det.fact_type == "empanelment") & (det.attribute == "private_insurance") & det.attributable & (det.status != "excluded") & (det.polarity == "positive")]
    par = pi_[pi_.match.str.lower() == "paramount"]
    adj = par.quote.str.contains(r"paramount (importance|significance|concern|priority)|of paramount|is paramount|are paramount", case=False)
    out["paramount_rows"] = {"rows": len(par), "rows_adjective_use": int(adj.sum()), "records": par.unique_id.nunique(),
                             "records_only_adjective_use": int(par[adj].unique_id.nunique() - par[~adj & par.unique_id.isin(par[adj].unique_id)].unique_id.nunique())}
    out["private_insurance_match_terms_top"] = pi_.match.str.lower().value_counts().head(15).to_dict()
    flagged = pd.concat([pd.read_parquet(f"{OUT}/{t}.parquet", columns=["flags", "status", "attributable", "polarity"]) for t in ("web_hours", "web_details")])
    fl = flagged[(flagged.status == "flagged") & flagged.attributable & (flagged.polarity == "positive")]
    out["flagged_usable_rows"] = len(fl)
    out["flag_terms_top"] = fl["flags"].str.split("|").explode().value_counts().head(10).to_dict()
    return out


def page_texts(r, pages: pd.DataFrame, cache: dict) -> tuple[str, str]:
    """(normalised title+text+chrome, normalised titles) of a target's stored pages for one record."""
    pg = pages[(pages.target_id == r.target_id) & (pages.unique_ids == r.unique_id)]
    docs = [load_doc(p, cache) for p in pg.path.head(6)]
    return (" ".join(norm(" ".join(filter(None, (d.get("title"), d.get("text"), d.get("chrome_text"))))) for d in docs),
            " ".join(norm(d.get("title") or "") for d in docs))


def identity_checks(si: pd.DataFrame, sample: pd.DataFrame) -> dict:
    """Rejected rows that a normalised name (& = and, Sri = Sree = Shri) or the record's street address would recover, counted
    only without a conflict and with the record's PIN or locality on the site; and accepted medium sites whose page titles
    or name line carry another district or city of the gazetteer (anywhere, not only after 'in')."""
    pages = pd.read_parquet(f"{ROOT}/kb/crawl/pages.parquet", columns=["target_id", "unique_ids", "path"]).explode("unique_ids").dropna(subset=["path"])
    raw = pd.read_parquet(f"{ROOT}/data/raw/facilities.parquet", columns=["unique_id", "name", "address_line1", "address_city"]).drop_duplicates("unique_id").set_index("unique_id")
    loc = pd.read_parquet(f"{ROOT}/cleaning/geo_identity/facility_location.parquet", columns=["unique_id", "district"]).drop_duplicates("unique_id").set_index("unique_id")
    g = pd.read_parquet(f"{ROOT}/derived/v1/place_gazetteer.parquet", columns=["name", "kind"])
    places = {norm(n) for n in g[g.kind.isin(["district", "city"])].name} - {""}
    cache: dict = {}
    rej = si[~si.attributable & si.kind.isin(["site", "branch"]) & ~si.parked_page]
    rec = {"name": [], "address_only": []}
    for r in rej.itertuples():
        conflict = r.other_pin_only or bool(r.domain_other_place)
        if r.name_how != "none" or conflict or not (r.pin_found or r.locality_found):
            continue
        txt, _ = page_texts(r, pages, cache)
        core = norm(re.split(r"[,(\u2013-]| in ", raw.at[r.unique_id, "name"])[0])
        addr = norm(raw.at[r.unique_id, "address_line1"] or "")
        if len(core) >= 8 and f" {core} " in f" {txt} ":
            rec["name"].append((r.unique_id, r.target_id, raw.at[r.unique_id, "name"]))
        elif len(addr) >= 12 and addr in txt:
            rec["address_only"].append((r.unique_id, r.target_id, raw.at[r.unique_id, "name"]))
    med = si[si.attributable & (si.confidence == "medium") & (si.kind == "site")]
    other = []
    for r in med.itertuples():
        _, titles = page_texts(r, pages, cache)
        line = f" {titles} {norm(r.name_quote if isinstance(r.name_quote, str) else "")} "
        own = norm(f"{raw.at[r.unique_id, 'name']} {raw.at[r.unique_id, 'address_city']} {loc.district.get(r.unique_id, '') or ''}")
        hits = sorted(p for p in places if len(p) >= 5 and f" {p} " in line and p not in own)
        if hits:
            other.append((r.unique_id, r.target_id, hits[0]))
    cache.clear()
    keyset = lambda rows: {(u, t) for u, t, _ in rows}
    def in_sample(rows: list, strata: list[str]) -> dict:
        s = sample[sample.stratum.isin(strata)]
        s = s[[(u, t) in keyset(rows) for u, t in zip(s.unique_id, s["item"])]]
        return {"wrong_fixed": int((~s.correct).sum()), "right_changed": int(s.correct.sum()), "n": [int(v) for v in s.n]}
    return {"rejected_site_or_branch_rows_not_parked": len(rej),
            "recoverable_by_normalised_name": len(rec["name"]), "recoverable_by_street_address_only": len(rec["address_only"]),
            "recoverable_examples": [x[2] for x in rec["name"][:6]] + [x[2] for x in rec["address_only"][:3]],
            "recoverable_in_sample": in_sample(rec["name"] + rec["address_only"], ["id_rej_low", "id_rej_none"]),
            "medium_own_sites": len(med), "medium_by_name_how": med.name_how.value_counts().to_dict(),
            "medium_with_other_place_in_title_or_name_line": len(other), "medium_other_place_examples": [x[2] for x in other[:8]],
            "medium_other_place_in_sample": in_sample(other, ["id_acc_medium"])}


FOREIGN = {"nepal", "kathmandu", "bangladesh", "dhaka", "dubai", "nairobi", "accra", "lagos", "colombo"}


def evidence_cells(svc: pd.DataFrame, sample: pd.DataFrame) -> dict:
    """Precision of positive (record, service) pairs by evidence structure: strength x pages x line kind of the best quote."""
    ss = pd.read_parquet(f"{OUT}/web_service_summary.parquet")
    ss = ss[ss.web_positive & (ss.scope != "chain_home")]
    lk = svc[["unique_id", "service_id", "quote", "final_url", "field", "line_kind"]].drop_duplicates(["unique_id", "service_id", "quote", "final_url", "field"])
    ss = ss.merge(lk, left_on=["unique_id", "service_id", "best_quote", "best_url", "best_field"], right_on=["unique_id", "service_id", "quote", "final_url", "field"], how="left")

    def cell(strong: pd.Series, pages: pd.Series, kind: pd.Series) -> pd.Series:
        return pd.Series(["A strong, 2+ pages" if st and pg >= 2 else "B strong, 1 page, list item" if st and k == "item" else "C strong, 1 page, sentence" if st
                          else "D weak, 2+ pages" if pg >= 2 else "E weak, 1 page" for st, pg, k in zip(strong, pages, kind)], index=strong.index)
    pop = cell(ss.web_positive_strong, ss.n_pages_positive, ss.line_kind).value_counts()
    sv = sample[sample.group == "svc"]
    sc = cell(sv.stratum.str.endswith("strong"), sv.value.astype(int), sv.line_kind)
    out = {}
    for c in sorted(pop.index):
        d = sv[sc == c]
        out[c] = {"pairs": int(pop[c]), "share": round(int(pop[c]) / len(ss), 3), "sample_k": int(d.correct.sum()), "sample_n": len(d), "wilson": wilson(int(d.correct.sum()), len(d))}
    return out


def other_place_pages(svc: pd.DataFrame, fd: pd.DataFrame, facts: pd.DataFrame, sample: pd.DataFrame) -> dict:
    """Evidence on a page whose title or URL path names a district or city (gazetteer, 5+ letters) or a foreign place that
    is not the record's own name, city or district: a chain or branch page about somewhere else."""
    raw = pd.read_parquet(f"{ROOT}/data/raw/facilities.parquet", columns=["unique_id", "name", "address_city"]).drop_duplicates("unique_id").set_index("unique_id")
    loc = pd.read_parquet(f"{ROOT}/cleaning/geo_identity/facility_location.parquet", columns=["unique_id", "district"]).drop_duplicates("unique_id").set_index("unique_id")
    g = pd.read_parquet(f"{ROOT}/derived/v1/place_gazetteer.parquet", columns=["name", "kind"])
    places = ({norm(n) for n in g[g.kind.isin(["district", "city"])].name} | FOREIGN) - {""}
    places = {p for p in places if len(p) >= 5}
    titles = pd.read_parquet(f"{ROOT}/kb/crawl/pages.parquet", columns=["path", "title"]).drop_duplicates("path").set_index("path").title
    def own_place(u: str) -> str:
        return " " + norm(" ".join(str(v or "") for v in (raw.at[u, "name"], raw.at[u, "address_city"], loc.district.get(u)))) + " "

    own = {u: own_place(u) for u in set(svc.unique_id) | set(facts.unique_id) if u in raw.index}

    def flag(uids: pd.Series, paths: pd.Series, urls: pd.Series) -> pd.Series:
        res = []
        for u, p, url in zip(uids, paths, urls):
            line = f" {norm(str(titles.get(p, '') or ''))} {norm(re.sub(r'^https?://[^/]+', '', str(url)))} "
            o = own.get(u, " ")
            res.append(any(f" {pl} " in line and f" {pl} " not in o for pl in places if pl[:3] in line))
        return pd.Series(res, index=uids.index)

    pos = svc[svc.attributable & svc.positive & (svc.scope != "chain_home")]
    hit = flag(pos.unique_id, pos.path, pos.final_url)
    pairs = pos.groupby(["unique_id", "service_id"]).size()
    keep = set(pos[~hit].groupby(["unique_id", "service_id"]).size().index)
    dropped = set(pairs.index) - keep
    sv = sample[sample.group == "svc"]
    s1 = sv[[(u, i) in dropped for u, i in zip(sv.unique_id, sv["item"])]]
    f = facts.drop_duplicates("fact_id").set_index("fact_id")
    x = fd[fd.n_usable > 0].join(f[["path", "final_url"]], on="best_fact_id")
    xh = flag(x.unique_id, x.path, x.final_url)
    keys = set(zip(x[xh].unique_id, x[xh].fact_type + ":" + x[xh].attribute))
    sx = sample[sample.group.isin(["hrs", "det"])]
    s2 = sx[[(u, i) in keys for u, i in zip(sx.unique_id, sx["item"])]]
    return {"service_rows_hit": int(hit.sum()), "service_pairs_dropped": len(dropped), "of_pairs": len(pairs),
            "service_sample": {"wrong_removed": int((~s1.correct).sum()), "right_lost": int(s1.correct.sum()), "n": [int(v) for v in s1.n]},
            "facility_facts_whose_best_page_hits": int(xh.sum()), "of_facts": len(x),
            "fact_sample": {"wrong_removed": int((~s2.correct).sum()), "right_lost": int(s2.correct.sum()), "n": [int(v) for v in s2.n]}}


def main() -> None:
    sample = pd.read_csv(f"{QA_OUT}/sample_scored.csv", keep_default_na=False)
    sample["correct"] = sample.correct.astype(str) == "True"
    svc = pd.read_parquet(f"{OUT}/web_services.parquet")
    hrs, det = pd.read_parquet(f"{OUT}/web_hours.parquet"), pd.read_parquet(f"{OUT}/web_details.parquet")
    facts = pd.concat([hrs, det], ignore_index=True)
    pi = pd.read_parquet(f"{OUT}/page_identity.parquet")
    si = pd.read_parquet(f"{OUT}/site_identity.parquet")
    fd = pd.read_parquet(f"{OUT}/web_facility_details.parquet")
    res = {"quotes": check_quotes({"svc": svc, "hrs": hrs, "det": det}, pi), "quote_shape": quote_shape(svc, facts),
           "facility_values": facility_value_check(fd, facts), "services": service_patterns(svc, sample),
           "facts": fact_patterns(fd, sample), "identity": identity_checks(si, sample),
           "evidence_cells": evidence_cells(svc, sample), "other_place_pages": other_place_pages(svc, fd, facts, sample)}
    json.dump(res, open(f"{QA_OUT}/scan.json", "w"), indent=1, default=str)
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
