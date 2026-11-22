"""Re-run the auditor's checks.py with its output redirected into verify/out (the auditor's out/ is not touched)."""
import json, os, sys
A = "/Users/karthikvattem/projects/datathon/validation/claims"
sys.path.insert(0, A)
sys.dont_write_bytecode = True
import checks as C
C.OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
res = []
for f in C.CHECKS:
    try:
        r = f()
    except Exception as e:
        r = C.res(f.__name__[6:], "fail", "check crashed", "", f"{type(e).__name__}: {e}")
    res.append(r)
    print(f"[{r['status']:7}] {r['name']}: {r['metric']}", flush=True)
json.dump(res, open(os.path.join(C.OUT, "auditor_rerun.json"), "w"), indent=1, default=str)
