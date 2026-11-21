# geo: shared travel time

One travel-time function for the decision layer, the planner and the app.

```python
from geo.travel import travel_minutes
rows = travel_minutes((26.45, 85.95), [(26.365, 86.08), (26.152, 85.897)])
# [{"minutes": 17, "low": 17, "high": 29, "km": 19.4, "method": "osrm", "cached": False,
#   "factor": 1.209, "kmh": 68.9, "label": "road route, free flow"}, ...]
```

`travel_minutes(origin, destinations, mode="road", timeout_s=3.0, use_osrm=True) -> list`

- Points are `(lat, lon)`. One row per destination, in order. Only `mode="road"` exists.
- `method` is `osrm` (road route) or `haversine_factor` (straight line x road factor / speed).
  `cached` is true when an `osrm` row came from disk. `factor` and `kmh` are what was used, so the
  card can name them. `label` is ready-made wording.
- Order of work: on-disk cache (sqlite, 30 days, key rounded to 4 decimals, about 11 m), then one
  OSRM table request for what is missing (3 s timeout, split above 100 points), then the estimate.
- It never raises on an OSRM or cache failure. After an OSRM failure it skips OSRM for 60 s.
- `use_osrm=False` never touches the network: use it for bulk scoring and offline packs. The OSRM
  demo server allows about 1 request per second and no bulk use.
- Standard library only. Environment: `OSRM_URL`, `TRAVEL_CACHE` (sqlite path, or `off`). The
  default cache file is `geo/data/travel_cache.sqlite`, which `.gitignore` already excludes.

`low` and `high`: for `osrm`, low is the free-flow time and high is the same road distance at
40 km/h. For `haversine_factor`, low and high are the measured 10th and 90th percentile of
OSRM time / estimate, and high is never below the 40 km/h time. **The 40 km/h slow end is an
assumption.** OSRM has no traffic data, so nothing here measures congestion.

## Files

| File | What |
|---|---|
| `travel.py` | The module |
| `test_travel.py` | 13 tests, no network: `.venv/bin/python -m pytest geo/test_travel.py -q` |
| `road_factor.json` | Constants `travel.py` reads for the estimate |
| `measure_road_factor.py` | Builds the constants. `--offline` re-runs from the cached responses |
| `out/road_factor_summary.json` | Every number below |
| `out/road_factor_pairs.csv` | The 2,420 measured pairs |
| `out/osrm_raw/` | The 242 raw OSRM responses, so a re-run sends nothing |

## Measured road factor and speed

Measured 2026-11-21 on the OSRM demo server (car profile, free flow).

Sample: 242 PIN centroids as origins in 34 states and union territories, up to 4 urban and 4 rural
per state (seed 7), each with 10 facilities at spread straight-line distances (nearest three, then
about 5, 10, 20, 35, 50, 75, 110 km). 2,420 pairs requested, all routed. 95 dropped because a point
snapped more than 2 km from a road, 163 dropped for a straight-line distance under 2 km. 2,162
pairs from 233 origins used. Confidence intervals resample whole origins.

Urban and rural are a proxy. The gazetteer has no urban flag, so a PIN is "urban" when 8 or more
other PIN centroids lie within 10 km (the national 75th percentile). It is postal density, not a
census class.

