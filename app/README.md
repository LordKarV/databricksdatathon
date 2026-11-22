# Referral Saathi app

FastAPI serving one plain HTML page and a service worker. Answers come from model v2 (`derived/v2`), built into
`app/facts/out` at deploy time by `facts/build.py` and served by `facts/engine.py` (`meta.stub = false`). On
Databricks the app also calls the serving endpoints (free text, note photo) and the SQL warehouse (call outcomes).
The original stub contract (issue #5) survives only as a test fixture in `stub_data.py`.

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
| `stub_data.py` | The issue #5 stub contract, kept as a test fixture; real answers come from `facts/engine.py` |
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
    "evidence": [{"claim_id", "field", "quote", "source_url",
                  "flags": [{"code", "text", "weak", "place", "km"}]}],   // #86: warnings shown next to the quote
    "contributions": [{"label", "points"}],
    "flags": ["plain-English warning", ...],
    "call_ahead": [{"question", "asked_because"}],
    "call_first": true,
    "track_record": {"n", "k_confirmed", "k_contradicted", "k_no_info", "split": "dev | test"},
    "phone": {"e164": null | "+91...", "display", "shared_listings"},
    "is_real": ["..."], "where_check": "...", "why_first_text": null | "...",
    "say_to_family": {"en": "...", "hi": null | "..."}
  }],
  "why_not": [{"facility_id", "name", "travel", "option_rank", "minutes_vs_first", "band",
               "reason_code", "reason", "basis": [{"code", "field", "value"}]}],          // #86
  "what_would_change": null | {"kind": "confirm_nearer | first_says_no", "facility_id", "name",
                               "first_name", "minutes_vs_first"},
  "time_window": {"window_min", "first_outside"},
  "public_option": null | {"facility_id", "name", "operator", "label", "text", "travel"},   // when first_outside
  "meta": {"stub": false, "model_hash": "...", "data_snapshot": "...", "generated_at": "..."}
}
```

### `POST /api/area` (Area depth, S11/S12)

Body `{service, lat, lon}` (0.01 deg). Every number below comes from model v2 through `facts/engine.py` `area()`.

```
{
  "query": {"service", "service_label": {"en", "hi"}},
  "area": {"district", "state", "window_min": 60},
  "as_of": "YYYY-MM-DD",
  "summary": {"n_pins", "n_without_option", "access_now", "access_if_confirmed",
              "calls_could_close", "no_public_evidence"},          // MODEL: shares of the area, 0..1
  "caveat": "Low web presence looks like a gap. Verify before deciding.",
  "gap": {"pins_sampled", "pins_in_district", "radius_km", "district_claiming", "district_confirmed",
          "covered", "not_confirmed", "far", "no_claim",
          "public_standard": [{"facility_id", "name", "label"}]},           // #86: data gap vs care gap
  "pins": [{"pin", "lat", "lon", "first": null | {"facility_id", "name"}, "backup": null | {...},
            "travel": null | {"low", "high"}, "call_first": null | "name", "nearest_km": null | 96.0,
            "gap": "covered | not_confirmed | far | no_claim",
            "public": null | {"facility_id", "name", "km", "label"}}],
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

### Radius rule: neighbour packs

Crossing a state line for care is normal (PM-JAY cards work in any state), so the phone saves more than its own
state. `POST /api/pack/locate` returns the home state (state of the nearest PIN centroid) plus, nearest first, every
built pack whose state has a facility offering an app service within 150 km of the fix (`RADIUS_KM` in
`facts/engine.py`, the same radius as the planner's `MAX_KM`). `build_packs.py` writes each state's facility points to
`packs/out/index.json` (`pts`, 0.1 degree, so at most about 8 km off; 1,144 points in all, kept out of
`/api/pack/version`). `offline.js` saves every named pack through the service worker, refreshes them on each online
answer as before, and drops a neighbour pack that no fix has named for 30 days; the home pack is never dropped.

Offline, `pack.js` (`queryAll`) takes the list of the nearest PIN in each saved pack, removes duplicates and ranks
the union by straight-line km as before, keeping the 3 nearest plus the nearest likely one (the build rule). With
one pack the answer is exactly the old one (checked on 19,803 queries over all 36 packs). A card names the
facility's state when it is not the state of the PIN the plan is made for ("In Uttar Pradesh, 81.9 km"), and the
staleness line lists each state's build date when they differ.

Measured on the current build (`R` = 150 km; #1 compared with the home pack alone, over the 7 services):

| Border point | Packs saved | Gzip bytes | #1 changed |
| --- | --- | ---: | --- |
| Bihar-UP, Gopalganj/Kushinagar (26.50, 84.25) | Bihar, UP | 109,736 | 1 of 7 (MRI: UP hospital, 117.2 vs 119.6 km) |
| Delhi NCR, Noida edge (28.57, 77.32) | UP, Delhi, Haryana, Rajasthan, Uttarakhand | 184,748 | 0 of 7 |
| Jharkhand-Odisha, Chaibasa/Rourkela (22.40, 85.10) | Jharkhand, Odisha | 43,213 | 0 of 7 |
| Assam-Meghalaya, south of Guwahati (26.08, 91.78) | Assam, Meghalaya | 22,834 | 4 of 7 (one in Meghalaya; 0.2 to 3.3 km nearer) |
| Maharashtra-Karnataka, near Belagavi (16.20, 74.40) | Maharashtra, Karnataka, Goa | 145,834 | 0 of 7 |

Of the 7,885 PIN centroids within 50 km of a state border (a PIN of another state within 50 km), the nearest
facility offering the service is in another state for 24.2% of (PIN, service) pairs (13,334 of 55,195; from 14.2%
for trauma to 34.0% for burns). The home pack already lists those for a fix inside the home state, because every
pack ranks its PINs against candidates from all of India. The neighbour packs matter when the fix is across the
line from the home state (the patient's village, a trip), and they add the neighbour's PINs to the offline picker.
Interior points save one pack (Lucknow, Pune); Delhi NCR saves the most (5 packs, 185 KB).

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
  - Quotes link to the record's best source URL (official home page first, then a page about the facility), not a per-sentence page.

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
            vs_direct: {text, what_would_change|null, direct_p_objective, plan_p_objective,
                        direct_p_first_care, plan_p_first_care}|null}],
   stop_1_note: text|null,   (why route 1's first stop is not the options list's first choice)
   meta: {origin_state, terrain, plans_considered}}
  ```
- **Results screen.** A "Suggested route" card shows route 1 as numbered stops. Stages at the same hospital
  (dialysis: assessment, fistula, sessions) nest under it. The other routes sit in expandable sections.
- **Slip.** The slip and the WhatsApp text list route 1's stops, with phone and arrival range.
- **Comparison against going direct.** One plain sentence from the planner, in minutes, plus "what would
  change this answer" (#86). The probabilities stay in the payload, not in the sentence.
- **Build order.** Run `planner/export_v2.py` before `app/facts/build.py`, because the facts export copies
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
- **Read aloud.** See "Voice" below.
- **Lexicon.** `app/inputs/lexicon.json` is generated by `.venv-app/bin/python app/inputs/build_lexicon.py` from
  `kb/taxonomy/services.json` (names, name phrases and symptom phrases) plus `kb/taxonomy/hindi_phrases.json`
  (Devanagari and Hinglish phrases and danger words), and committed, because the deploy bundle has no `kb/`. It
  ships in the app shell (`/lexicon.json`) and holds the danger words too. On the server, `inputs/understand.py`
  folds spellings before matching (Devanagari nukta, vowel length, aspirated letters; Hinglish ee/oo/w/z and
  doubled letters) and, only when nothing matched exactly, fuzzy-matches Devanagari phrases of 5 or more letters
  (ratio 0.86). The browser still matches the lexicon exactly, so offline it does not catch misspelled Devanagari.
- **Deploy.** Attach the two serving endpoints as app resources and expose them as env vars:
  - `SERVING_ENDPOINT_TEXT` (for example `databricks-meta-llama-3-3-70b-instruct`);
  - `SERVING_ENDPOINT_VISION` (for example `databricks-llama-4-maverick`).

  The calls use the Databricks SDK pre-installed on Apps. Without the env vars, the lexicon and danger paths still
  work and the model paths say "not available".
- **Tests.** `app/tests/test_inputs.py` mocks the endpoints.

## Voice: Hindi and English, speech to text and read aloud

The user picks Hindi or English (default from the phone's language). The choice is stored on the phone in
`localStorage` `rs.voice` (wrapped in try/catch; a private window just forgets it) and is shared by the microphone
and Read aloud. The language is never auto-detected.

| Part | Where it runs | Files |
| --- | --- | --- |
| Speech to text, default | App server: faster-whisper `small`, int8, 2 CPU threads, language forced | `voice/transcribe.py`, `POST /api/transcribe`, `static/voice.js` |
| Speech to text, opt-in | Phone's Web Speech API (`hi-IN` / `en-IN`); sends audio to Google. Off unless ticked | `static/voice.js` |
| Speech to text, offline | Not available: the page says to use the keyboard's mic | `static/voice.js` |
| Understanding the words | Browser lexicon, then `POST /api/parse` (see above) | `static/input.js`, `inputs/understand.py` |
| Read aloud | Phone's `speechSynthesis`, `hi-IN` or `en-IN` | `static/speech.js`, `static/speech_templates.json` |

- **Flow on `#/describe`.** Tap Speak (up to 15 s, tap again to stop). The transcript goes into the text box, so the
  user can see and fix it, then through the same parse as typed text. When it names one service, the card asks in
  the chosen language, for example "kya aapka matlab dialysis hai?" in Devanagari, with full-width Yes / No buttons. "Read the
  question aloud after I speak" (on by default, stored in `rs.say`) speaks the question. No goes back to the text
  box. Danger words still show Call 108 at once.
- **Read aloud** on the results (options and the multi-stop route) and on the why page's Call ahead section (that
  option, its top quote and its call-ahead questions). The spoken text comes only from fixed templates in
  `speech_templates.json` filled from the `/api/plan` payload; no model writes spoken content. Facility names and
  quotes stay in their own script. If the phone has no Hindi voice, it reads the English text and says so.
