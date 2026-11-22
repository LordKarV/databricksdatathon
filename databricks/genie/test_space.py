"""Ask the Genie space 7 planner questions through the Conversation API and compare with our own SQL.

    python databricks/genie/test_space.py        # writes test_results.json next to this file

Each test has a ground-truth SQL (run by us on the warehouse) and a check that compares Genie's result
rows and text with it. Honesty checks look at Genie's text: no "no care" wording for zero-evidence places.
"""
import json
import re
import sys
from pathlib import Path

from space import HERE, S, cli, run_sql

SPACE_ID = (HERE / "space_id.txt").read_text().strip()
BANNED = re.compile(r"\bno (dialysis|trauma|c-section|caesarean)? ?(care|facilit(y|ies)|services?) (exists?|available)\b"
                    r"|\bthere (is|are) no (dialysis|trauma)\b", re.I)


def cells(rows):
    return {str(v).strip().lower() for r in rows for v in r if v is not None}


def num_in(value, rows, text, tol=0.0):
    """value appears as a result cell, or as a number in the text."""
    nums = []
    for c in cells(rows) | set(re.findall(r"-?\d[\d,]*\.?\d*", text)):
        try:
            nums.append(float(str(c).replace(",", "")))
        except ValueError:
            pass
    return any(abs(n - value) <= tol for n in nums)


TESTS = [
    dict(q="How many districts in Uttar Pradesh have no confirmed dialysis facility, and how many people live in them?",
         sql=f"SELECT COUNT(*), ROUND(SUM(pop)/1e6, 1) FROM {S}.geo_dialysis_district "
             "WHERE nfhs_state = 'Uttar Pradesh' AND n_corr = 0",
         check=lambda gt, rows, text: num_in(float(gt[0][0]), rows, text)
         or len(rows) == int(gt[0][0])),
    dict(q="Among states with at least 100 trauma or emergency claims, which has the lowest share confirmed by a "
           "second source?",
         sql=f"SELECT stname, COUNT(*) n, ROUND(100*AVG(CASE WHEN trauma_corroborated THEN 1 ELSE 0 END), 1) pct "
             f"FROM {S}.geo_facility WHERE trauma_claimed GROUP BY stname HAVING COUNT(*) >= 100 ORDER BY pct LIMIT 1",
         check=lambda gt, rows, text: bool(rows) and str(rows[0][0]).lower() == gt[0][0].lower()),
    dict(q="Cite the claim ids behind the dialysis claim of Ford Hospital And Research Center in Patna.",
         sql=f"SELECT e.claim_id FROM (SELECT EXPLODE(FROM_JSON(gr.cite_evidence, "
             "'array<struct<claim_id:string,field:string,text:string>>')) e "
             f"FROM {S}.grades gr JOIN {S}.geo_facility g ON g.unique_id = gr.unique_id "
             "WHERE gr.service = 'dialysis' AND g.name = 'Ford Hospital And Research Center' AND g.dtname = 'Patna')",
         check=lambda gt, rows, text: all(r[0].lower() in (cells(rows) | {text.lower()}) or r[0] in text
                                          or any(r[0] in c for c in cells(rows)) for r in gt)),
    dict(q="How many facilities in Maharashtra hold a LaQshya certificate that is still valid?",
         sql=f"SELECT COUNT(DISTINCT l.unique_id) FROM {S}.facility_list_facts l JOIN {S}.geo_facility g "
             "ON g.unique_id = l.unique_id WHERE l.list_slug = 'laqshya' AND l.status = 'certified, valid' "
             "AND g.stname = 'MAHARASHTRA'",
         check=lambda gt, rows, text: num_in(float(gt[0][0]), rows, text)),
    dict(q="Which Bihar districts have zero facility records?",
         sql=f"SELECT dtname FROM {S}.geo_district WHERE stname = 'BIHAR' AND records = 0 ORDER BY dtname",
         check=lambda gt, rows, text: {r[0].lower() for r in gt} <= cells(rows)
         and len(rows) == len(gt)),
    dict(q="Is there dialysis care in Madhubani district of Bihar?",
         sql=f"SELECT n_claim, n_corr FROM {S}.geo_dialysis_district WHERE nfhs_state = 'Bihar' "
             "AND nfhs_district = 'Madhubani'",
         check=lambda gt, rows, text: num_in(0.0, rows, text) and not BANNED.search(text)),
    dict(q="How many facilities in Bihar does model v2 band Likely for dialysis?",
         sql=f"SELECT COUNT(*) FROM {S}.facility_service_scores_v2 s JOIN {S}.geo_facility g "
             "ON g.unique_id = s.unique_id WHERE s.service_id = 'dialysis' AND s.band = 'LIKELY' "
             "AND g.stname = 'BIHAR'",
         check=lambda gt, rows, text: num_in(float(gt[0][0]), rows, text)),
]


def ask(question):
    m = cli("genie", "start-conversation", SPACE_ID, question)
    out = {"status": m.get("status"), "conversation_id": m.get("conversation_id"), "message_id": m.get("message_id"),
           "sql": None, "text": "", "columns": [], "rows": [], "error": m.get("error")}
    for a in m.get("attachments") or []:
        if a.get("text"):
            out["text"] += a["text"].get("content", "") + "\n"
        if a.get("query"):
            out["sql"] = a["query"].get("query")
            out["text"] += (a["query"].get("description") or "") + "\n"
            r = cli("genie", "get-message-attachment-query-result", SPACE_ID, m["conversation_id"],
                    m["message_id"], a["attachment_id"])
            sr = r.get("statement_response", {})
            out["columns"] = [c["name"] for c in sr.get("manifest", {}).get("schema", {}).get("columns", [])]
            out["rows"] = sr.get("result", {}).get("data_array", []) or []
    return out


def main():
    results = []
    for i, t in enumerate(TESTS, 1):
        _, gt = run_sql(t["sql"])
        g = ask(t["q"])
        passed = g["status"] == "COMPLETED" and bool(t["check"](gt, g["rows"], g["text"]))
        results.append({"n": i, "question": t["q"], "ground_truth_sql": t["sql"], "ground_truth": gt,
                        "genie": g, "auto_pass": passed})
        print(f"{'PASS' if passed else 'FAIL'} {i}. {t['q']}\n  truth {gt[:8]}\n  genie {g['rows'][:5]}"
              f"\n  text  {g['text'].strip()[:600]}\n  sql   {(g['sql'] or '')[:600]}\n", flush=True)
    (HERE / "test_results.json").write_text(json.dumps(results, indent=1))
    print(f"{sum(r['auto_pass'] for r in results)}/{len(results)} pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