| Group | Pairs | Road factor, median (95% CI) | 10th to 90th pct | Free-flow km/h, median (95% CI) |
|---|---|---|---|---|
| All | 2,162 | 1.35 (1.33 to 1.38) | 1.14 to 2.01 | 65.1 (63.6 to 66.7) |
| Urban origin | 973 | 1.29 (1.28 to 1.32) | 1.12 to 1.78 | 62.2 (60.5 to 63.8) |
| Rural origin | 1,189 | 1.42 (1.36 to 1.46) | 1.17 to 2.20 | 67.4 (65.1 to 69.1) |
| 2 to 10 km | 344 | 1.35 (1.31 to 1.38) | 1.14 to 1.72 | 50.0 (47.6 to 51.7) |
| 10 to 25 km | 349 | 1.29 (1.26 to 1.33) | 1.14 to 1.90 | 58.2 (55.4 to 61.0) |
| 25 to 50 km | 529 | 1.33 (1.30 to 1.36) | 1.13 to 1.96 | 64.9 (62.8 to 67.8) |
| 50 to 100 km | 630 | 1.40 (1.34 to 1.48) | 1.16 to 2.13 | 72.1 (70.1 to 73.6) |
| 100 to 150 km | 310 | 1.41 (1.33 to 1.46) | 1.16 to 2.16 | 73.6 (70.8 to 75.8) |

The sample gives every state equal weight. Reweighted by each state's share of facility records,
the median factor is 1.29 and the median speed 64.1 km/h.

State medians run from 1.20 (Andhra Pradesh) to 2.38 (Arunachal Pradesh, 20 pairs). Hill states
are far above the national figure: Sikkim 2.19, Himachal Pradesh 1.97, Uttarakhand 1.95,
Nagaland 1.88, Manipur 1.64.

## Reconciling the two earlier figures

Median of (assumed minutes / OSRM minutes) on the 2,162 pairs:

| Assumption | Median ratio | Mean abs. pct. error |
|---|---|---|
| Spec: 1.3 at 40 km/h | 1.50 | 53% |
| Spec: 1.3 at 25 km/h | 2.40 | 137% |
| Feasibility: 1.26 at 69.4 km/h | 0.84 | 23% |
| Feasibility: 1.26 at 40 km/h | 1.45 | 49% |

- The spec's factor of 1.3 was close. Its speeds were not: 40 to 25 km/h gives 1.5 to 2.4 times the
  OSRM free-flow time.
- The feasibility figure (1.26 at 69 km/h, 50 rural Bihar pairs) is 16% too fast nationally. Bihar
  is flat, and its pairs were mostly 20 to 80 km where speeds are highest.

## What the fallback uses

Speed rises with distance (50 km/h under 10 km, 74 km/h past 100 km), so one constant pair is the
wrong shape. The fallback interpolates factor and speed between the five distance-band medians
(held flat below 5.5 km and above 110 km; beyond 150 km is extrapolation).

Error of minutes = straight km x factor / speed against OSRM, constants fitted without the
held-out origin:

| Constants | Median abs. pct. error | 90th pct | Within 20% |
|---|---|---|---|
| One national pair (1.35, 65.1) | 19% | 45% | 52% |
| By urban / rural | 20% | 46% | 51% |
| By distance band (shipped) | 17% | 44% | 58% |
| By state | 16% | 44% | 59% |

Ratio of OSRM minutes to the shipped estimate (in sample):

| Group | Median | 10th to 90th pct | Median abs. pct. error | 90th pct |
|---|---|---|---|---|
| All | 1.03 | 0.79 to 1.64 | 17% | 43% |
| Urban origin | 0.98 | 0.76 to 1.48 | 17% | 40% |
| Rural origin | 1.08 | 0.83 to 1.84 | 17% | 47% |

Splitting by urban / rural did not help, so the fallback does not use it. For a single headline
figure use **1.35 at 65 km/h free flow**, and say "free flow".

## Limits

- The estimate is off by more than 44% for one pair in ten, and it is too fast in hill states
  (the true road factor there is about 1.6 to 2.4). A per-state factor is about as accurate as the
  distance bands overall; combining the two was not tried. `travel_minutes` takes no state, so
  this would need a signature change.
- Free flow only. Real times in cities and on bad roads are longer; the 40 km/h slow end is an
  assumption with no measurement behind it.
- Pairs under 2 km and over 150 km were not measured.
- Origins are PIN centroids, not villages. 95 pairs were dropped for snapping more than 2 km from
  a road, so places far from any mapped road are under-represented.
- Not run: no comparison against a second routing source, no check against real journey times.
