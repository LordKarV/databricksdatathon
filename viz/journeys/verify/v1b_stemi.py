"""Why STEMI never gets a stop: how many best plans have PCI travel beyond the 120 min gate, and how many Bihar/UP/MH
records have a thrombolysis stage p >= 0.05 under the stub."""
import gzip
import json
import sys
from pathlib import Path

R = Path("/Users/karthikvattem/projects/datathon")
sys.path.insert(0, str(R))
from planner.data_v1 import V1Store  # noqa: E402

raw = json.load(gzip.open(R / "viz/journeys/data/plans_raw.json.gz", "rt"))["runs"]
st = [x for x in raw if x["pathway"] == "stemi" and not x["result"]["abstain"]]
over = [x for x in st if x["result"]["plans"][0]["stops"][-1]["leg"]["minutes"] > 120]
print("STEMI planned", len(st), "best plan PCI leg > 120 min:", len(over))
print("dropped stop plans (below margin), total:", sum((x["result"].get("considered") or {}).get("stop_plans_dropped_below_margin") or 0 for x in st))
s = V1Store(v1=R / "derived/v1", caps_path=R / "kb/pathways/capabilities.json")
fac = s.facilities()
n = sum(1 for f in fac if s.capability_p(f["id"], "thrombolysis")[0] > 0.02)
print("records with any thrombolysis evidence:", n, "of", len(fac))
