"""Print random samples of the city-vs-PIN matcher for hand checking (verdicts in FINDINGS.md)."""
import pandas as pd

g = pd.read_parquet("/Users/karthikvattem/projects/datathon/audit/geo/facility_geo.parquet")
c = pd.read_parquet("/Users/karthikvattem/projects/datathon/audit/geo/pin_centroids.parquet").set_index("pincode")
for flag, seed in [(True, 21), (False, 22)]:
    s = g[g.pin_in_dir & (g.city_match_pin == flag)].sample(20, random_state=seed)
    print(f"--- city_match_pin={flag}")
    for r in s.itertuples():
        x = c.loc[r.pin]
        print(f"{r.unique_id[:8]} city={r.address_city!r:24} pin={int(r.pin)} {x.state}/{x.district} d_pin={r.d_pin_km:.0f} offices={list(x.offices)[:3]}")
