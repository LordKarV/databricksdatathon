"""40-item self-check of the web evidence, read by hand.

`sample` draws a stratified sample (seed 3033) into out/selfcheck_sample.csv:
  8 site identity rows (4 attributable, 4 not), 16 positive service pairs (6 that confirm a dataset claim, 6 web-only
  with an offer cue (strength strong), 4 web-only without one (weak)),
  4 negated service rows, 7 hour facts (3 emergency 24x7, 2 OPD, 1 LLM reading, 1 service-specific 24x7), 5 details.
`score` joins the verdicts in LABELS (written after reading each item with its line, page URL and record name and city)
and writes out/selfcheck.json with precision and 95% Wilson intervals.
Criteria: identity, the verdict (attributable or not) is right for the record; service, read with its line, the quote
says this facility provides the service now; negated, the line really says the service is not offered here; hours and
details, the fact type, attribute and value are what the quote says about this facility.
Run: .venv/bin/python selfcheck.py sample | score
"""
from __future__ import annotations

import json
import os
import sys

import pandas as pd

from compare_dataset import OUT, ROOT, dataset_claims, wilson

SEED = 3033  # round 3 (scored). Rounds 1 (seed 20261121) and 2 (seed 2027) drove fixes; kept in out/selfcheck_round1.csv, _round2.csv


def sample() -> pd.DataFrame:
    loc = pd.read_parquet(f"{ROOT}/cleaning/geo_identity/facility_location.parquet", columns=["unique_id", "name", "address_city", "pin"])
    si = pd.read_parquet(os.path.join(OUT, "site_identity.parquet"))
    si = si[si.kind == "site"]
    ss = pd.read_parquet(os.path.join(OUT, "web_service_summary.parquet"))
    svc = pd.read_parquet(os.path.join(OUT, "web_services.parquet"))
    hrs = pd.read_parquet(os.path.join(OUT, "web_hours.parquet"))
    det = pd.read_parquet(os.path.join(OUT, "web_details.parquet"))
    hrs, det = hrs[hrs.attributable & (hrs.status != "excluded") & (hrs.polarity == "positive")], det[det.attributable & (det.status != "excluded") & (det.polarity == "positive")]
    dc = dataset_claims(set(ss.unique_id))
    claimed = set(zip(dc[dc.text_any | dc.spec].unique_id, dc[dc.text_any | dc.spec].service_id))
    pos = ss[ss.web_positive & (ss.scope != "chain_home")].assign(in_ds=lambda x: [(u, s) in claimed for u, s in zip(x.unique_id, x.service_id)])
    items = []
    add = lambda df, kind, n, **cols: items.extend({"stratum": kind, **{k: r[v] if v in r else v for k, v in cols.items()}, "unique_id": r["unique_id"]}
                                                  for r in df.sample(n, random_state=SEED).to_dict("records"))
    idc = dict(item="confidence", quote="name_quote", context="locality_quote", url="name_url", value="pin_quote")
    add(si[si.attributable], "identity_attributable", 4, **idc)
    add(si[~si.attributable], "identity_not_attributable", 4, **idc)
    sc = dict(item="service_id", quote="best_quote", url="best_url", value="n_pages_positive", context="best_field")
    add(pos[pos.in_ds], "service_confirms_dataset", 6, **sc)
    add(pos[~pos.in_ds & pos.web_positive_strong], "service_web_only_strong", 6, **sc)
    add(pos[~pos.in_ds & ~pos.web_positive_strong], "service_web_only_weak", 4, **sc)
    add(svc[svc.attributable & svc.negated], "service_negated", 4, item="service_id", quote="quote", url="final_url", value="nonoffer_cue", context="segment")
    hc = dict(item="attribute", quote="quote", url="final_url", value="value_text", context="source_text")
    add(hrs[(hrs.fact_type == "hours_24x7") & (hrs.attribute == "emergency")], "hours_24x7_emergency", 3, **hc)
    add(hrs[(hrs.fact_type == "opd_hours") & (hrs.method == "regex") & hrs.attribute.isin(["opd", "general"])], "hours_opd", 2, **hc)
    add(hrs[hrs.method == "llm"], "hours_llm", 1, **hc)
    add(hrs[(hrs.fact_type == "hours_24x7") & hrs.attribute.isin(["icu", "dialysis", "blood_bank", "lab_imaging", "pharmacy"])], "hours_service_24x7", 1, **hc)
    for ft in ("unit_beds", "accreditation", "empanelment", "ambulance", "blood_centre"):
        d = det[det.fact_type == ft]
        add(d, "detail_" + ft, 1, item="attribute", quote="quote", url="final_url", value="value_num" if ft == "unit_beds" else "value_text", context="source_text")
    s = pd.DataFrame(items).merge(loc, on="unique_id", how="left")
    s.insert(0, "n", range(1, len(s) + 1))
    s.to_csv(os.path.join(OUT, "selfcheck_sample.csv"), index=False)
    return s


