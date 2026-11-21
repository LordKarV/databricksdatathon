# Referral Saathi app skeleton

FastAPI serving one plain HTML page, a service worker and stub JSON (issue #5). No model and no Databricks reads
yet: every answer is invented sample data, labelled "(sample)" and `meta.stub = true`.

## Run locally

```
python3 -m venv .venv-app
.venv-app/bin/pip install fastapi==0.115.14 uvicorn pytest httpx playwright axe-playwright-python
cd app && ../.venv-app/bin/python main.py   # or: ../.venv-app/bin/uvicorn app:app --reload
```

Open http://127.0.0.1:8000/. Chrome DevTools > Sensors can fake a GPS point.

## Files

| Path | What |
| --- | --- |
| `app.py` | FastAPI: `/`, shell files (allowlist), `/api/ping`, `POST /api/plan`, dev alias `GET /api/recommend` |
| `main.py` | Entry point: uvicorn on `DATABRICKS_APP_PORT` (default 8000), access log off |
| `stub_data.py` | Placeholder responses in the proposed contract shape; the lead replaces `recommend_stub` |
| `app.yaml` | Databricks Apps command: `python main.py` |
| `static/index.html`, `app.js`, `app.css` | One page, hash routes, no framework |
| `static/sw.js` | Network first; cached shell on network error or status >= 500; API never cached |
| `tests/test_api.py` | Contract and input-validation tests |
| `checks/a11y_check.py` | axe-core 4.x over 10 states x light/dark at 360 px, screenshots, page weight |

Screens: start (GPS default, change location, 8 tiles, 108 line, danger checklist), GPS searching, change location,
results (Quick depth), abstention (S3x), why / how / call-ahead (S4, S5, S6 on one page), offline banner.

## `POST /api/plan` contract

`POST /api/plan` with a JSON body:

```
{"service": "dialysis", "lat": 26.6, "lon": 85.48, "accuracy_m": 40, "source": "gps", "depth": "quick"}
```

`service` is one of `emergency_csection, nicu, trauma_emergency, burn_care, dialysis, mri, cardiac_surgery`;
`source` is `gps | last_fix | pin | district | manual`; `depth` is `quick | compare | area`. The point goes in the
body because query strings can land in proxy logs we do not control. The server rounds lat/lon to 0.01 degree
before use. Unknown keys, unknown fields and points outside India return 422.
`GET /api/recommend?<same fields>` is a dev alias for curl checks; the page never calls it.

Response:

```
{
  "query": {"service": "dialysis", "service_label": {"en": "...", "hi": "..."}},
  "location": {"lat": 26.6, "lon": 85.48, "accuracy_m": 40, "source": "gps", "rounded_to_deg": 0.01},
  "as_of": "2026-11-21",
  "profile": "emergency | urgent | scheduled | planned",
  "emergency_numbers": [{"number": "108", "label": "..."}],
  "abstain": null | {"text": "...", "outside_option": {"facility_id", "name", "operator", "text", "travel"}},
  "options": [{
    "rank": 1, "facility_id": "<unique_id>", "name": "...", "town": "...", "district": "...", "state": "...",
    "address": "...", "operator": "private | public | unknown", "lat": 0.0, "lon": 0.0,
    "travel": {"minutes", "low", "high", "km", "method": "osrm | haversine_factor",
               "cached", "factor", "kmh", "terrain", "label"},
    "band": "likely | not_verified | unlikely", "band_word": "Likely", "band_reason": null | "...",
    "p": 0.81, "p_lo": 0.70, "p_hi": 0.89,
    "p_e": 0.97, "p_l": 0.95,   // MODEL: P(facility exists), P(map point is right); Compare depth (S10)
    "evidence": [{"claim_id", "field", "quote", "source_url"}],
    "contributions": [{"label", "points"}],
    "flags": ["plain-English warning", ...],
    "call_ahead": [{"question", "asked_because"}],
    "call_first": true,
    "track_record": {"n", "k_confirmed", "k_contradicted", "k_no_info", "split": "dev | test"},
    "phone": {"e164": null | "+91...", "display", "shared_listings"},
    "is_real": ["..."], "where_check": "...", "why_first_text": null | "...",
    "say_to_family": {"en": "...", "hi": null | "..."}
  }],
  "why_not": [{"facility_id", "name", "travel", "reason"}],
  "meta": {"stub": true, "model_hash": "...", "data_snapshot": "...", "generated_at": "..."}
}
```

### `POST /api/area` (Area depth, S11/S12; stub until #11)

Body `{service, lat, lon}` (0.01 deg). Every number below is MODEL-supplied (area_metrics and ten-call lists, tier 3);
the stub returns invented sample values.

```
{
  "query": {"service", "service_label": {"en", "hi"}},
  "area": {"district", "state", "window_min": 60},
  "as_of": "YYYY-MM-DD",
  "summary": {"n_pins", "n_without_option", "access_now", "access_if_confirmed",
              "calls_could_close", "no_public_evidence"},          // MODEL: shares of the area, 0..1
  "caveat": "Low web presence looks like a gap. Verify before deciding.",
  "pins": [{"pin", "lat", "lon", "first": null | {"facility_id", "name"}, "backup": null | {...},
            "travel": null | {"low", "high"}, "call_first": null | "name", "nearest_km": null | 96.0}],
  "ten_calls": [{"rank", "facility_id", "name", "phone_kind", "areas", "access_gain"}],   // MODEL
  "meta": {"stub", "model_hash"}
}
```

The page reads only these fields. `travel` is one row of `geo/travel.py` (#7, PR #13) passed through unchanged;
the stub calls `geo.travel.estimate` (measured factor and percentile range, no OSRM call) and falls back to
straight-line x 1.35 only if `geo/` is not importable.

## Not done here

PIN/place lookup (`/api/resolve`), note scan,
free-text mapping, read aloud, outcome storage, the in-browser faithfulness
recompute (spec 5.4), Hindi UI strings beyond the tile labels (#10), and a test on a real phone or behind the
Databricks Apps proxy (#4).

## Offline pack storage

The service worker keeps each saved state pack in IndexedDB (`rs-packs` database, `packs` store, keyed by slug:
`{body, sha256, built, saved_at}`); the pack format is unchanged and `/api/pack/<slug>` is answered from there when
the network fails. Packs saved before #32 in Cache Storage (`rs-packs-v1`) move over on activate. After the first
save the page calls `navigator.storage.persist()` once and records the answer in `localStorage['rs.pack'].persisted`.
