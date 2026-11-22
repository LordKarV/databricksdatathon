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

## Live website check (`POST /api/verify`, #37)

Body `{facility_id, service_id}`. The server fetches the facility's official website and looks for the service.
- It reads up to 4 pages: the home page, then links about the service, departments, contact or emergency.
- It is polite: robots.txt is honoured, at most 1 request per second per domain, 8 s total, User-Agent `datathon-facility-check/0.1`. Only http(s) is fetched, on the first URL and on every redirect (at most 5 redirects). Each hop resolves its host once, every address must be global, and the socket connects to that checked address, so there is no second DNS lookup. TLS keeps the hostname for SNI and certificate checks.
- Matching uses the claims lexicon. Sentences that say the service is not offered here and now (negation, referral, future, past, camp) never count as found.

Returns:
```
{"facility_id", "service_id", "status": "found | not_mentioned | unreachable | wrong_site | no_website",
 "status_text", "quotes": [{"text", "url", "says": "yes | no"}],   // at most 2, verbatim
 "pages_checked": [...], "checked_at", "checked_at_ms", "cached", "note"}
```
- Results are cached in memory for 24 h. The cache holds quotes and URLs only; page bodies are dropped after matching.
- The why page shows the result as a dated line, and it never changes the band.
- The endpoint returns 503 until the inputs are built:
  `.venv-app/bin/python app/verify/build_sites.py` writes `app/verify/out/` (git-ignored, about 350 KB, from `derived/v1/source_urls.parquet` and `cleaning/claims/lexicon.py`).
- Tests replay recorded pages from `app/verify/fixtures/` and make no network calls.

## Real data behind the contract (#42)

`/api/plan`, `/api/area` and the slip read real facilities from `derived/v1` (the stub in `stub_data.py` is
now a test fixture only).
- **Build:** `.venv-app/bin/python app/facts/build.py` writes `app/facts/out/facts.json.gz` (git-ignored, about
  1.4 MB, under a second). It holds 9,947 facilities, 8,012 facility-service pairs, the 13,829 cited claims,
  the PIN gazetteer and the evidence-rule hand-check counts, all copied unchanged.
- **Runtime:** the app loads that file once at start-up using only the standard library. Until it is built,
  both endpoints return 503.
- **Measured locally:** start-up to first response 0.31 s, process RSS 108 MB. Plan requests take 1.5-2.6 ms
  and area requests 12-20 ms (p50 over HTTP).
- **Candidates:** pairs the claims lexicon found (`grades` + `data_point_scores`) within 150 km straight line.
  The nearest 40 get a `geo/travel.py` estimate. Ranking is p x exp(-minutes / scale), where the scale is
  45 / 60 / 120 / 240 min by urgency, for every band: a confirmed listing far away does not outrank a nearer one
  by default, but the best Likely option in reach always takes the last slot if it did not make the list.
- **Scores:** everything model-like is in `Engine.score(facility_id, service_id) -> (band, p, lo, hi,
  contributions, evidence_ids)`.
  - Interim: Likely only for pairs verified true by a second source. Unlikely when verified false or graded
    attributed-elsewhere / counter-evidence; such pairs are never offered as options. Everything else is Not
    verified.
  - p, lo and hi are `data_point_scores` score / score_lo / score_hi. The contributions split that stored score
    in log-odds x 10 (evidence rule, then sources, then the second-source check), so the total maps back to p.
  - When `derived/v2/facility_service_scores.parquet` exists, `build.py` exports its band / p / lo / hi and
    `score()` uses them; nothing else changes.
- **Evidence:** verbatim `claims.text` with claim ids, at most 3. Sentences with a non-offer cue or attributed
  to another facility are left out; the latter are shown as "Ignored: ..." flags.
- **Flags and checks:** flags come from `record_trust.trust_reasons` (already plain English) and the grade's
  risk columns. `where_check` comes from the location rule, and `track_record` from the evidence rule's
  hand-check and gold-dev counts.
- **Abstention:** when no option is Likely (the common case until the model publishes), the response abstains
  and lists the Not verified options to call. The outside option is the nearest district hospital or medical
  college by name, within 150 km.
- **Known gaps:**
  - `operator` is "unknown" for every option: derived/v1 has no public/private field, and the spec allows
    "public" only when a field says so.
  - Quotes link to the record's best source URL (official home page first), not a per-sentence page.

## How this works page (`#/how`, #45)

A plain-language global HOW for judges and planners, reached from the header link. The sections are: the data
problem, what was fixed / flagged / could not be fixed, how a recommendation is made, how good it is (including
what did not work), sources and licences, and limits.

- **No hand-typed numbers.** `.venv-app/bin/python app/howto/build.py` writes `app/howto/out/how.json`
  (git-ignored, about 20 KB) after `app/facts/build.py`.
  - Counts are computed from `derived/v1`, the facts export and `kb/pathways`.
  - Ranking constants are read from `app/facts/engine.py`.
  - Tables and the "did not work" list are copied verbatim from `REPORT.md`, `model/MODEL_SPEC.md` and
    `research/DATASETS.md`, found by heading. A missing heading or table fails the build.
  - Every entry names its source file. When #11 lands, point `EVAL` in the build at its results file.
- **Served by** `GET /api/how` (503 until built). The renderer `how.js` loads only on this route, so it is
  never on the critical path.
- **Tested:** the faithfulness test checks every number and table cell on the page against how.json, requires
  every fact and cell to be shown, and requires every source link to point at a file that exists in the repo.

