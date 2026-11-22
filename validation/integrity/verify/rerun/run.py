"""Run every check_* in checks.py (or the ones named on the command line); write outputs/results.json.

Usage: .venv-viz/bin/python validation/integrity/run.py [check_name ...]
"""
import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import checks  # noqa: E402
from common import OUT  # noqa: E402

names = sys.argv[1:] or [n for n in dir(checks) if n.startswith("check_")]
OUT.mkdir(exist_ok=True)
out_file = OUT / ("results.json" if not sys.argv[1:] else "results_partial.json")
results = []
for n in names:
    fn = getattr(checks, n if n.startswith("check_") else "check_" + n)
    t0 = time.time()
    try:
        r = fn()
    except Exception as e:  # a crashing check is reported as a failure, never dropped
        r = {"name": n, "status": "fail", "metric": "error", "threshold": None,
             "detail": f"{type(e).__name__}: {e}", "examples": traceback.format_exc().splitlines()[-4:]}
    r["seconds"] = round(time.time() - t0, 1)
    results.append(r)
    print(f"[{r['status']:4}] {r['name']}: {r['metric']} ({r['seconds']} s)", flush=True)
    for x in r.get("examples", [])[:4]:
        print("        ", str(x)[:220])
out_file.write_text(json.dumps(results, indent=1, default=str))
print("wrote", out_file)
