"""Ask the Genie space 3 planner questions it was not tested on (not in its examples or test_space.py) and
print Genie's rows and text next to our own SQL. Judged by reading the output, recorded in VERIFY.md.
Run: DATABRICKS_CONFIG_PROFILE=vf .venv/bin/python databricks/verify/verify_genie.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "genie"))
from space import S, cli, run_sql  # noqa: E402
from test_space import SPACE_ID, ask  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "build" / "databricks_staging" / "independent_genie.json"
TESTS = [
    ("Which three states have the most facilities on the e-RaktKosh blood bank list?",
     f"SELECT g.stname, COUNT(DISTINCT l.unique_id) n FROM {S}.facility_list_facts l JOIN {S}.geo_facility g "
     "ON g.unique_id = l.unique_id WHERE l.list_slug = 'eraktkosh' GROUP BY g.stname ORDER BY n DESC LIMIT 3"),
    ("In Kerala, how many facility records claim emergency C-section, and how many of those are confirmed "
     "by a second source?",
     f"SELECT SUM(CASE WHEN csection_claimed THEN 1 ELSE 0 END), "
     f"SUM(CASE WHEN csection_claimed AND csection_corroborated THEN 1 ELSE 0 END) "
     f"FROM {S}.geo_facility WHERE stname = 'KERALA'"),
    ("Which district in Odisha with no confirmed dialysis facility has the largest population?",
     f"SELECT nfhs_district, ROUND(pop / 1e6, 2), n_claim, n_corr FROM {S}.geo_dialysis_district "
     "WHERE lower(nfhs_state) = 'odisha' AND n_corr = 0 ORDER BY pop DESC LIMIT 3"),
]


def main() -> None:
    out = []
    for q, truth_sql in TESTS:
        _, truth = run_sql(truth_sql)
        g = ask(q)
        out.append({"q": q, "truth_sql": truth_sql, "truth": truth, "genie": g})
        print(f"Q: {q}\n  truth: {truth}\n  genie status={g['status']} rows={g['rows'][:5]}\n"
              f"  genie sql: {g['sql']}\n  genie text: {g['text'].strip()[:900]}\n")
    OUT.write_text(json.dumps({"space_id": SPACE_ID, "tests": out}, indent=1, default=str))


if __name__ == "__main__":
    main()
