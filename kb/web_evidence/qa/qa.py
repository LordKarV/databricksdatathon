"""Adversarial QA of kb/web_evidence: a fresh stratified sample read by hand against the stored page text.

Subcommands (run from anywhere with the project venv):
  sample  draws 150 items (seed 4242) into qa/out/sample.csv, skipping (record, item) pairs used by the 3 self-check rounds:
          60 service pairs (15 each: confirms a dataset claim x strong/weak, web-only x strong/weak),
          30 hour facts (10 emergency 24x7, 10 OPD/general regex schedule, 5 LLM readings, 5 other usable hour facts),
          30 detail facts (6 beds, 6 accreditation, 6 empanelment, 4 ambulance, 4 blood centre, 4 other),
          30 site-identity decisions (accepted: 10 high, 5 medium; rejected: 10 low, 5 none; own sites and branch pages).
  show    prints every item with its record, the page title and a window of page text around the quote.
  score   joins LABELS (qa/labels.py) and writes qa/out/qa_results.json with per-stratum and per-type precision, Wilson
          intervals and stratum-weighted estimates.
Sampling units are what a downstream step reads: (record, service) pairs from web_service_summary (judged on best_quote),
(record, fact_type, attribute) rows from web_facility_details with n_usable > 0 (judged on best_quote), and site_identity rows.
"""
from __future__ import annotations

import gzip
import json
import os
import sys

import pandas as pd

ROOT = "/Users/karthikvattem/projects/datathon"
WE = f"{ROOT}/kb/web_evidence"
OUT = f"{WE}/out"
QA_OUT = f"{WE}/qa/out"
sys.path.insert(0, WE)
sys.path.insert(0, f"{WE}/qa")
from compare_dataset import dataset_claims, wilson  # noqa: E402

SEED = 4242
SVC_STRATA = {"svc_confirm_strong": 15, "svc_confirm_weak": 15, "svc_webonly_strong": 15, "svc_webonly_weak": 15}
HRS_STRATA = {"hrs_emergency_24x7": 10, "hrs_opd_regex": 10, "hrs_llm": 5, "hrs_other": 5}
DET_STRATA = {"det_beds": 6, "det_accreditation": 6, "det_empanelment": 6, "det_ambulance": 4, "det_blood_centre": 4, "det_other": 4}
ID_STRATA = {"id_acc_high": 10, "id_acc_medium": 5, "id_rej_low": 10, "id_rej_none": 5}


def used_before() -> set[tuple[str, str]]:
    """(record, item) pairs already read in the extraction step's self-check rounds."""
    used = set()
    for f in ("selfcheck_sample.csv", "selfcheck_round1.csv", "selfcheck_round2.csv"):
        s = pd.read_csv(f"{OUT}/{f}")
        used |= set(zip(s.unique_id, s["item"].astype(str)))
    return used


def draw(df: pd.DataFrame, stratum: str, n: int, used: set, item_col: str) -> pd.DataFrame:
    df = df[[(u, str(i)) not in used for u, i in zip(df.unique_id, df[item_col])]]
    return df.sample(n, random_state=SEED).assign(stratum=stratum, pop_n=len(df))


def service_items(used: set) -> pd.DataFrame:
    ss = pd.read_parquet(f"{OUT}/web_service_summary.parquet")
    pos = ss[ss.web_positive & (ss.scope != "chain_home")].copy()
    dc = dataset_claims(set(ss.unique_id))
    claimed = set(zip(dc[dc.text_any | dc.spec].unique_id, dc[dc.text_any | dc.spec].service_id))
    pos["in_ds"] = [(u, s) in claimed for u, s in zip(pos.unique_id, pos.service_id)]
    cells = {"svc_confirm_strong": pos.in_ds & pos.web_positive_strong, "svc_confirm_weak": pos.in_ds & ~pos.web_positive_strong,
             "svc_webonly_strong": ~pos.in_ds & pos.web_positive_strong, "svc_webonly_weak": ~pos.in_ds & ~pos.web_positive_strong}
    s = pd.concat([draw(pos[m], k, SVC_STRATA[k], used, "service_id") for k, m in cells.items()])
    # locate the page file holding best_quote (summary keeps URL and field, not the path)
    svc = pd.read_parquet(f"{OUT}/web_services.parquet", columns=["unique_id", "service_id", "quote", "final_url", "field", "path", "line_kind", "role", "segment"])
    svc = svc.drop_duplicates(["unique_id", "service_id", "quote", "final_url", "field"])
    s = s.merge(svc, left_on=["unique_id", "service_id", "best_quote", "best_url", "best_field"],
                right_on=["unique_id", "service_id", "quote", "final_url", "field"], how="left")
    assert s.path.notna().all(), "every best quote must map to a stored page"
    return s.rename(columns={"service_id": "item", "best_url": "url", "n_pages_positive": "value"})[
        ["stratum", "pop_n", "unique_id", "item", "value", "quote", "url", "field", "path", "line_kind", "role"]]


