"""Re-run the auditor's checks.py with its OUT redirected into verify/rerun_out (no writes to the auditor's out/)."""
import importlib.util, json, sys, time
from pathlib import Path
here = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("rl_checks", here.parent / "checks.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.OUT = here / "rerun_out"
res = m.run_all()
