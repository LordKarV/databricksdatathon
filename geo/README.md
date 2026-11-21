# geo: shared travel time

One travel-time function for the decision layer, the planner and the app.

```python
from geo.travel import travel_minutes
rows = travel_minutes((26.45, 85.95), [(26.365, 86.08), (26.152, 85.897)])
# [{"minutes": 17, "low": 17, "high": 29, "km": 19.4, "method": "osrm", "cached": False,
#   "factor": 1.209, "kmh": 68.9, "terrain": None, "label": "road route, free flow, no traffic data"}, ...]
```

`travel_minutes(origin, destinations, mode="road", timeout_s=3.0, use_osrm=True, state=None, area=None) -> list`

- Points are `(lat, lon)`. One row per destination, in order. Only `mode="road"` exists.
- `method` is `osrm` (road route) or `haversine_factor` (straight line x road factor / speed).
  `cached` is true when an `osrm` row came from disk. `factor` and `kmh` are what was used, so the
  card can name them. `label` is ready-made wording.
- `state` (optional): state or union territory of the origin, any case. The nine hill states below
  get their own factor, speed and range. Without it the plain constants are used, which are 49% too
  fast there. `terrain` in the row says which constants an estimate used.
- `area` (optional): `"urban"` or `"rural"` origin. It only changes the range, and only slightly.
- Order of work: on-disk cache (sqlite, 30 days, key rounded to 4 decimals, about 11 m), then one
  OSRM table request for what is missing (3 s timeout, split above 100 points), then the estimate.
- It never raises on an OSRM or cache failure. After an OSRM failure it skips OSRM for 60 s.
- `use_osrm=False` never touches the network: use it for bulk scoring and offline packs. The OSRM
  demo server allows about 1 request per second and no bulk use.
- Standard library only. Environment: `OSRM_URL`, `TRAVEL_CACHE` (sqlite path, or `off`). The
  default cache file is `geo/data/travel_cache.sqlite`, which `.gitignore` already excludes.

`low` and `high`:
- `haversine_factor`: the measured 10th and 90th percentile of (OSRM minutes / estimate) for that
  terrain, distance band and area. On held-out origins 78 to 79% of road routes fall inside
  (target 80%), and about 1 in 9 is above `high`.
- `osrm`: low = high = minutes. It is one free-flow route. OSRM has no traffic data and nothing
  here measures how much slower a real journey is, so no spread is claimed. The label says
  "free flow, no traffic data".

## Files

| File | What |
|---|---|
| `travel.py` | The module |
| `test_travel.py` | 19 tests, no network: `.venv/bin/python -m pytest geo/test_travel.py -q` |
| `road_factor.json` | Constants `travel.py` reads for the estimate (version 2: per terrain class) |
| `measure_road_factor.py` | Sends the OSRM requests. `--offline` re-runs from the cached responses |
| `fit_travel_constants.py` | Fits the constants from the pairs (run from `geo/`, no network) |
| `out/road_factor_summary.json` | National numbers below (balanced core sample) |
| `out/travel_constants_summary.json` | Terrain, range and held-out numbers below |
| `out/road_factor_pairs.csv` | The 3,790 measured pairs; `core` marks the balanced national sample |
| `out/osrm_raw/` | The 379 raw OSRM responses, so a re-run sends nothing |

## Measured road factor and speed (national, balanced sample)

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

## Terrain: hill states

137 more origins were measured in 12 candidate states (the Himalayan states and the North East,
up to 12 urban and 12 rural origins each), 379 origins and 3,790 pairs in all, 3,335 usable.
A candidate is "hill" when its median road factor is 1.5 or more. The cut was chosen after seeing
the data, so check the table, not the cut.

| State | Pairs | Origins | Road factor, median (95% CI) | Free-flow km/h | Class |
|---|---|---|---|---|---|
| Sikkim | 110 | 11 | 2.11 (2.03 to 2.28) | 67.9 | hill |
| Arunachal Pradesh | 70 | 7 | 2.11 (1.93 to 2.44) | 75.5 | hill |
| Uttarakhand | 219 | 24 | 1.94 (1.46 to 2.10) | 56.2 | hill |
| Mizoram | 120 | 12 | 1.90 (1.48 to 2.66) | 78.3 | hill |
| Nagaland | 109 | 11 | 1.82 (1.64 to 1.99) | 74.8 | hill |
| Himachal Pradesh | 238 | 24 | 1.78 (1.65 to 1.95) | 51.1 | hill |
| Ladakh | 20 | 2 | 1.61 (2 origins: no usable interval) | 65.2 | hill |
| Meghalaya | 176 | 22 | 1.56 (1.48 to 1.66) | 67.6 | hill |
| Manipur | 160 | 16 | 1.52 (1.39 to 1.73) | 66.3 | hill |
| Jammu and Kashmir | 195 | 20 | 1.42 (1.30 to 1.56) | 61.2 | plain |
| Tripura | 204 | 23 | 1.39 (1.32 to 1.55) | 78.4 | plain |
| Assam | 223 | 23 | 1.32 (1.29 to 1.43) | 72.7 | plain |