# n -> (correct, note). Filled in after reading out/selfcheck_sample.csv.
LABELS: dict[int, tuple[bool, str]] = {
    1: (True, "PIN 518501 on the site"), 2: (True, "R.K. Devi Memorial Hospital, Kanpur"), 3: (True, "doctor-named maternity hospital, PIN 751007"),
    4: (True, "Amritsar on the site"), 5: (True, "Indonesian spam page on an expired domain"), 6: (True, "ushahospital.com is a Lucknow hospital; the record's Muzaffarpur site is another target, rated high"),
    7: (True, "empty server page"), 8: (True, "empty page"),
    9: (True, "menu item on an ENT hospital site"), 10: (True, ""), 11: (True, ""), 12: (True, "awake craniotomies imply neurosurgery"),
    13: (True, "hemato-oncology menu item"), 14: (True, ""),
    15: (False, "phone support outside OPD hours, not an emergency department"), 16: (True, "fracture care after road crashes"), 17: (True, ""),
    18: (True, "listed on the clinic's services page; unusual for a urology clinic"), 19: (True, ""), 20: (True, ""),
    21: (True, "snake bite listed under toxicological emergencies"), 22: (False, "NRC is the board's Nomination and Remuneration Committee"),
    23: (True, "C-section delivery offered"), 24: (True, ""),
    25: (True, "right to exclude: catheter treatment instead of open-heart surgery"), 26: (True, "patient testimonial, no offer statement"),
    27: (True, "right outcome, wrong reason: 'without cut' fired; EUS is not the ultrasound service"), 28: (True, "educational MRI line; right to exclude"),
    29: (True, ""), 30: (True, ""), 31: (True, ""), 32: (False, "bare time range on an accreditation page; nothing says what it is"),
    33: (True, ""), 34: (True, "doctor session; day from the same line"), 35: (True, ""),
    36: (True, ""), 37: (True, ""), 38: (True, ""), 39: (True, "facility landline left in the text by the crawl redaction"), 40: (True, "listed by a diagnostics centre"),
}


def score() -> None:
    s = pd.read_csv(os.path.join(OUT, "selfcheck_sample.csv"))
    assert len(s) == 40 and set(LABELS) == set(s.n), "label every item"
    s["correct"] = s.n.map(lambda n: LABELS[n][0])
    s["note"] = s.n.map(lambda n: LABELS[n][1])
    s.to_csv(os.path.join(OUT, "selfcheck_sample.csv"), index=False)
    grp = lambda df: {"k": int(df.correct.sum()), "n": len(df), "wilson": wilson(int(df.correct.sum()), len(df))}
    res = {"all": grp(s), "by_group": {g: grp(d) for g, d in s.groupby(s.stratum.str.split("_").str[0])},
           "by_stratum": {g: grp(d) for g, d in s.groupby("stratum")}, "wrong": s[~s.correct][["n", "stratum", "item", "note"]].to_dict("records")}
    json.dump(res, open(os.path.join(OUT, "selfcheck.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    if sys.argv[1:] == ["sample"]:
        pd.set_option("display.width", 250)
        pd.set_option("display.max_colwidth", 400)
        for r in sample().to_dict("records"):
            print(f"--- {r['n']} {r['stratum']} | {r['item']} | value={r['value']} | {r['name']} ({r['address_city']}, {r['pin']})\n  url: {r['url']}\n  quote: {r['quote']!r}\n  context: {str(r['context'])[:400]!r}")
    else:
        score()