def fact_items(used: set) -> pd.DataFrame:
    fd = pd.read_parquet(f"{OUT}/web_facility_details.parquet")
    fd = fd[fd.n_usable > 0].copy()
    fd["key"] = fd.fact_type + ":" + fd.attribute
    facts = pd.concat([pd.read_parquet(f"{OUT}/{t}.parquet", columns=["fact_id", "path", "field", "final_url", "method", "scope", "value_text", "value_num"])
                       for t in ("web_hours", "web_details")]).drop_duplicates("fact_id").rename(columns={"value_text": "fact_value_text", "value_num": "fact_value_num"})
    fd = fd.merge(facts, left_on="best_fact_id", right_on="fact_id", how="left")
    assert fd.path.notna().all()
    fd = fd[fd.scope != "chain_home"]
    ft, at = fd.fact_type, fd.attribute
    hrs = ft.isin(["hours_24x7", "opd_hours", "hours_dialysis_shifts"])
    cells = {"hrs_emergency_24x7": (ft == "hours_24x7") & (at == "emergency"),
             "hrs_opd_regex": (ft == "opd_hours") & at.isin(["opd", "general"]) & (fd.method == "regex"),
             "hrs_llm": hrs & (fd.method == "llm")}
    cells["hrs_other"] = hrs & ~(cells["hrs_emergency_24x7"] | cells["hrs_opd_regex"] | cells["hrs_llm"])
    named = {"det_beds": "unit_beds", "det_accreditation": "accreditation", "det_empanelment": "empanelment", "det_ambulance": "ambulance", "det_blood_centre": "blood_centre"}
    for k, v in named.items():
        cells[k] = ft == v
    cells["det_other"] = ~hrs & ~ft.isin(list(named.values()))
    n = {**HRS_STRATA, **DET_STRATA}
    s = pd.concat([draw(fd[m], k, n[k], used, "key") for k, m in cells.items()])
    val = [f"{t}" if pd.notna(t) and t != "" else f"{v}" for t, v in zip(s.value_text, s.value_num)]
    return s.assign(item=s.key, value=val, quote=s.best_quote, url=s.best_url)[
        ["stratum", "pop_n", "unique_id", "item", "value", "quote", "url", "field", "path", "method"]]


def identity_items(used: set) -> pd.DataFrame:
    si = pd.read_parquet(f"{OUT}/site_identity.parquet")
    si = si[si.kind.isin(["site", "branch"])]
    cells = {"id_acc_high": si.attributable & (si.confidence == "high"), "id_acc_medium": si.attributable & (si.confidence == "medium"),
             "id_rej_low": ~si.attributable & (si.confidence == "low"), "id_rej_none": ~si.attributable & (si.confidence == "none")}
    s = pd.concat([draw(si[m], k, ID_STRATA[k], used, "confidence") for k, m in cells.items()])
    return s.assign(item=s.target_id, value=s.confidence, quote=s.name_quote, url=s.name_url)[
        ["stratum", "pop_n", "unique_id", "item", "value", "quote", "url", "target_id", "name_how", "pin_quote", "locality_quote",
         "other_pin_only", "domain_other_place", "parked_page"]]


def sample() -> pd.DataFrame:
    used = used_before()
    s = pd.concat([service_items(used), fact_items(used), identity_items(used)], ignore_index=True)
    raw = pd.read_parquet(f"{ROOT}/data/raw/facilities.parquet", columns=["unique_id", "name", "address_line1", "address_city", "address_zipOrPostcode", "officialWebsite", "organization_type", "facilityTypeId"])
    s = s.merge(raw, on="unique_id", how="left")
    s.insert(0, "n", range(1, len(s) + 1))
    s.insert(1, "group", s.stratum.str.split("_").str[0])
    os.makedirs(QA_OUT, exist_ok=True)
    s.to_csv(f"{QA_OUT}/sample.csv", index=False)
    return s


def page(path: str) -> dict:
    return json.load(gzip.open(os.path.join(ROOT, path)))


