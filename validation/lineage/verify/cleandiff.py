"""Compare cleaning tables rebuilt from data/raw in a scratch copy with the published derived/v1 copies."""
import hashlib, json, sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tablediff import frame_diff

V1 = Path("/Users/karthikvattem/projects/datathon/derived/v1")
SRC = {"pin_gazetteer": "geo_identity", "facility_location": "geo_identity", "place_gazetteer": "geo_identity",
       "record_trust": "geo_identity", "facility_groups": "geo_identity", "claims": "claims/out",
       "specialties": "claims/out", "grades": "claims/out", "grades_v1": "claims/out"}

if __name__ == "__main__":
    scratch = Path(sys.argv[1])
    res = {}
    for t, d in SRC.items():
        a, b = V1 / f"{t}.parquet", scratch / d / f"{t}.parquet"
        if not b.exists():
            res[t] = "not rebuilt"
            continue
        e = {"byte_identical": hashlib.sha256(a.read_bytes()).digest() == hashlib.sha256(b.read_bytes()).digest()}
        if not e["byte_identical"]:
            x, y = pd.read_parquet(a), pd.read_parquet(b)
            e.update(frame_diff(x, y))
            if e.get("shape_or_cols_differ") is None and not e["nonfloat_cols_differ"] and e["cells_differ"] == 0:
                e["note"] = "content equal, bytes differ (parquet metadata)"
        res[t] = e
    print(json.dumps(res, indent=1, default=str))
