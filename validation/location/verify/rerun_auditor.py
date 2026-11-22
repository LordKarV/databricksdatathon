"""Re-run the auditor's checks.py functions without letting it write into its own out/ (we write here)."""
import json, sys, time
from pathlib import Path
sys.path.insert(0, "/Users/karthikvattem/projects/datathon/validation/location")
sys.dont_write_bytecode = True
import checks as C
res = []
t0 = time.time()
for f in C.ALL:
    try:
        r = f()
    except Exception as e:
        r = dict(name=f.__name__, status="fail", metric="error", detail=f"{type(e).__name__}: {e}")
    res.append(r)
    print(f"{r['status']:5} {r['name']}: {r['metric']}")
Path(__file__).parent.joinpath("out/auditor_rerun.json").write_text(json.dumps(res, indent=1, default=str))
print("secs", round(time.time() - t0, 1))
