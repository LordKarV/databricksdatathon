"""Fresh stratified sample for hand judgment (seed 7171).

  sample  -> out/sample.csv: 60 service pairs, 30 hour facts, 30 detail facts, 30 identity decisions (same strata and
             sampling units as kb/web_evidence/qa/qa.py, so the numbers compare), plus 40 vf_details usable text facts.
             Skips every (record, item) already read by the 3 self-check rounds, the QA sample and the vf hand check.
  show [n ...]  prints each item with the record and the source text around the quote.
Verdicts live in labels.py: LABELS[n] = (correct: bool, error_pattern: str, note: str).
"""
from __future__ import annotations

import importlib.util
import os
import sys

import pandas as pd

ROOT = "/Users/karthikvattem/projects/datathon"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
SEED = 7171
VF_ALLOC = {"hours_24x7": 6, "unit_beds": 5, "empanelment": 5, "staffing": 5, "accreditation": 4, "ambulance": 3,
            "free_or_government": 3, "blood_centre": 3, "equipment_count": 3, "opd_hours": 3}

sys.path.insert(0, f"{ROOT}/kb/web_evidence")
_spec = importlib.util.spec_from_file_location("we_qa", f"{ROOT}/kb/web_evidence/qa/qa.py")
QA = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(QA)
QA.SEED = SEED  # qa.draw reads the module-level seed


def vf_items() -> pd.DataFrame:
    f = pd.read_parquet(f"{ROOT}/kb/vf_details/out/facts.parquet")
    u = f[f.status.isin(["ok", "flagged"]) & (f.polarity == "positive") & f.method.isin(["regex", "llm"])]
    u = u[~u.fact_id.isin(pd.read_csv(f"{ROOT}/kb/vf_details/handcheck_labels.csv").fact_id)]
    parts = [u[u.fact_type == t].sample(n, random_state=SEED).assign(stratum=f"vf_{t}", pop_n=int((u.fact_type == t).sum())) for t, n in VF_ALLOC.items()]
    s = pd.concat(parts)
    val = [f"{t}" if isinstance(t, str) and t else f"{v}" for t, v in zip(s.value_text, s.value_num)]
    return s.assign(item=s.fact_type + ":" + s.attribute, value=val, url="", path="", field=s.field)[
        ["stratum", "pop_n", "unique_id", "item", "value", "quote", "url", "field", "path", "method", "fact_id", "source_text", "status", "flags"]]


def sample() -> pd.DataFrame:
    used = QA.used_before()
    qa = pd.read_csv(f"{ROOT}/kb/web_evidence/qa/out/sample.csv", keep_default_na=False)
    used |= set(zip(qa.unique_id, qa["item"].astype(str)))
    s = pd.concat([QA.service_items(used), QA.fact_items(used), QA.identity_items(used), vf_items()], ignore_index=True)
    raw = pd.read_parquet(f"{ROOT}/data/raw/facilities.parquet", columns=["unique_id", "name", "address_line1", "address_city", "address_zipOrPostcode", "officialWebsite", "facilityTypeId"])
    s = s.merge(raw.drop_duplicates("unique_id"), on="unique_id", how="left")
    s.insert(0, "n", range(1, len(s) + 1))
    s.insert(1, "group", s.stratum.str.split("_").str[0])
    os.makedirs(OUT, exist_ok=True)
    s.to_csv(f"{OUT}/sample.csv", index=False)
    return s


def show(only: set[int] | None) -> None:
    s = pd.read_csv(f"{OUT}/sample.csv", keep_default_na=False)
    pages = pd.read_parquet(f"{ROOT}/kb/crawl/pages.parquet", columns=["target_id", "unique_ids", "final_url", "role", "path"])
    for r in s.to_dict("records"):
        if only and r["n"] not in only:
            continue
        print(f"=== {r['n']} {r['stratum']} | {r['item']} | value={r['value']} | {r['name']} ({r['address_city']}, {r['address_zipOrPostcode']}) "
              f"type={r['facilityTypeId']} web={r['officialWebsite']}\n  addr: {r['address_line1']}")
        if r["group"] == "id":
            print(f"  name_how={r['name_how']} name_quote={r['quote']!r}")
            QA.show_identity(r, pages)
        elif r["group"] == "vf":
            print(f"  status={r['status']} flags={r['flags']} method={r['method']}\n  quote: {r['quote']!r}\n  src: {r['source_text'][:600]!r}")
        else:
            d = QA.page(r["path"])
            print(f"  url: {r['url']} field={r['field']} kind={r.get('line_kind')} role={r.get('role')}\n  title: {d.get('title')!r}\n  quote: {r['quote']!r}\n  ctx: {QA.context(d, r['field'], r['quote'], 300)!r}")


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    if sys.argv[1:2] == ["sample"]:
        print(sample().groupby("stratum").pop_n.agg(["size", "first"]).to_string())
    elif sys.argv[1:2] == ["show"]:
        show({int(x) for x in sys.argv[2:]} or None)
    else:
        sys.exit(__doc__)
