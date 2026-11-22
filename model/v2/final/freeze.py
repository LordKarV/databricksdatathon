"""FREEZE: predictions for the 150 sealed v3 TEST pairs from the exported scores. Reads only TEST ids (test_sample.json).

Writes model/v2/test_predictions.parquet and model/v2/test_predictions.sha256 (sha256 of the parquet bytes).
"""
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path("/Users/karthikvattem/projects/datathon")
V2 = ROOT / "model/v2"

t = pd.DataFrame(json.load(open(ROOT / "model/gold/v3/test_sample.json")))[["pair_id", "unique_id", "service"]]
assert len(t) == 150 and t.pair_id.is_unique
s = pd.read_parquet(ROOT / "derived/v2/facility_service_scores.parquet",
                    columns=["unique_id", "service_id", "p", "band", "model_version"])
out = t.rename(columns={"service": "service_id"}).merge(s, on=["unique_id", "service_id"], how="left", validate="one_to_one")
assert out.p.notna().all() and out.model_version.nunique() == 1
out.to_parquet(V2 / "test_predictions.parquet", index=False)
h = hashlib.sha256((V2 / "test_predictions.parquet").read_bytes()).hexdigest()
(V2 / "test_predictions.sha256").write_text(f"{h}  test_predictions.parquet\n")
print(h, out.band.value_counts().to_dict(), out.model_version.iloc[0])