- **Faithfulness.** `buildSpeech` returns the payload path of every value it speaks. `tests/test_speech.py` checks
  both languages on real and stub plans; `tests/test_faithfulness.py` reads `state.spoken` from the running page
  on the results and every why page and checks each spoken value against its field, and that no other digit is
  spoken except 108 and 102.
- **Privacy.** Audio is decoded in memory and never written to disk or logged; transcripts are not stored or
  logged. Responses carry `Cache-Control: no-store`. With the opt-in phone service, Google receives the audio.
- **Model.** About 480 MB, downloaded from Hugging Face on the first request after each container start into
  `VOICE_MODEL_DIR` (default `<tmp>/rs-whisper`), and about 1.2 GB of memory once loaded. Until it is ready,
  `/api/transcribe` answers 503 and the page says voice is getting ready. If the workspace blocks Hugging Face,
  voice input stays on the keyboard-mic hint. Not yet tested on Databricks Apps.
- **Limits.** Measured on synthetic voices only, on a laptop: Hindi character error rate 0.13 to 0.29, English 0,
  about 2 s for a 4 s clip; the 2 vCPU container will be slower. Hinglish speech (romanised Hindi spoken) fails in
  both language settings. Hindi templates and labels are drafts until a native speaker reviews them (#10).
  Questions' "need" words and evidence quotes are read in English. Safari, Firefox and real Android phones are
  not tested.

## Call outcomes: the learning loop (#65)

- **What is recorded.** On the why page, "Said yes", "Said no" and "No answer" are sent to `POST /api/outcome`.
  "Wrong number" stays on the slip only, because it says nothing about the service. The page sends:
  - a random `outcome_id`;
  - the facility and service;
  - the answer and the tap time;
  - the location rounded to 0.01 degree.
- **Offline.** The page queues outcomes in localStorage (the last 50) and flushes them when the phone is back
  online. A retried flush writes once, because the insert is a `MERGE` on `outcome_id`.
- **What the server adds and keeps.**
  - The server keeps only the district of the nearest PIN, never the coordinates.
  - It fills in the call questions from the engine's templates, so no user text reaches the table.
  - It adds the model version and the app version (the service worker cache name).
  - The row is written to `OUTCOMES_TABLE` (default `workspace.referral_saathi.call_outcomes`), through the
    SQL Statement Execution API on `DATABRICKS_WAREHOUSE_ID` with named parameters.
  - Without the warehouse env var the endpoint returns 503, and the page keeps the item queued.
- **Live count.** `GET /api/outcomes/summary` feeds a live section on "How this works", cached for 60 s. It shows
  outcomes recorded, and how many contradicted the band the app shows today: "Said no" to a Likely, or "Said yes" to
  an Unlikely.
- **Notebook.** Section 9b of the submission notebook reads the table and shows how the outcomes would move each
  evidence family's weight (a Beta update, with today's mean counted as 10 earlier calls). Nothing retrains
  automatically.
