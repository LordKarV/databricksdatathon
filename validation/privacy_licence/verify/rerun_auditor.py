"""Re-run the auditor's checks.py with its outputs redirected into verify/rerun_out (the auditor's out/ is untouched)."""
import importlib.util, json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("pl_checks", HERE.parent / "checks.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.OUT = HERE / ("rerun_out_" + sys.argv[1] if len(sys.argv) > 1 else "rerun_out")
res = []
for fn in m.CHECKS:
    try:
        r = fn()
    except Exception as e:
        r = m.result(fn.__name__[6:], "fail", "not run", "", f"{type(e).__name__}: {e}", [])
    print(json.dumps(r, ensure_ascii=True)[:1200], flush=True)
    res.append(r)
(m.OUT / "results.json").write_text(json.dumps(res, indent=1, ensure_ascii=True))