## Multi-stop route (`itinerary` in `/api/plan`, #47)

For services with a care pathway (`kb/pathways/care_pathways.json`: trauma, emergency C-section, burns, sick
newborn, dialysis start), `/api/plan` adds `itinerary`. It holds the planner's routes (`planner/`, tm-Art4v):
where to go and in what order. The single-destination `options` are unchanged and stay the list of whom to
call. MRI and cardiac surgery have no pathway and return `itinerary: null`.

- **Source and fallback.** `app/itinerary.py` calls `planner.service.plan_for_service`. It returns null if
  the planner is not shipped, if `planner/out` is not built (`RuntimeError`), or if there is no pathway.
  The page then shows the options alone.
- **What the module adds.** It only reshapes the planner's output and joins the app's own facts: phone,
  place, and up to 2 verbatim own-offer sentences per stop (claim ids from the planner; text from the
  facts export). It never changes an order, a time or a probability.
- **Swap point.** `capability_p` inside `planner.service` remains the single swap point for the model (#11).
- **Shape.**
  ```
  {pathway, pathway_name, urgency, abstain: text|null,
   plans: [{rank, type, type_word,
            stops: [{facility_id, name, place, purpose, purpose_word, eta_low, eta_high, dwell_minutes, p,
                     weakest_capability, weakest_capability_p, question, evidence: [{claim_id, quote}],
                     n_evidence, phone, fallback: {facility_id, name, eta_minutes, p}|null, flags}],
            totals: {minutes_to_definitive, low, high, p_first_care, p_treated},
            window_checks: [{check, limit_minutes, eta_minutes, met}],
            vs_direct: {direct_name, direct_minutes, direct_p_objective, plan_p_objective,
                        direct_p_first_care, plan_p_first_care}|null}],
   meta: {stub, origin_state, terrain, plans_considered}}
  ```
- **Results screen.** A "Suggested route" card shows route 1 as numbered stops. Stages at the same hospital
  (dialysis: assessment, fistula, sessions) nest under it. The other routes sit in expandable sections.
- **Slip.** The slip and the WhatsApp text list route 1's stops, with phone and arrival range.
- **Comparison against going direct.** The page builds this sentence from the structured fields, so every
  number in it is marked and checked.
- **Build order.** Run `planner/export_v1.py` before `app/facts/build.py`, because the facts export copies
  the claims the planner cites (about 45k claims, 2.1 MB gz in total). `tools/deploy/deploy.sh` runs them
  in that order.
- **Tests.**
  - The faithfulness test checks every route value on the results screen and the slip. Two new kinds:
    `dur` (minutes shown as min, h or days) and `met`.
  - `test_every_route_field_is_shown` fails when an itinerary field is neither rendered nor listed in
    `ROUTE_NOT_SHOWN`.
  - `test_engine.py` checks latency, size and verbatim quotes, that the options are unchanged, and the
    null fallbacks.

## Free text, referral-note photo and read aloud (#64)

- **Describe it in your words** (`#/describe`, also the "Other / not sure" tile). The browser runs the danger
  words first, then the lexicon, so both work offline.
  - A danger hit shows Call 108 at once. It never maps to MRI or heart surgery: chest pain is not a planned
    service.
  - Only when neither finds anything is the text sent to `POST /api/parse`. The server repeats the same steps,
    then calls the text model:
    - `SERVING_ENDPOINT_TEXT`, temperature 0, strict JSON;
    - its `decisive_phrase` must appear verbatim in the input, or the answer is dropped.
  - Every suggestion ends at a confirm card that quotes the deciding words. Nothing searches until the user taps
    "Yes, that is right".
- **Scan referral note** (`#/note`).
  - A consent card comes first.
  - The photo is re-encoded in the browser (1024 px JPEG; EXIF dropped) and sent once to `POST /api/read-note`.
  - That calls `SERVING_ENDPOINT_VISION`. The guard from `app_design/feasibility/vision/score.py` marks the
    answer "sure" only if:
    - the trigger phrase is verbatim in the detected text;
    - the lexicon or clinical terms agree;
    - no line reads like an instruction to an AI.
  - Otherwise the card says "We are not sure". The image is not stored or logged.
- **Read aloud.** `speechSynthesis` reads two things:
  - the one-line answer on the plan (first and backup option, band word and travel range, built from the payload);
  - "Say this to the family" on the why page.

  A Stop control is shown. It uses Hindi only when the phone has a Hindi voice and the text exists in Hindi; today
  no Hindi summary exists (no runtime translation, SAFETY.md 14), so it says so and reads English.
- **Lexicon.** `app/inputs/lexicon.json` is generated by `.venv-app/bin/python app/inputs/build_lexicon.py` from
  `kb/taxonomy/services.json` (names, name phrases and symptom phrases) and committed, because the deploy bundle
  has no `kb/`. It ships in the app shell (`/lexicon.json`) and holds the danger words too.
- **Deploy.** Attach the two serving endpoints as app resources and expose them as env vars:
  - `SERVING_ENDPOINT_TEXT` (for example `databricks-meta-llama-3-3-70b-instruct`);
  - `SERVING_ENDPOINT_VISION` (for example `databricks-llama-4-maverick`).

  The calls use the Databricks SDK pre-installed on Apps. Without the env vars, the lexicon and danger paths still
  work and the model paths say "not available".
- **Tests.** `app/tests/test_inputs.py` mocks the endpoints.