- **Tests.** `app/tests/test_outcomes.py` mocks the warehouse.

## Community: field reports, area pulse and the family card

Health workers already know which hospitals took their patients. These three features put that knowledge next to
the listing evidence without turning it into opinions: no star ratings, no free-text reviews, no feed about named
people. Every report is a fixed choice, and every number it adds is shown with its count and date.

- **What is stored.** One row per report in `call_outcomes` (`OUTCOMES_TABLE`), through the same parameterised
  `MERGE` as #65.
  - A phone result (`kind` call: yes, no, no answer). A "no" can carry one reason from a fixed list of 8.
  - A visit result (`kind` visit: accepted or turned away), with an optional reason and a wait bucket
    (`lt_30m`, `30_120m`, `gt_2h`).
  - Also the facility, the service, the district of the nearest PIN, the time cut to the hour on the server before
    the write, the model and app versions, and `reporter_key`.
  - `reporter_key` is HMAC-SHA256 of the signed-in user (`X-Forwarded-User`) under the `REPORTER_KEY` secret, cut
    to 16 hex characters (`community/reporter.py`). It is never the user or the email. Without the secret it is
    NULL: the row is stored but never counts as a reporter.
  - Nothing about the patient, no names, no phone numbers, no typed text, nothing finer than the district.
  - One report per reporter, facility, service and kind in 24 h (429 after that; the page drops it).