| Class | Pairs | Origins | States | Road factor, median (95% CI) | Free-flow km/h (95% CI) |
|---|---|---|---|---|---|
| plain | 1,707 | 185 | 25 | 1.30 (1.28 to 1.32) | 65.0 (63.2 to 66.6) |
| hill | 1,222 | 129 | 9 | 1.79 (1.68 to 1.88) | 64.4 (61.4 to 67.3) |

Plain is the balanced core sample without the nine hill states. Hill-state pairs scored with the
plain constants come out 49% too fast (median OSRM / estimate 1.49); with the hill constants the
median ratio is 1.07 on held-out origins.

## What the estimate uses

Per terrain class, factor and speed are interpolated between five distance-band medians (held flat
below about 5 km and above 110 km; beyond 150 km is extrapolation).

| Class | Band | Pairs | Factor | km/h | OSRM / estimate, 10th to 90th pct |
|---|---|---|---|---|---|
| plain | 2 to 10 km | 290 | 1.34 | 49.1 | 0.75 to 1.57 |
| plain | 10 to 25 km | 310 | 1.27 | 57.8 | 0.75 to 1.35 |
| plain | 25 to 50 km | 443 | 1.30 | 65.8 | 0.82 to 1.34 |
| plain | 50 to 100 km | 457 | 1.30 | 72.5 | 0.85 to 1.32 |
| plain | 100 to 150 km | 207 | 1.29 | 73.6 | 0.84 to 1.46 |
| hill | 2 to 10 km | 137 | 1.45 | 52.1 | 0.72 to 1.60 |
| hill | 10 to 25 km | 138 | 1.77 | 57.1 | 0.60 to 2.30 |
| hill | 25 to 50 km | 255 | 1.79 | 60.4 | 0.68 to 1.88 |
| hill | 50 to 100 km | 445 | 1.86 | 70.2 | 0.68 to 1.81 |
| hill | 100 to 150 km | 247 | 1.88 | 74.6 | 0.69 to 1.67 |

Urban and rural percentiles are stored per band where at least 30 pairs were measured
(`ratio_by_area` in `road_factor.json`) and used when `area` is passed.

Held out by origin (10 folds), estimate against OSRM:

| Class | Origin | Pairs | Median abs. pct. error | 90th pct | Inside low to high | Above high |
|---|---|---|---|---|---|---|
| plain | all | 1,707 | 14% | 36% | 79% | 10% |
| plain | urban | 828 | 15% | 37% | 78% | 9% |
| plain | rural | 879 | 14% | 34% | 81% | 12% |
| hill | all | 1,222 | 27% | 54% | 78% | 11% |
| hill | urban | 355 | 28% | 56% | 82% | 6% |
| hill | rural | 867 | 27% | 53% | 76% | 14% |

Passing `area` moves coverage by about a point either way (plain urban 78%, rural 78%; hill urban
79%, rural 77%), so it is optional and not worth a lookup on its own.

For a single headline figure use **1.35 at 65 km/h free flow** nationally, or 1.30 for the plains
and 1.79 for the hill states.

## Limits

- The range is the spread of OSRM free-flow routes around the estimate. It is not a range for real
  journeys: there is no traffic, weather, road-condition or night-time data here. The earlier
  40 km/h slow end was an assumption and has been removed, not replaced by a measurement.
- OSRM free flow looks optimistic on mountain roads: its median speed in the hill states is
  64 km/h, the same as the plains, and a live route from Gangtok towards Darjeeling (38 km straight line,
  76 km by road) came back as 63 minutes. Hill times from either method should be shown as "at least".
- Terrain is by state. Hill districts of plain states (Darjeeling, the Western Ghats, hill
  districts of Jammu and Kashmir and Assam) use the plain constants, and valley towns in hill
  states use the hill ones. Ladakh rests on 2 origins.
- The hill class was chosen with a cut picked after seeing the data, from 12 candidates.
- Pairs under 2 km and over 150 km were not measured.
- Origins are PIN centroids, not villages. Pairs snapping more than 2 km from a road were dropped,
  so places far from any mapped road are under-represented.
- Not run: no comparison against a second routing source, no check against real journey times.