def context(doc: dict, field: str, quote: str, pad: int = 350) -> str:
    t = doc.get(field) or ""
    i = t.find(quote)
    if i < 0:
        return "<<QUOTE NOT FOUND IN FIELD>>"
    return t[max(0, i - pad):i] + " >>>" + quote + "<<< " + t[i + len(quote):i + len(quote) + pad]


def show_identity(r: dict, pages: pd.DataFrame) -> None:
    p = pages[(pages.target_id == r["target_id"]) & pages.unique_ids.map(lambda u: r["unique_id"] in u)]
    print(f"  pin_quote={r['pin_quote']!r}\n  loc_quote={str(r['locality_quote'])[:200]!r}\n  other_pin_only={r['other_pin_only']} other_place={r['domain_other_place']!r} parked={r['parked_page']}")
    for _, pg in p.head(6).iterrows():
        if not isinstance(pg.path, str):
            continue
        d = page(pg.path)
        print(f"  [{pg.role}] {pg.final_url} | title={d.get('title')!r}\n     text: {(d.get('text') or '')[:350]!r}\n     chrome: {(d.get('chrome_text') or '')[-200:]!r}")


def show(only: set[int] | None = None) -> None:
    s = pd.read_csv(f"{QA_OUT}/sample.csv", keep_default_na=False)
    pages = pd.read_parquet(f"{ROOT}/kb/crawl/pages.parquet", columns=["target_id", "unique_ids", "final_url", "role", "path"])
    for r in s.to_dict("records"):
        if only and r["n"] not in only:
            continue
        print(f"=== {r['n']} {r['stratum']} | {r['item']} | value={r['value']} | {r['name']} ({r['address_city']}, {r['address_zipOrPostcode']}) "
              f"type={r['facilityTypeId']} web={r['officialWebsite']}\n  addr: {r['address_line1']}\n  url: {r['url']}  field={r.get('field')} kind={r.get('line_kind')} role={r.get('role')}")
        if r["group"] == "id":
            print(f"  name_how={r['name_how']} name_quote={r['quote']!r}")
            show_identity(r, pages)
        else:
            d = page(r["path"])
            print(f"  title: {d.get('title')!r}\n  quote: {r['quote']!r}\n  ctx: {context(d, r['field'], r['quote'])!r}")


def score() -> None:
    from qa_labels import LABELS
    s = pd.read_csv(f"{QA_OUT}/sample.csv", keep_default_na=False)
    assert set(LABELS) == set(s.n), f"label every item; missing {sorted(set(s.n) - set(LABELS))}"
    s["correct"] = s.n.map(lambda n: LABELS[n][0])
    s["error"] = s.n.map(lambda n: LABELS[n][1])
    s["note"] = s.n.map(lambda n: LABELS[n][2])
    # accepted and rejected identity decisions answer different questions, so they are scored as separate types
    s["group"] = s.group.where(s.group != "id", s.stratum.str[:6])
    s.to_csv(f"{QA_OUT}/sample_scored.csv", index=False)

    def grp(df: pd.DataFrame) -> dict:
        k, n = int(df.correct.sum()), len(df)
        out = {"k": k, "n": n, "p": round(k / n, 3), "wilson": wilson(k, n)}
        if df.stratum.nunique() > 1:  # weight each stratum by its population size; bounds are the weighted stratum Wilson bounds
            st = df.groupby("stratum").agg(k=("correct", "sum"), n=("correct", "size"), N=("pop_n", "first"))
            w = st.N / st.N.sum()
            lo_hi = [wilson(int(a), int(b)) for a, b in zip(st.k, st.n)]
            out["weighted_p"] = round(float((w * st.k / st.n).sum()), 3)
            out["weighted_bounds"] = (round(float(sum(wi * l for wi, (l, _) in zip(w, lo_hi))), 3), round(float(sum(wi * h for wi, (_, h) in zip(w, lo_hi))), 3))
        return out

    res = {"all": grp(s), "by_group": {g: grp(d) for g, d in s.groupby("group")}, "by_stratum": {g: grp(d) for g, d in s.groupby("stratum")},
           "errors_by_pattern": s[~s.correct].error.value_counts().to_dict(),
           "wrong": s[~s.correct][["n", "stratum", "item", "error", "note"]].to_dict("records")}
    json.dump(res, open(f"{QA_OUT}/qa_results.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "sample":
        print(sample().groupby("stratum").pop_n.agg(["size", "first"]).to_string())
    elif cmd == "show":
        show({int(x) for x in sys.argv[2:]} or None)
    elif cmd == "score":
        score()
    else:
        sys.exit(__doc__)