- **On the page.**
  - After "Call before you go", "Said no" shows the optional reason buttons. "Not offered there" and "Not
    available today" are separate groups. Skip, a different answer, or leaving the page sends the "no" without a
    reason.
  - Making a slip remembers the referral on this phone (`localStorage['rs.recent']`: facility, service, time,
    point rounded to 0.01 degree; at most 5, for 7 days). The start screen then offers "How did a referral go?"
    (`#/report`): accepted or turned away, why, and the wait. Reports go through the same offline queue as #65.
  - Option cards and the why page show "Field reports": the server's dated lines in English and Hindi, any
    availability note, and "Reports disagree with the listing: call first". The why page ledger gains a "Field
    reports" row.
  - When the reports could not be read, `field_reports.note` says so under the plan.
  - Strings are in `static/community.js` (lazy, cached by the service worker). Hindi strings are drafts.
- **Field witness math** (`community/field.py`, pure `field_adjust`).
  - Prior Beta(N0 p, N0 (1 - p)), where p is the model score. N0 = 10 is an assumption: the model counts as 10
    earlier reports, as in notebook section 9b.
  - For "offers": an accepted visit counts 1 and a phone yes counts 1/2 (SAFETY 10: a receptionist's yes is not
    a confirmation).
  - Against: a "does not offer" reason counts 1 on a visit and 1/2 on the phone.
  - Each report is weighted 0.5^(age in days / 30) over a 90-day window. Each reporter counts once (their
    latest report).
  - Nothing moves until 2 distinct reporters have reported.
  - Temporary reasons (no bed, doctor away, machine down, asked to pay, closed) never lower the score. They
    become a note for the last 7 days.
  - The effect is one additive term, `logit(posterior) - logit(p)`, so the ledger still sums to the score.
  - Reports alone never take a score below 0.20 (they flag "call first" instead; SAFETY 9). Without listing
    text they never lift it to the Likely line (t_L = 0.3686, the model card's) or above.
  - Reports can lower a band, never raise it. A Likely pair whose adjusted p falls below t_L (0.3686) becomes Not
    verified, with the reason "Health-worker reports disagree with the listing: call first" (English and Hindi).
    Every other band stays as the model set it, even when the reports are positive; the field line still shows
    them. There is still no public "Unlikely" from reports alone.
  - The plan is rebuilt from the adjusted scores (`Engine.plan(..., scores)`): the ranking, why_first_text,
    why_not, the abstention, say_to_family, the call-ahead questions, the family card and its read-aloud all use
    the adjusted p and band. p_lo and p_hi move by the same logit shift, not by the posterior's own interval.
- **Tie-break from health-worker reports** (#86; `engine.tied_prefix`, `field._tie_row`).
  - Only after the Field reports term, only for profiles outside `NEAREST_FIRST` (urgent NICU, scheduled
    dialysis, planned MRI and heart surgery; never the emergency order).
  - Tied: the leading options (at most 3) are in the same band, their shown p differ by at most 0.05 and their
    travel by at most 10 min, for every pair. Only those are reordered; nothing else moves.
  - Value per option: `field.net`, the term's own recency-weighted counts (accepted + phone yes at half weight -
    "does not offer"; temporary reasons never count), from the same cached aggregates. Fewer than 2 reporters
    count 0. Equal values keep the evidence-and-time order.
  - Shown only on the why page of the tied options, as the row "Tie broken by: health-worker reports" (with
    "(simulated for the demo)" for demo reports), payload `tie_break`. Cards keep only the field line.
- **Never waits on the warehouse.** `/api/plan` and `/api/recommend` call
  `field.apply_field(plan, field.aggregates(wait=False), now, eng)`. One `GROUP BY` query is cached for 60 s and
  refreshed in a background thread, because a stopped warehouse can take 30 s to answer. The first answer after
  start-up has no field lines. On any warehouse error the plan is unchanged and `field_reports` is
  `{"read": false, "note": {...}}`.
- **Area pulse** (`#/pulse`, `GET /api/pulse?district=&service=` or `lat=&lon=`, `community/pulse.py`,
  `static/pulse.js`).
  - District counts for coordinators and planners, for one window only: the last 90 days, as the 13 whole
    weeks that end where the current ISO week starts. Times are cut to the week in SQL, so the numbers stay the
    same for a whole week.
  - k-anonymity: a district x service cell needs at least 3 distinct reporter keys and 5 reports; a facility
    cell or a reason cell needs 5 and 8. Reason cells show the two classes only ("does not offer",
    "temporarily unavailable"), never a single reason.
  - Complementary suppression: what a service cell holds beyond its shown facility (or reason) cells is either
    nothing or passes the 5 and 8 rule itself; otherwise the smallest detail cell is hidden too.
  - Hidden cells are left out, with no count of them, and every total is the sum of the shown cells. The only
    text about hidden data is "Some reports are not shown so no single health worker can be identified.",
    shown on every answer.
  - Acceptance rates carry a 95% Wilson interval in words. Each most-used facility carries the listing sentence
    behind its band.
  - Known limit (COMMUNITY_CHECK.md 2E): someone who reads the same query in two weeks can subtract the
    answers and see what one week added, and a report that arrives late with an older time changes a week
    already published. If that week added a single report, it is exposed. Health workers who collude can
    also subtract their own reports from a cell: with k = 3, two of them can recover the third's report. A
    fixed weekly answer narrows this but does not close it; closing it would need noise (differential privacy)
    or a release that is frozen once published.
  - 503 until the SQL below has run.
- **Family journey card** ("Send to family" on the slip, `static/journey.js`).
  - One self-contained HTML file, sent with Web Share or downloaded. It opens on any phone without a Databricks
    login (a link into the app would not) and makes no network requests (CSP `default-src 'none'`).
  - It shows 108 and 102 first, then the stops in order with phone, address and map links, what to bring, the
    questions to ask, and the dates, plus Read aloud and Large print.
  - No patient data, no origin point, no p values or band codes: bands become "Listed for this service" (Likely,
    and no health-worker reports disagree) or "Call first to check".
- **Demo flag.** `COMMUNITY_DEMO=1` adds simulated reports in memory for real options at the README point
  (26.6, 85.48, Sitamarhi), for dialysis and emergency C-section. They are never written. Every line starts
  "Simulated for the demo:" and the pulse shows a banner. The demo has no "reports disagree" case: even
  simulated, it would be a negative claim about a real hospital. `checks/a11y_check.py` runs with the flag on.
- **Deploy.**
  - Apply `databricks/app_plumbing/field_reports.sql` (4 columns, CHECKs) before binding the secret. Once
    `REPORTER_KEY` is set, every write queries `reporter_key`.
  - Then create the `referral-saathi/reporter-key` secret and the app resource, and add
    `- name: REPORTER_KEY / valueFrom: reporter-key` to the app.yaml that `tools/deploy/deploy.sh` writes.
- **Tests.**
  - `test_field.py` (math, write path, rate limit), `test_pulse.py` (k-anonymity, Wilson), `test_journey.py`
    (card content under node), `test_community_api.py` (no blocking, the note, input bounds).
  - `test_faithfulness.py` recounts fixed reports against every field line and note (counts and "N days ago",
    Hindi numbers equal to English). It also downloads the family card for every option in both languages and
    checks each name, phone and number against the plan.

## Why not the nearest, flagged citations, data gap vs care gap (#86)

- **Why not the nearest?** `why_not` lists the 3 nearest candidates by travel time other than the first choice,
  also when the answer abstains. Each has one plain sentence of at most two clauses, the most decisive first:
  - contradicted; no own sentence; every sentence flagged;
  - beyond the urgency window (60 min for emergencies); farther than the first choice;
  - a prerequisite the first choice's listing mentions and this one's does not (24x7 emergency, CT, operating theatre);
  - tag-only or vague evidence; map point in doubt; shared phone; not confirmed; weaker evidence.

  `basis` names the field behind each clause. The tests check it against the engine and the payload.
  - `what_would_change`: the nearer Not verified listing that a "yes" on the phone would move to first place. It is
    re-ranked with the confirmed-pair score. Otherwise: "if option 1 cannot take the patient, call option 2".
  - `time_window.first_outside`: when option 1 misses the window (60 min for emergencies), the answer's first line
    says so ("The best-evidenced option is about 104 min away; that misses the 60-min window for this care"). It
    shows 108 (and 102 for mothers and newborns) and `public_option`: the nearest hospital the public standard
    expects to offer the care, labelled "by public standard, not verified". This holds whether or not the answer
    abstains.
- **Flags inside the citation.** Each quote carries the warnings the pipeline already computed:
  - source page: `url_kind` list or unverified (`audit/provenance/q1_sources.py`), or a Wikipedia page about a place
    in `place_gazetteer` more than 25 km away;
  - sentence: `claims.parquet` attribution `ambiguous`, `foreign_names`, `places_other_district/state`, and the
    third-party, hedge, part-time, camp, future and past cues.

  Weak quotes are listed after clean ones (demoted, not hidden), with a 0-point row in "How we decided".
  The record's source link now prefers a page about the facility over a list or an unchecked page.
  This covers 9,082 of 9,947 records, against 5,514 before.
- **No names.** `facts/redact.py` turns "Dr. X Y" into "a doctor" in every quote. That covers options, route stops,
  "Ignored" flags, the website check and offline packs. Institutions named after someone are kept, and so is the
  claim id.
- **Data gap vs care gap** (`gap` in `/api/area`). Each sampled PIN is one of:
  - covered: a confirmed option within the window;
  - care gap: listings in the window claim it but none is confirmed, or every listing is beyond the window;
  - data gap: no listing within 150 km claims it, so we cannot tell.

  The page states the PIN sample (the first 40 PINs by number). Where a PIN has no option with public evidence, its
  row names the nearest public-standard hospital (`pins[].public`). Where the district shows a gap, the screen lists
  the district's public-standard hospitals (`gap.public_standard`, at most 5). Both are labelled "by public standard,
  not verified".
- **Tests.** `tests/test_standout.py`. `tests/test_faithfulness.py` checks every new value on the page. It adds three
  probes: Pusa trauma, Pune heart surgery (a named doctor) and Nagpur MRI (flagged sources).
