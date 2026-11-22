"""Story 4: with the wider snakebite wording (17 records), how many sampled origins would have a mention within the
planner's 150 km straight-line radius? Origins from data/plans_raw.json.gz."""
import gzip
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.stats.proportion import proportion_confint

R = Path("/Users/karthikvattem/projects/datathon")
sys.path.insert(0, str(R / "viz/journeys/scripts"))
from s4_snakebite import snake_mentions  # noqa: E402  (pattern only; counts were checked by hand in v4b_loose.log)

ids = snake_mentions()
f = pd.read_parquet(R / "derived/v1/facility_location.parquet", columns=["unique_id", "loc_lat", "loc_lon"]).dropna()
f = f[f.unique_id.isin(ids)]
print("wide mentions with coordinates:", len(f), "of", len(ids))
raw = json.load(gzip.open(R / "viz/journeys/data/plans_raw.json.gz", "rt"))["runs"]
org = pd.DataFrame([x["origin"] for x in raw if x["pathway"] == "snakebite"])
la1, lo1 = np.radians(org.lat.values)[:, None], np.radians(org.lon.values)[:, None]
la2, lo2 = np.radians(f.loc_lat.values)[None], np.radians(f.loc_lon.values)[None]
h = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
km = 2 * 6371 * np.arcsin(np.sqrt(h)).min(axis=1)
for s, g in org.assign(km=km).groupby("origin_set"):
    k = int((g.km <= 150).sum())
    lo, hi = proportion_confint(k, len(g), method="wilson")
    print(f"{s}: {k} of {len(g)} within 150 km ({100*k/len(g):.0f}%, {100*lo:.0f} to {100*hi:.0f}); median nearest {g.km.median():.0f} km")
