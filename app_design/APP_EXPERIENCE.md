# App experience spec: Referral Saathi

Status: build contract for the team, written 2026-11-21. Nothing here is built. The judges picked Referral Saathi
(field worker lens, totals 24.5 vs 23 and 23) with three grafts: Setu's gap split and ten-call list go into the Area
depth, Referral Desk's call questions generated from each option's weakest terms go into the call script, and the
danger checklist moves onto the start screen. Every safety guardrail in judging/SAFETY.md is applied below.

Numbers in wireframes are placeholders unless marked (measured). Facility names in mocks are invented.

## Sources used in this spec (short tags)

| Tag | What | Where |
| --- | --- | --- |
| [Brief] | Challenge doc, slides, Marketplace listing | app_design/brief/challenge_doc.md, opening_slides.md, marketplace_listing.md |
| [Spec] | Model spec v1 (Witness Ledger) | model/design/MODEL_SPEC_v1.md (sections cited as Spec 6.4 etc.) |
| [Proto] | Current prototype outputs | model/proto/fusion/pair_scores.parquet, band_record.parquet, test_metrics.json |
| [Net] | Outbound internet probe from a deployed App | tools/net-probe/RESULT_2026-11-21.json |
| [Cap] | Workspace and Apps capabilities | audit/capabilities/CAPABILITIES.md |
| [F-vision] | Photo to service | app_design/feasibility/vision/ (outputs/calls.log, scores.csv) |
| [F-voice] | Free text, voice, translation | app_design/feasibility/voice_language/ (out/scores.md) |
| [F-geo] | GPS, geocoding, travel time, map weight | app_design/feasibility/geo_routing/ (out/*.json) |
| [F-actions] | Deep links, 108/102, call script, phone validator | app_design/feasibility/actions/links.py, probes/ |
| [F-a11y] | Framework, page weight, axe, offline ladder | app_design/feasibility/accessibility/ (outputs/results.json) |
| [F-offline] | Offline GPS, service worker behind auth, packs, SMS | app_design/feasibility/offline/ (out/sizes.json, browser_results.json) |
| [Safety] | Safety, ethics and privacy review | app_design/judging/SAFETY.md (sections cited as Safety 8 etc.) |

The six feasibility subagents could not write their REPORT.md files (harness refusal). Their findings live in the
workflow results this spec was built from and in the scripts and out/ folders listed above. "Not tested" means no
test was run; it never means "assumed to work".

## 1. The product

Referral Saathi is one Databricks App for the people who arrange care for a patient: give it a service and a place
(GPS by default) and it returns a referral plan (a first choice, two backups and the one call worth making first)
where every option carries quoted facility text, a calibrated confidence with its track record, and plain Hindi or
English reasons the user can read to the family. It ends in actions that work on a basic phone (call ahead, 108/102,
directions, an SMS slip) and it keeps working with no data connection from satellite GPS and a saved state pack.

The app never diagnoses. The user already knows the service (the doctor or PHC said so). The patient is not the user.

### Three users, one app, three depths

| | Field health worker (ASHA, ANM) | NGO coordinator | District planner |
| --- | --- | --- | --- |
| Where | Standing with the patient, village, low-end Android, patchy data, Hindi | At a desk or on the phone, patient elsewhere | Office, laptop, thinking about an area, not one patient |
| Location | GPS (the patient is here) | GPS fills the field; usually taps Change location and types a PIN or village | GPS fills the field; usually types a district or crash coordinates |
| Depth | Quick (default) | Compare | Area |
| Needs | One answer she can trust, a call script, 108/102, a slip for the family, works offline | Options side by side, the trade-off in one sentence, something to show a supervisor | Standing plan per PIN, where evidence is missing vs where care is missing, which ten calls to make |

Depth is a toggle on the plan screen, remembered per device (localStorage, wrapped in try/catch). Quick is the
default. All three depths read the same stored decision rows, so the coordinator and the planner see the field
worker's answer, only with more of its numbers.

"Is the patient here?" sits under the location. In Quick depth it defaults to Yes. In Compare and Area depth it has
no default and the user must tap one (Safety 6.2), so a Nagpur coordinator never gets a plan for her own desk. GPS
still fills the field in all depths.

## 2. Judging fit

The brief: "A patient needs a specific kind of care. Where should they go, and why should they trust that answer?"
and "A community health worker in rural Bihar has a patient who needs dialysis. An NGO coordinator in Maharashtra
needs a hospital that can handle a high-risk delivery. A district planner wants to know where to send trauma cases
from a highway accident hotspot." [Brief]

The hard gate: "Every team must be able to answer two questions about every recommendation their build makes: WHY
this facility? ... HOW did you decide? ... If your build can't explain itself, it doesn't meet the challenge
requirements, however good it looks." [Brief]

Submission rules [Brief]: runs on Free Edition (Databricks App, [Cap]); uses the provided dataset (all facility rows
come from it; the India Post and NFHS-5 files are the listing's own supplements); "a clear non-technical user
workflow" (Quick depth: GPS, one tile, plan); "Cite the underlying facility text" (every card quotes claim_atoms
rows verbatim); "Communicate uncertainty" (bands, intervals, track record, abstention, data dates).

No rubric has been published [Brief]. The team's criteria are creativity, modeling and impact, plus accessibility
and reasoning.

| Criterion | What scores | Evidence |
| --- | --- | --- |
| Creativity | Reasoning built to be passed on: "Say this to the family" in Hindi, the referral slip, the call script. The call is the verification step and re-plans on the spot. The planner's standing plan per PIN is the same artefact as the field worker's offline pack. GPS works with no internet and the app says so. "Evidence we ignored" shows a contaminated sentence and why. | Judges' creativity lens, [F-offline] |
| Modeling | The glass-box model shown as it is: three heads (exists, where, offers) with per-term points that sum to the score, intervals, three-outcome band track record, exact "why the farther one first" arithmetic, abstention when evidence is thin, and a render refusal if the screen does not reproduce the ranking. LLMs only map words or a referral note to one of 7 services, behind deterministic guards. | [Spec] 5.5, 6.5-6.7, 7.1-7.4; [Cap] (LLM said confidence 1 on contaminated records) |
| Impact | Built for the named users: 1.8 KB shell (measured), 0.44 s to the first button on the emulated 2G profile vs 44 s for Streamlit (measured), a 110 KB gzip state pack (measured, placeholder content), Hindi, 48 px targets, call-ahead before travel, 108/102 first in emergencies. | [F-a11y], [F-offline] |
| Accessibility | WCAG 2.2 AA axe gate in every state; icon plus word plus colour; read aloud; one decision per screen. | Section 7 |
| Reasoning | Every line of every card maps to a named column (section 5). | Section 5 |

## 3. Inputs

### 3.1 Service input

The 7 services are the decision layer's keys (model/gold/queries.json): emergency_csection, nicu,
trauma_emergency, burn_care, dialysis, mri, cardiac_surgery. Every input path ends at one of them and the user
confirms it. Nothing is chosen for the user.

Order on the start screen:

1. Tiles (default, offline, no model). 8 tiles, 2 columns, each 48 px or taller with an icon, a large Hindi label
   and an English label. Fixed order, emergencies first:
   - Operation se delivery (emergency C-section)
   - Navjaat ICU (NICU)
   - Accident / chot (trauma)
   - Jalna (burns)
   - Dialysis
   - MRI scan (planned)
   - Dil ka operation (planned)
   - Other / not sure
   Under the two planned tiles, one fixed line: "Chest pain or stroke now? Call 108" with a tel:108 button
   (Safety 3, 4). Hindi labels are a draft until a native speaker reviews them (Safety 14.1).
2. Search box (offline, no model). Plain substring match over the lexicon synonyms in English, Hindi (Devanagari),
   Hinglish and Marathi (LSCS, caesarean, "operation se delivery", "khoon saaf karna", "kidney machine"). Matches
   appear as tiles. The lexicon ships in the app shell. Reuse the synonym list behind [Spec] 6.2.
3. "Other / not sure" opens "Describe it in your words" (online only). A plain text field with lang set to the UI
   language, so the Android keyboard's own voice typing works with no code (not tested in the App). Flow:
   a. The danger-word list runs first, in the browser, before any model call. A hit shows the Call 108 bar and the
      text never maps to an elective service (Safety 3: the "chest pain, sweating, left arm numb" case must not
      reach cardiac_surgery).
   b. POST /api/map-service calls databricks-meta-llama-3-3-70b-instruct, temperature 0, json_schema strict, with an
      enum of the 7 services plus "other" and "symptoms_only" and a decisive_phrase field. Measured 36/36 correct,
      0 schema errors, phrase verbatim 36/36, median 876 ms [F-voice].
   c. Guard: decisive_phrase must be a substring of the input. If not, or the reply is "other", the tiles open.
      "symptoms_only" shows "This sounds like symptoms. Ask the PHC doctor which service is needed, or call 108."
   d. The result is a confirm chip quoting the phrase (screen S2).
   e. 8 s timeout. Any error falls back to the tiles with a one-line message.
4. "Scan referral note" (online only, camera). Screen S2a first asks "Ask the patient. Cover the name before taking
   the photo." (Safety 1). Then:
   a. <input type=file accept=image/* capture=environment>. The image is drawn to a canvas, the user can crop, and
      it is re-encoded to JPEG at about 1024 px on the long side. Re-encoding through a canvas drops EXIF metadata
      (standard browser behaviour; not tested on Android).
   b. POST /api/read-note sends it once to databricks-llama-4-maverick with json_schema and a 15 s timeout.
      Measured 9/9 service correct, resisted the in-image injection, median 2.07 s, no 429 in 11 calls [F-vision].
   c. Deterministic guard (reuse feasibility/vision/score.py): the trigger phrase must appear verbatim in the
      detected text, the lexicon must find the same service, instruction-like lines are flagged. Measured: accepted
      10/10 correct document answers, flagged 2/2 injection answers [F-vision]. Failing answers still go to the
      confirm screen, but with "We are not sure" and the tiles open below.
   d. The confirm screen quotes the trigger phrase from the note. If the note names a hospital, that hospital is
      shown first with our evidence for it; the app never silently replaces the doctor's choice (Safety 1).
   e. The image lives in memory for one call. It is never written to disk, a table or a log. The model reply is not
      logged. The wording on screen is "We do not keep the photo. It is sent once to a Databricks model to read
      it." because Databricks documents that Foundation Model API requests may be processed outside the workspace
      region (https://docs.databricks.com/aws/en/machine-learning/foundation-model-apis/compliance), and the
      retention terms for Free Edition pay-per-token endpoints were not checked (Safety 1).
   f. Any 400, 429, timeout or unparseable reply falls back to the tiles.

Confirmation: every path except a tile tap goes through S2 (one tap: "Yes, that is right" or "Change service").

Languages: Hindi and English at launch, picked from navigator.language with a toggle on every screen. All UI and card
text are template strings in one strings file per language. Marathi waits for a native-speaker review (Safety 14.1);
until then Marathi users get Hindi or English and the toggle says "Marathi coming". Facility quotes always stay in
their original language.

Danger checklist (inline on S1, not a gate): a collapsed row "Danger signs now?" with 6 boxes: heavy bleeding,
breathing trouble, unconscious or fitting, labour with bleeding or baby stuck, chest pain, burn on face or large
area. The wording is the team's and the card says "checklist written by the team, not clinically reviewed" until it
is checked against an official ASHA or NHM module (Safety 5.3). A tick, or a danger-word hit in any typed text,
makes the Call 108 bar full width and moves it to the top of every later screen. Ticks change wording and the order
of actions only. They never change the ranking ([Spec] 6.4). The plan request is sent in parallel, so ticking never
delays it.

For the emergency-profile services (trauma, emergency C-section, burns) the Call 108 button is on every screen
whether or not a box is ticked, including the GPS search screen and the offline answer (Safety 5.1).

### 3.2 Location input

Team rule: GPS is the default for every user. Typing a PIN, city, district or coordinates, or dropping a pin, lives
under "Change location" and is never the default. Exception: offline, where the app uses the best alternative
(3.2.3).

#### 3.2.1 GPS default (online)

- First visit: the location block shows one focused button, "Use my location (GPS)". The permission prompt fires on
  that tap, never on page load (https://web.dev/articles/user-location: "Always request access to location on a
  user gesture").
- Later visits: if navigator.permissions.query({name: "geolocation"}) returns "granted", the fix starts on load with
  no tap (behaviour on a device not tested). "denied" switches the block to "Location blocked. Type a PIN or place."
  with focus in the Change location field.
- Call: getCurrentPosition({enableHighAccuracy: true, timeout: 15000, maximumAge: 60000}).
  enableHighAccuracy must be true: Chromium maps false to PRIORITY_BALANCED_POWER_ACCURACY (Wi-Fi and cell
  positioning), which needs data (LocationProviderGmsCore.java lines 110-127, copy in feasibility/offline/sources/).
  Without a timeout the request "might never return" (web.dev). Never watchPosition while online.
- The app stores its own last fix {lat, lon, accuracy, time} in IndexedDB, overwriting (one fix, no history,
  Safety 7.1). It does not rely on maximumAge as a store: the W3C spec keeps the cached position per page load and
  lets the browser evict it (https://www.w3.org/TR/geolocation/).
- A saved fix under 6 h old shows at once with its age while the new fix arrives.
- Echo: "Near Singwahini, PIN 843317, Sitamarhi, Bihar. GPS, 40 m, 09:14". District comes from point-in-polygon on
  geoBoundaries ADM2 on the server (8.0 MB simplified, ODbL); locality and PIN from the nearest post office (median
  1.9 km away). Nearest-PIN alone gets the district wrong about 1 time in 8 (87.2% right over 1,972 points;
  77-80% within 5 km of a boundary) [F-geo]. The place and its source appear on every plan, card and slip
  (Safety 6.1).
- Accuracy rules (Safety 6.3, [F-geo], [F-offline]):
  - up to 1,500 m: accepted as is.
  - 1,500 to 5,000 m: amber "Approximate. Is this right?" with one tap to confirm before the plan.
  - over 5,000 m: the plan is held until the user confirms or picks a place.
  - over 2,000 m, also: "Turn on precise location for Chrome" (Android approximate permission forces low accuracy;
    inferred from Chromium source, not tested).
- Errors (codes per MDN getCurrentPosition: 1 denied, 2 unavailable, 3 timeout): the live region says what
  happened ("Could not get GPS. Type a PIN or place."), focus moves to the Change location field, and the last
  saved fix is offered with its age. Fix older than 6 h: plan held until "Patient is here" is tapped (Safety 6.4).

#### 3.2.2 Change location (one smart field)

One text box, parsed by deterministic code (reuse audit/geo/resolve_input.py per [Spec] 6.2). Placeholder text:
"PIN, village, town, district or 'lat, lon'".

| Input | Rule | Resolution | Offline | Echo |
| --- | --- | --- | --- | --- |
| PIN | exactly 6 digits | India Post PIN centroid (19,584 PINs) | yes (pack) | "PIN 843317 centre, can be up to 9 km off" |
| Coordinates | two numbers, comma or space | checked against the India bounding box | yes | "Point 25.1546, 83.6814, near Mohania" |
| District | matches the district list | district HQ town, labelled | yes (pack) | "Kaimur district, using HQ Bhabua" |
| City, town, village | anything else | offline post-office names first, then Nominatim search (countrycodes=in) on submit | post-office names only | candidate list with district and state, user picks |
| Google Maps link (tier 3) | contains @lat,lng or q=lat,lng | parsed as coordinates | yes | as coordinates |
| Drop a pin (tier 2) | "Drop a pin" button | Leaflet 1.9.4 from cdnjs, OSM tiles, loaded on tap | no | as coordinates |

- Ambiguous names always list matches and ask; the app never guesses ("Muhra" returned Gaya, Bihar and Damoh, MP
  [F-geo]). The offline gazetteer found 1 of 4 test villages, so offline the picker adds "Not found? Use PIN or
  district then post office".
- Maps short links (maps.app.goo.gl) and WhatsApp location text are not tested and not parsed.
- "Back to my GPS location" is always the first row of the sheet.
- Recent places: up to 5 PINs, coordinator depth only, with "Forget my locations" in settings (Safety 7.1).
- Planner hotspot points (tier 3): "Add another point" appends coordinates to the same field; the Area plan runs
  per point.

#### 3.2.3 Offline: the best alternative

Offline is detected when navigator.onLine is false, or a /api call fails, or a /api call takes more than 8 s
[F-a11y]. A fetch with {redirect: "manual"} that returns type "opaqueredirect" means the Databricks session
expired, not offline: the banner says "Sign in again" and the pack keeps answering [F-offline].

What still works offline and why:
- GPS from satellites. Chrome on Android takes location from the OS (fused provider or LocationManager), so a
  satellite fix needs no data when enableHighAccuracy is true (Chromium source, [F-offline]). Network-based
  location (Wi-Fi, cell) does not work offline. Indoors a fix may never arrive. Cold start can take 2-4 minutes
  (https://en.wikipedia.org/wiki/Time_to_first_fix). Offline time to first fix on a real phone is not tested.
- The app shell from the service worker cache, the state pack from IndexedDB, tel: and sms: links (they use the SIM).

Location ladder offline (the app never makes the user wait for GPS):
1. Show the app's own last fix at once with its age. If it is under 6 h old, the plan from the pack shows
   immediately, labelled "Using GPS from 09:14 (2 h ago)". If older, the plan is held until the user taps "Patient
   is here" or picks a place.
2. In parallel, watchPosition({enableHighAccuracy: true, maximumAge: 0, timeout: 120000}). Accept the first fix with
   accuracy of 1,000 m or better, save it, clear the watch, and swap the plan with "Updated to GPS now". The screen
   says "Getting GPS from satellites. Stand outside. Up to 2 minutes." with a spinner and no countdown (no time
   limits, WCAG 2.2.1). "Choose place instead" is one tap away the whole time. If 120 s pass, use the best fix seen
   with the amber rule above, or fall to step 3.
3. Offline picker: PIN (6 digits, resolved from the pack's PIN centroids), or district then post office (9,058 Bihar
   offices ship in the Bihar picker, 56 KB gzip measured), or typed coordinates. Focus moves to the PIN field and the
   live region says why.

What is on the phone (the referral pack), per [F-offline]:
- Scope: the user's state plus facilities in neighbouring states near the border, chosen from the first online GPS
  fix. "Add a state" and "All India" (1.85 MB gzip measured with placeholder content) in settings for coordinators.
  No district packs (2.6-21 KB, they drop facilities across district lines).
- Content per (PIN, service): the stored plan from the decision layer (primary, backup1, backup2, call-first marker),
  band, P_S with its interval, up to 2 own quotes with claim ids, the record's source URLs, phone with phone trust,
  the abstention sentence when there is one, the 108 crew fallback (best public facility), Hindi service names and
  the call script template. Plus the PIN centroid table, the post-office picker, and the data snapshot date and
  model hash.
- Layout: normalized (facility table, evidence table, PIN index). Bihar pack plus picker: 110 KB gzip on the wire,
  196 KB in IndexedDB (measured). Denormalized is 8x larger on the wire and 14x on disk, so do not use it.
  Largest state today: Uttar Pradesh 228 KB gzip (measured).
- Stored in IndexedDB only (not also in Cache Storage, saving about 476 KB). navigator.storage.persist() after the
  first save.
- Download in the background after the first online result, never on the critical path.
- Refresh: on every online open, GET /api/pack/version (snapshot + model_hash). If changed, download in the
  background and swap in one IndexedDB transaction, keeping the old pack until the new one is complete.
- Two dates on every offline answer (Safety 15.1): "Facility data from web pages collected <snapshot date>. Saved to
  this phone 21 Nov (3 days ago)." Amber after 30 days on the phone, red after 90 with "phone numbers may have
  changed".
- Offline ranking: the app shows the stored plan for the nearest PIN centroid in the pack and says "Plan made for
  PIN 843317 centre, 4 km from you". Distances to facilities are recomputed from the fix as straight-line km and a
  road range (x1.26 at 69-40 km/h, "rough"). ponytail: no client-side re-ranking; if fixes far from PIN centres
  prove common, port the U formula to JS and test it against the Python rows.
- Packs built from the fallback model are labelled demo data and never shipped as real (Safety 15.5).

No-internet channels:
- tel:108, tel:102, tel:<facility> and sms:?body=<slip> work offline on the SIM (links.py).
- The offline HTML copy (tier 3): one file per state with the pack embedded (Bihar 475 KB, 112 KB gzip; GPS and PIN
  fallback worked from file:// with the network off in desktop Chromium, measured; opening it from Android Downloads
  not tested). For the user's own phone only. "Pass it between workers on WhatsApp" is removed from the pitch until
  the Marketplace terms are read, and each copy shows its build date, data date and a short content hash
  (Safety 16).
- SMS query bot (tier 4, demo only): a team Android phone running android-sms-gateway (Apache-2.0) with a laptop
  script (feasibility/offline/sms_reply.py) answering "DIALYSIS 843317" from the pack in 2-3 GSM-7 segments
  (measured format). The number is never shown, replies go only to allowlisted team numbers, nothing is stored
  (Safety 17). Real two-way SMS needs DLT registration through an Indian entity (days to weeks); roadmap only. USSD
  is killed.

## 4. Screens

Mobile first, 40 columns, single column, reflows at 320 px. "[...]" is a button or link, "( )" a radio, "[ ]" a
checkbox. "!" marks the 108 bar. Desk layouts (S10, S11) are the same content in a wider grid.

### S1 Home: location, service, danger signs

```
+--------------------------------------+
| Referral Saathi     [hi|EN] [Detail] |
| WHERE IS THE PATIENT?                |
| (pin) Near Singwahini, PIN 843317    |
|       Sitamarhi, Bihar. GPS 40 m     |
|       09:14                          |
| Patient is here? (o)Yes ( )No        |
| [Change location]                    |
| WHAT DOES THE PATIENT NEED?          |
| [search: kidney, delivery, MRI...  ] |
| [Operation se    ] [Navjaat ICU    ] |
| [ delivery       ] [ NICU          ] |
| [Accident/chot   ] [Jalna / burns  ] |
| [Dialysis        ] [MRI (planned)  ] |
| [Dil ka operation] [Other /        ] |
| [ (planned)      ] [ not sure      ] |
| Chest pain or stroke now? [Call 108] |
| [camera] Scan referral note          |
| Danger signs now? [show 6 boxes v]   |
| Saved for offline: Bihar, 21 Nov     |
+--------------------------------------+
```
First visit: the WHERE block is a single "Use my location (GPS)" button. "Patient is here?" has no preset in Compare
and Area depth.

### S1a GPS searching (online or offline)

```
+--------------------------------------+
| ~ No internet. Saved data, 21 Nov    |
| ! [phone] CALL 108 (free)            |
|   (shown for emergency services)     |
| Getting GPS from satellites...       |
| Stand outside. Up to 2 minutes.      |
| Using now: GPS from 09:14 (2 h ago)  |
|   Near Singwahini, Sitamarhi         |
| [Patient is here]                    |
| [Choose place instead]               |
|   PIN | District -> post office      |
+--------------------------------------+
```

### S1b Change location

```
+--------------------------------------+
| Change location                  [x] |
| [pin] Back to my GPS location        |
| PIN, village, town, district,        |
| or 'lat, lon'                        |
| [ Ashti                            ] |
| Which one?                           |
| ( ) Ashti BO, PIN 444801, Amravati   |
| ( ) Ashti, Beed, Maharashtra         |
| [Use this place]                     |
| [map] Drop a pin (needs internet)    |
| Precision: PIN centre, up to 9 km off|
+--------------------------------------+
```

### S1c Location problems

```
+--------------------------------------+
| Location blocked for this site.      |
| Type a PIN or place instead.         |
| [ 6-digit PIN or place             ] |
| (focus is here)                      |
| Last GPS: yesterday 17:40, Sitamarhi |
| [Use it: patient is there]           |
+--------------------------------------+
| Approximate location (2.4 km).       |
| Is this right? Near Sitamarhi town   |
| [Yes, patient is here] [Change]      |
| Turn on precise location for Chrome  |
+--------------------------------------+
```

### S2a Before scanning a note

```
+--------------------------------------+
| Scan the doctor's referral note      |
| 1 Ask the patient first.             |
| 2 Cover the patient's name.          |
| 3 Photo the part that says what is   |
|   needed.                            |
| We do not keep the photo. It is sent |
| once to a Databricks model to read.  |
| [camera] Take photo                  |
| [Back to tiles]                      |
+--------------------------------------+
```

### S2 Confirm what we understood

```
+--------------------------------------+
| We read on the note:                 |
| "Refer to higher centre for dialysis"|
| Looking for: a dialysis centre       |
| [ Yes, that is right ]               |
| [ Change service ]                   |
+--------------------------------------+
| You wrote: "...khoon saaf karwana..."|
| Looking for: a dialysis centre       |
| [ Yes ] [ Change service ]           |
+--------------------------------------+
| For C-section the chip reads:        |
| "A hospital that can do emergency    |
|  C-section" (never "patient needs")  |
+--------------------------------------+
```

### S3 The plan (Quick depth)

```
+--------------------------------------+
| Dialysis near Singwahini             |
| (GPS 40 m, 09:14)       [Read aloud] |
| [Quick] [Compare] [Area]             |
| CALL FIRST: option 1                 |
| 1 [check] LIKELY offers dialysis     |
|   Kidney Care Centre, Sitamarhi      |
|   private: may charge                |
|   24 km, about 25-45 min (rough)     |
|   "6 haemodialysis machines in a     |
|    dedicated unit" [equipment]       |
|   Listings like this: too few checks |
|   yet (2 checked)                    |
|   About the listing, not about       |
|   today. Call to check a slot.       |
|   [Call ahead] [Why this?]           |
| 2 ? NOT VERIFIED: call to confirm    |
|   Sadar Hospital (govt) 19 km        |
|   [Call ahead] [Why?]                |
| 3 [check] LIKELY Nephro Centre 71 km |
| [Why not the nearer ones?]           |
| [Get there] [Send slip to family]    |
+--------------------------------------+
```
Quick depth shows the band word, the track record in words and no decimals (Safety 8.1). "Chance at least one
works" is not on Quick depth or the slip (Safety 8.3). With 10 or more checks the line reads "About 8 in 10 listings
like this checked out (22 checked)".

### S3x Abstention (expected often with the current model)

```
+--------------------------------------+
| Emergency C-section near Ashti BO    |
| (PIN centre, up to 9 km off)         |
| ! [phone] CALL 108 (free)            |
|   [phone] Call 102: pregnant women,  |
|   babies (free). No answer? Call 108 |
| No facility within 150 km has enough |
| public evidence that it does         |
| emergency C-section.                 |
| CALL TO CONFIRM                      |
| 1 ? NOT VERIFIED  <name> 41 km       |
|   [Call ahead] [Why?]                |
| 2 ? NOT VERIFIED  <name> 58 km       |
| District hospital: the public        |
| standard says this level should      |
| offer it; not verified in our data.  |
|   <DH name> 33 km [Call]             |
+--------------------------------------+
```
Text from [Spec] 6.6. Current prototype: 2 of 69,713 pairs are Likely (measured, [Proto], model_hash
de82eeee9ea0d0f6-fallback), so this screen is the most likely result today and must look finished, not empty.

### S4 Why this facility

```
+--------------------------------------+
| < Plan  Kidney Care Centre  LIKELY   |
| SAY THIS TO THE FAMILY [Read aloud]  |
| "Is aspatal ki listing mein dialysis |
|  ki 6 machine likhi hain. Yeh 24     |
|  kilometre door hai. Hum jaane se    |
|  pehle phone karke poochhenge."      |
| (Hindi draft, not reviewed)          |
| Doctor's note: "Refer to higher      |
|  centre for dialysis"                |
| FROM ITS OWN LISTING                 |
| [equipment] "6 haemodialysis machines|
|  in a dedicated unit"                |
| [procedure] "Haemodialysis and       |
|  peritoneal dialysis"                |
| Source: one of these 3 pages [show]  |
| IS IT REAL: own website; mobile      |
|  number not shared with others       |
| WHERE: PIN, map point, city agree    |
|  (within 3 km)                       |
| WE IGNORED: "Dialysis at City        |
|  Hospital, Patna" - names a          |
|  different hospital [see text]       |
| HOW SURE: likely (0.81, range 0.70   |
|  to 0.89). Of 2 checked like this:   |
|  1 confirmed, 0 wrong, 1 no info.    |
|  Too few checks yet (dev, not test)  |
| WHY BEFORE SADAR HOSPITAL: Sadar is  |
|  5 km nearer; distance favours it    |
|  1.4x. Evidence here is 1.8x         |
|  stronger. So this ranks first.      |
| DISTANCE: 19 km straight x 1.26 =    |
|  24 km, 25-45 min (rough estimate)   |
| [Show the numbers] [Call ahead]      |
+--------------------------------------+
```
The decimal appears here, one tap from Quick. Interval wider than 0.4 adds "We are very unsure about this one."
(Safety 8.4).

### S4b Why not the others

```
+--------------------------------------+
| < Plan  Looked at, not put first     |
| Shanti Clinic 6 km                   |
|  Our data has no own sentence about  |
|  dialysis: only a list of 40 words   |
|  [see text] [Call]                   |
| Eye Hospital 9 km                    |
|  Its dialysis sentence names another |
|  hospital [see text] [Call]          |
| Life Hospital 11 km                  |
|  PIN says Sitamarhi, map point says  |
|  Patna [see text] [Call]             |
| 14 more within 50 km: no public      |
| evidence of dialysis in our data     |
+--------------------------------------+
```
Wording describes our data, never the facility (Safety 9.1). Unlikely facilities keep a Call button (Safety 9.3).

### S5 How we decided (numbers)

```
+--------------------------------------+
| < Why   Numbers for option 1         |
| OFFERS DIALYSIS  (20 pts = 2x odds)  |
|  base: private hospital      -18     |
|  own sentences, 2 fields     +46     |
|  equipment with a count      +14     |
|  record merges 12 sources     -6     |
|  total +36 -> 0.81 (0.70-0.89)       |
| EXISTS  0.93   [waterfall v]         |
| WHERE   0.95   [waterfall v]         |
| Band rule:                           |
|  [x] P_S >= 0.70 [x] where >= 0.7    |
|  [x] exists >= 0.7 [x] own unit      |
| Without the 2 quoted sentences:      |
|  offers would be 0.34                |
| If a call confirms option 2, it      |
|  ranks first.                        |
| Rank: 0.93 x 0.81 x 0.45 = 0.34      |
| Data <snapshot>  Model de82..        |
| [Model card] [Row id 4471/dialysis]  |
+--------------------------------------+
```

### S6 Call ahead

```
+--------------------------------------+
| Call Kidney Care Centre              |
| [phone] CALL +91 62xx xxx xxx        |
| Number looks like the hospital's own |
| Read this (hi|EN)       [Read aloud] |
| 1 "Kya yeh Kidney Care Centre,       |
|   Sitamarhi hai?"  [Yes][Wrong no.]  |
| 2 "Ek mareez ko dialysis chahiye."   |
| 3 "Aaj ya kal slot hai?"  [Y][N]     |
| 4 "Naye mareez lete hain? Ek session |
|   kitne ka? PM-JAY chalega?"         |
| 5 "Is Sitamarhi branch mein hi hota  |
|   hai ya doosri branch mein?"        |
|   (asked because: record merges 12   |
|   web pages)                         |
| 6 "Nahin to kaun sa hospital?" [___] |
| 7 "Pahunch kar kisse milein?" [___]  |
| [Said yes] [Said no] [No answer]     |
| [Wrong number]          [Undo 1 min] |
+--------------------------------------+
```
Emergency profile adds at the top: "Call 108 first. Do not wait for this call to send the patient." (Safety 10.1).
The script never asks for or says the patient's name (Safety 10.3).

### S7 Get there

Emergency profile (trauma, emergency C-section, burns, or any danger tick):
```
+--------------------------------------+
| ! [phone] CALL 108 ambulance (free)  |
| [phone] Call 102: pregnant women and |
|  babies (free, JSSK). No answer?     |
|  Call 108.                           |
| Tell the crew: take us to Kidney     |
|  Care Centre, Sitamarhi.             |
| If they cannot: the best government  |
|  place in reach is Sadar Hospital,   |
|  19 km (not verified).               |
| 108 not connecting? Call 112.        |
| [Ambulance not coming or refused]    |
+--------------------------------------+
  after that tap:
+--------------------------------------+
| A car has no medical crew. Keep      |
| trying 108.                          |
| [car] Uber (destination filled)      |
| [car] Ola car (destination filled)   |
| [map] Directions in Google Maps      |
| Address: Station Road, ... [Copy]    |
+--------------------------------------+
```
Scheduled and elective (dialysis, MRI, planned cardiac): directions, Uber, Ola auto, Ola "ride later" (dialysis),
Rapido and Namma Yatri open-app buttons with the address to copy, Google Maps transit mode for planned surgery.

### S8 Referral slip

```
+--------------------------------------+
| REFERRAL SLIP  21 Nov 2026 10:45     |
| Service: Dialysis                    |
| Go to: Kidney Care Centre            |
|  Station Road, Sitamarhi 843302      |
|  Phone +91 62xx  Ask for: (from call)|
|  Map: https://www.google.com/maps/...|
| Why: its listing says 6 dialysis     |
|  machines. We phoned 10:40, they     |
|  said yes.                           |
| If not: Sadar Hospital 19 km,        |
|  +91 ...                             |
| Emergency 108. Pregnancy/baby 102.   |
| Carry the doctor's note.             |
| Made 21 Nov 10:45. Call before going |
| if this is more than a day old.      |
| Ask the patient before sending.      |
| [SMS] [WhatsApp] [Show big] [Print]  |
+--------------------------------------+
```
No patient name (paper blank), no patient location, no confidence decimals (Safety 13.3). The Maps link has no
origin. No app link (no anonymous access, [Cap]).

### S9 Offline answer

```
+--------------------------------------+
| ~ NO INTERNET                        |
| Facility data: web pages from <date> |
| Saved to this phone: 21 Nov (3 days) |
| ! [phone] CALL 108   [phone] 102     |
| Dialysis near PIN 843317             |
| GPS now, 25 m. Plan made for PIN     |
| centre, 4 km from you.               |
| CALL BEFORE YOU GO                   |
| 1 [check] LIKELY Kidney Care Centre  |
|   19 km straight, road 24 km or more |
|   "6 haemodialysis machines..."      |
|   [Call ahead] (works offline)       |
| 2 ? NOT VERIFIED Sadar Hospital      |
| 3 [check] LIKELY Nephro Centre       |
| Needs internet: note scan, map, road |
| times, places outside Bihar+border   |
| [SMS slip to family]                 |
+--------------------------------------+
```

### S10 Compare (coordinator)

Phone: one card per option with identical row labels in identical order. Desk: a real table with th scope and a
caption.
```
+--------------------------------------------------------------+
| High-risk delivery near Ashti BO (444801)  [Change] [Print]  |
| Patient is here? ( )Yes ( )No   <- must tap                  |
| ! CALL 108    Call 102 (free, JSSK)                          |
| Plan: A, then B, then C. Chance at least one listing checks  |
| out: 0.86 (assumes they fail independently)                  |
|               | A (first)      | B (backup)    | N (nearest)  |
| Band          | LIKELY         | LIKELY        | NOT VERIFIED |
| Offers (range)| 0.78 .66-.87   | 0.71 .58-.82  | 0.22 .08-.47 |
| Track record  | 18/22 conf.    | 18/22         | 25/65        |
| Exists/Where  | 0.97 / 0.95    | 0.91 / 0.90   | 0.88 / 0.62  |
| Road km, min  | 41, 45-70      | 58, 60-95     | 16, 15-30    |
| Quote         | "Emergency LSCS| "24 hour      | "Gynaecology |
|               |  available"    |  labour room" |  OPD"        |
| Ignored text  | none           | 1 sentence    | none         |
| Phone         | mobile, unique | landline      | shared x4    |
| Public/priv.  | private        | public        | private      |
| Ask on call   | anaesthetist?  | OT, blood?    | do LSCS here?|
| Phone result  | said yes 14:05 | -             | not reached  |
| Why A before N: N is 25 km nearer, distance favours N 2.3x;  |
| A's evidence is 5.7x stronger (0.74 vs 0.13). A ranks first. |
| [Open WHY / HOW for any column] [Export record]              |
+--------------------------------------------------------------+
```

### S11 Area (planner)

```
+--------------------------------------------------------------+
| Standing referral plan: TRAUMA   Kaimur (Bhabua), Bihar      |
| 9 PIN areas + 1 point (25.1546, 83.6814)   [Print chart]     |
| 6 of 9 PIN areas: no trauma option with public evidence      |
| within 60 min.                                               |
| Access now 0.11 | if calls confirm 0.22                       |
| Calls could close: 0.11 | No public evidence of care: 0.78   |
| Low web presence looks like a gap. Verify before deciding.   |
| PIN    | first choice      | backup         | min    | call  |
| 821109 | Sharda Hosp, NV   | G.S. Mem., NV  | 47-81  | Sharda|
| 821105 | none in 60 min, nearest 96 km      |        |       |
| [10 calls that close the most gap] [Gap table] [CSV]         |
| [Download as offline pack for field workers]                 |
+--------------------------------------------------------------+
```
"Care gap" is renamed "No public evidence of care" on every surface (Safety 19.1). Numbers are from the fallback
prototype and must be regenerated.

### S12 Ten calls (planner)

```
+--------------------------------------------------------------+
| 10 calls that close the most of the gap (trauma, Kaimur)     |
| # facility          phone        areas   access gain         |
| 1 G.S. Memorial     landline       4      +0.06               |
| 2 Sharda Hospital   own mobile     3      +0.04               |
|   [Script] [Said yes] [Said no] [No answer]                  |
| Shown as "Said yes on the phone, 23 Nov"; score unchanged.   |
| [Send list on WhatsApp] [CSV]                                |
+--------------------------------------------------------------+
```

### S13 Model card (global HOW)

```
+--------------------------------------+
| How Referral Saathi decides          |
| 1 Funnel: 10,088 rows > 9,959        |
|   records > 69,713 pairs > bands     |
| 2 Evidence rules, with hand-check n  |
| 3 Weights with 90% intervals, signs  |
| 4 Calibration (bars, Wilson)         |
| 5 Track record per band: confirmed / |
|   wrong / no info, n, dev or test    |
| 6 Baselines (incl. an LLM judge)     |
| 7 Assumptions in words: road factor, |
|   speeds, D_s, R, band thresholds    |
| 8 Walk-throughs: Aravind, Wockhardt  |
| 9 What it does not know: beds,       |
|   staff, today's slots               |
| 10 Hashes: data, model, labels       |
+--------------------------------------+
```

### S14 Offline and settings

```
+--------------------------------------+
| Saved for offline: Bihar + border    |
| 110 KB, saved 21 Nov                 |
| Data <snapshot>, model de82..        |
| [Update now] [Add state] [All India] |
| [Download offline copy (HTML)]       |
| Language (o)Hindi ( )English         |
| Read aloud: on (Hindi voice found)   |
| Detail (o)Quick ( )Compare ( )Area   |
| [Forget my locations]                |
| Call results waiting to send: 2      |
+--------------------------------------+
```

## 5. Reasoning for each recommendation

### 5.1 What is shown, and which data backs each line

Every line is a template filled by code from stored rows. No LLM writes, rewrites or translates any reason
([Spec] 7.4). Column names below are the prototype's (pair_scores.parquet columns, measured) or the spec's output
contracts ([Spec] 6.9, 7.5).

| Line on screen | Source |
| --- | --- |
| Band word (LIKELY / NOT VERIFIED / UNLIKELY) and icon | pair_scores.band; band_reason gives the failed rule |
| Name, town, private/public | facility_features (operator type; only 469 of 10,088 say public, so "public" is shown only when the field says so) |
| Distance and time range | benchmark_answers d1_km, minutes_lo, minutes_hi (live: same formula in /api/plan) |
| Quotes with field tag | pair_contributions cited atom ids -> claim_atoms.text (must equal the raw parquet item) |
| "Source: one of these pages" | the record's source URLs (no sentence-to-URL map exists, [Spec] 7.1) |
| Doctor's note quote | the S2 trigger phrase, held in the page only (never stored) |
| Is it real | facility_contributions, existence head terms (own website, phone class, shared phone) |
| Where | location head votes and flags (PIN, map point, city) |
| What we ignored | rejected atom ids and rejected_reason for this pair |
| How sure (decimal and range) | pair_scores.p_s, p_s_lo, p_s_hi |
| Track record | band_record.parquet: N, k_confirmed, k_contradicted, k_no_info, split, labels_sha256 |
| "Without the quoted sentences" | pair_scores.p_s_without_cited |
| Why before a nearer option | benchmark_answers.why_first_text, recomputed from P_E, P_S, G ([Spec] 6.7) |
| Call first marker | live counterfactual: P_S of option k set to 0.95 ([Spec] 7.2) |
| Points waterfall | pair_contributions / facility_contributions per term, prior and posterior weight from weights.parquet |
| Abstention sentence and outside option | benchmark_answers.abstained, abstain_text, outside_option_uid |
| Phone trust | facility_features phone class; links.e164_india result |
| Data and model hash | pair_scores.model_hash, snapshot date, labels_sha256 |

### 5.2 Three depths of the same reasoning

1. "Say this to the family": 2-3 template sentences (what the listing says, how far, what we will do to check),
   numbers written as words with units in the Hindi string ("24 kilometre") so the voice cannot pick a unit
   (Safety 14.4). Read aloud with speechSynthesis only when getVoices() has a voice for the language; otherwise the
   button is hidden [F-voice]. The same text goes on the slip.
2. WHY card (S4): the lines in 5.1 in words.
3. HOW card (S5): points waterfall per head, band checklist, counterfactuals, ranking arithmetic, hashes, and "trust
   receipts" (tier 2): each number taps through to its table name, row id and snapshot date.

### 5.3 Uncertainty and track record

- Band word first, always with a number or a count next to it. "Likely" is never used outside the band rule
  ([Spec] 5.5). Only three band words exist: Likely, Not verified, Unlikely. Referral Desk's "POSSIBLE" is not used.
- Not verified cards start "NOT VERIFIED: call to confirm" in grey with a question-mark icon.
- Quick depth: no decimals; the track record in words ("about 8 in 10 listings like this checked out, 22 checked").
  N under 10 says "too few checks yet (N checked)". Until the sealed test is used, the label is "dev, not final
  test" (Safety 8.5). Today the Likely band has N = 2 on dev out-of-fold and 0 on test (measured, [Proto]), so the
  card will say "too few checks yet" for every Likely option.
- Under every band: "This is about the listing, not about today. Call to check a slot." P_S means a public web check
  would confirm the listing ([Spec] 5.6), not a bed today (Safety 8.2).
- Interval wider than 0.4 adds "We are very unsure about this one."
- P(at least one works) appears only in Compare and Area, labelled "chance at least one listing checks out (assumes
  they fail independently)" ([Spec] 6.5, Safety 8.3).
- Travel time is always a range with its source ("OSRM road route, free flow" for the top 3-5 when online, else
  "straight-line x 1.26, rough"). Options within about 20% of each other say "about the same time" [F-geo].
- Phone outcomes appear as "Said yes on the phone, 14:05" beside the score, never inside it and never as "confirmed"
  (Safety 10.4, 10.6).

### 5.4 Faithfulness

- The page recomputes U = P_E x P_S x G and the order from the numbers it displays and compares them with the
  server's order. If they disagree it shows the list without numbers and "numbers unavailable" and logs the query id
  (Safety 8.8). It never shows a blank screen.
- The waterfall rows must sum to the displayed logit within 1e-9 ([Spec] 7.4), checked in the browser before
  rendering S5.
- Release test (not only runtime): for all 40 benchmark queries, every displayed number equals the stored row,
  every quote equals claim_atoms.text, every ignored sentence is in the pair's rejected ids.
- Translation: none at runtime for anything a user acts on (call script, slip, danger text, transport). Templates
  per language. Direct LLM translation broke a name, quote or number in 4/4 runs; placeholder protection passed 4/4
  (measured, [F-voice]), which is kept only as a tier-3 option for the WHY card's descriptive text, labelled
  "machine translated".

### 5.5 Road factor: reconcile before the demo

The spec uses road factor 1.3 at 40-25 km/h (assumption, [Spec] 6.3). Measured on 50 rural Bihar pairs: circuity
median 1.257 (95% CI 1.23-1.34), OSRM free-flow median 69 km/h, the spec's 1.4 at 40 km/h gives times 1.87x OSRM
[F-geo]. Ask the decision-layer owner to use 1.26 and show 69-40 km/h. The app only displays what the decision layer
stores, so the card label must name whichever factor it used.

## 6. Actions

All actions are plain links the user taps. Nothing books, dials or opens by itself: Chrome will not launch an
external app without a user gesture (https://developer.chrome.com/docs/android/intents). Builders are in
feasibility/actions/links.py (stdlib only; self-check passes, measured). "Probed" means one HTTP request with an
Android Chrome user agent; no link has been tap-tested on a real phone. tap_test.html exists for that.

| Action | Exact format | Verified |
| --- | --- | --- |
| Ambulance | tel:108 | links.py self-check; NHM page for the 108 role |
| Pregnancy and infant transport | tel:102 ("If 102 does not answer, call 108") | NHM JSSK page; roles vary by state, not checked |
| Integrated emergency | tel:112 (small line) | Wikipedia citing 112.gov.in; 112.gov.in refused our connection |
| Call ahead | tel:+91XXXXXXXXXX only if links.e164_india passes and the number is not shared across 3+ cities | 9,448 of 10,088 dialable, 76 refused incl. "100" (measured) |
| Directions | https://www.google.com/maps/dir/?api=1&destination=LAT,LNG&travelmode=driving (two-wheeler, transit); origin omitted = device location; destination = "name, town" when coordinates are low trust | Google Maps URLs docs; probe 200 |
| Map app chooser (works with offline maps) | geo:0,0?q=LAT,LNG(Label) | Android intents doc |
| Uber (documented) | https://m.uber.com/looking?drop[0]={"latitude":LAT,"longitude":LNG,"addressLine1":"Name"} (URL-encoded JSON) | Uber deep-link docs; probe 301 keeps drop[0] |
| Uber (legacy backup) | https://m.uber.com/ul/?action=setPickup&pickup=my_location&dropoff[latitude]=LAT&dropoff[longitude]=LNG&dropoff[nickname]=Name&dropoff[formatted_address]=Addr | probe 302 to get.uber.com keeps params; not in current docs |
| Ola | https://olawebcdn.com/assets/ola-universal-link.html?drop_lat=LAT&drop_lng=LNG&drop_address=Name&category=auto&landing_page=bk (category=mini for labour or newborn; &bk_act=rl for ride later) | docs say utm_source is mandatory; drop-off without it not tested |
| Rapido | intent://rapido.bike/#Intent;scheme=https;package=com.rapido.passenger;S.browser_fallback_url=<encoded Play URL>;end plus copy-address | App Link verified in assetlinks.json; no destination params documented |
| Namma Yatri | intent://nammayatri.in/#Intent;scheme=https;package=in.juspay.nammayatri;S.browser_fallback_url=<encoded Play URL>;end plus copy-address | same |
| Slip by SMS | sms:?body=<URL-encoded slip> (RFC 5724; no recipient, the phone's own app opens) | self-check; no-recipient behaviour on Android not tested |
| Slip by WhatsApp | https://wa.me/?text=<URL-encoded slip> (contact picker) | probe 302 to api.whatsapp.com |
| Show big | full-screen slip at 200% text for the family to photograph | no network needed |
| Print | one print stylesheet for the A5 slip, the wall chart and the record (tier 3) | not tested |

Ordering by urgency profile ([Spec] 6.4, Safety 11, 12):
- Emergency (trauma, emergency C-section, burns, any danger tick): Call 108 first; 102 beside it for C-section and
  NICU; the crew fallback line "Ask the crew to take you to A. If they cannot, the best government place in reach is
  B" always shown, B named even when Not verified, because 108 dispatch picks the nearest centre and 102 goes to
  CHC or government hospitals; then call ahead "while waiting"; ride links only after "Ambulance not coming or
  refused", starting with "A car has no medical crew. Keep trying 108.", cars only for labour or newborns. If A is
  private and the patient is pregnant: "Free delivery and transport under JSSK apply in public hospitals."
- NICU (urgent): as emergency, 102 prominent.
- Dialysis (scheduled): call ahead first (slot, new patients, cost, PM-JAY), then directions, Ola ride later, Uber,
  share the plan with the family member who travels.
- MRI and planned cardiac surgery: call ahead, directions (transit for surgery), ride links, share.

Call-ahead script (S6): links.call_script order (identity check first, "I have a patient who needs <service>",
SERVICE_QUESTIONS, "If you cannot, which hospital nearby can?", "Whom should we ask for when we arrive?"), plus
questions added by fixed rules from the option's weakest terms, each shown with "asked because ...":

| Condition (stored row) | Added question |
| --- | --- |
| P_L < 0.7 or PIN and map point disagree | "What is your full address and a landmark?" |
| phone shared by 3+ listings | line 1 becomes required before the rest is shown; "may be a directory number" |
| service evidence only in a specialty or tag list (T low) | "Do you do <service> here yourselves, or send patients elsewhere?" |
| record merges many web sources (bucket high) | "Is this the <town> branch, or another branch?" |
| private | "What does it cost? Is PM-JAY accepted?" |

Outcome buttons: Said yes / Said no / No answer / Wrong number, with Undo for 1 minute. "Said no" or "Wrong number"
promotes the backup at once. "No answer" in an emergency keeps the option with "not reached" and only moves it down
if a backup says yes; for scheduled services it moves to the backup (Safety 10.5). Outcomes are kept in IndexedDB,
queued offline, and sent to /api/outcome when online with facility id, service, outcome, date, depth and district
only (no caller number, no patient data). They are shown beside the score and never feed the score or the track
record without review (Safety 10.6). "We went and they could not help" is an outcome on the slip screen.

## 7. Accessibility checklist and page-weight budget

Gate before every demo build: 0 axe-core 4.12.1 violations (wcag2a, wcag2aa, wcag21a, wcag21aa, wcag22aa,
best-practice) in every state: start, GPS searching, GPS denied, approximate, results, abstention, why, numbers,
call, slip, offline, compare, area. Reuse feasibility/accessibility/measure.py and offline_test.py. The plain FastAPI
page measured 0 violations; Streamlit, Dash and Gradio each had 3 rule types [F-a11y].

- [ ] Targets 48x48 CSS px for primary actions, nothing under 24x24 (WCAG 2.5.8).
- [ ] Contrast 4.5:1 text, 3:1 UI, in light and dark (prefers-color-scheme).
- [ ] Band, gap and status never by colour alone: icon plus word plus colour.
- [ ] lang on html and on every other-language span (lang="hi" on Hindi strings).
- [ ] Status messages in a role=status live region; focus moves to the next input on any failure.
- [ ] Reflow at 320 px; works at 200% text. No separate text-size control (browser scaling covers it).
- [ ] No time limits: the GPS wait has "Choose place instead", no countdown. prefers-reduced-motion honoured.
- [ ] Real table with th scope and caption for Compare and the gap table on desk; identical card rows on phone.
- [ ] Every chart (waterfall, calibration) has a table under it. The map is never the only place anything appears;
      markers have unique titles; OSM attribution visible.
- [ ] Icon plus word on every action; Western digits with units; one decision per screen in Quick; typing only for
      the PIN or place.
- [ ] Read aloud on the plan, why, call script and slip, only when a voice exists for the language.
- [ ] System fonts with a Noto Sans Devanagari fallback in the font stack; no downloaded web fonts.
- [ ] One manual TalkBack pass and one low-end Android test on the deployed App before judging (not run yet).
- Known gap: WCAG 3.3.8 cannot be met for the Databricks sign-in, which the app does not control ([Cap]: no anonymous
  access).

Low literacy context: 96 of 706 districts have women's literacy under 60% and 26 under 50% (NFHS-5, measured from
the local parquet, [F-a11y]).

Page-weight budget (gzip on the wire) [F-a11y], [F-geo]:

| Item | Budget | Measured reference |
| --- | --- | --- |
| Critical path to the GPS button | <= 50 KB, <= 5 requests, 0 third-party hosts | probe page 1.8 KB, 1 request |
| First button visible | <= 1 s Lighthouse slow 4G, <= 3 s Regular 2G | 0.24 s / 0.44 s (Streamlit 8.2 s / 44.1 s) |
| Plan JSON | <= 20 KB | not measured |
| Repeat visit | <= 5 KB via the service worker | not measured |
| State pack (background) | <= 150 KB per state target | Bihar 110 KB; UP 228 KB (over: accept or split UP) |
| Map (opt-in only) | about 220 KB first view | leaflet.js 42.6 KB + css 3.5 KB + 8 tiles 173.6 KB |
| Note photo upload | about 1024 px long side | maverick prompt tokens grew 1,017 to 2,177 with size |

## 8. Tech stack and architecture

```
 Android Chrome / desk browser
 +-------------------------------------------------+
 | index.html + app.js + strings_{hi,en}.json      |
 | service worker (sw.js at "/")  IndexedDB:       |
 |  network-first navigations,     pack, last fix, |
 |  cached shell on error or >=500 outcomes queue  |
 | Geolocation, Permissions, file input+canvas,    |
 | speechSynthesis, Leaflet on demand (cdnjs)      |
 +-----------------------|-------------------------+
                         | HTTPS, Databricks Apps auth proxy (SSO cookie)
 +-----------------------v-------------------------+
 | Databricks App: FastAPI 0.115 + uvicorn         |
 |  in memory at startup: scores, contributions,   |
 |  claim atoms, band record, plans_by_pin,        |
 |  PIN centroids, post offices, ADM2 polygons     |
 +---|------------------|-------------------|------+
     | SQL warehouse    | serving endpoints | internet (cached proxies)
     v                  v                   v
  Unity Catalog     llama-3-3-70b       OSRM demo, Nominatim,
  tables            llama-4-maverick    OSM tiles (browser)
```

Framework: FastAPI (pre-installed 0.115, [Cap]) serving one hand-written HTML page, vanilla JS and JSON endpoints.
Chosen because it was the only option tested that was small, axe-clean, able to use GPS and camera with plain
browser APIs, and able to reload offline (Streamlit reload offline failed with net::ERR_INTERNET_DISCONNECTED)
[F-a11y]. Preact or HTMX only if a screen outgrows plain JS. app.yaml command as in
feasibility/offline/probe_app/app.yaml with --no-access-log added (Safety 7.3, https://www.uvicorn.org/settings/).

Service worker and auth (tested only in a local simulation of a cookie-auth proxy, [F-offline]):
- Register only from the app's own authenticated page. Network first for navigations; cached shell on network error
  and on status >= 500 (a stopped app returns a proxy error page). Let redirects through so an expired session signs
  in again.
- <link rel=manifest crossorigin=use-credentials> (the manifest loaded only with this attribute, measured).
- New service worker registration without a session fails with SecurityError (script behind a redirect, measured);
  an update check without a session fails and the old worker stays active (measured).
- Not tested on *.databricksapps.com. Unknowns: Vary: * (breaks cache.addAll), cookie lifetime, whether /sw.js is
  served unchanged, what a stopped app returns. Deploy feasibility/offline/probe_app first (section 10).

Endpoints:

| Endpoint | Does | Calls |
| --- | --- | --- |
| GET / , /sw.js, /app.js, /strings_*.json | shell | none |
| GET /api/ping | online and session check | none |
| POST /api/resolve | place text or rounded point -> place echo, district, PIN | in memory; Nominatim on miss |
| POST /api/plan | service + rounded point -> plan, cards, why-not, abstention | in memory |
| GET /api/why/{uid}/{service} | full WHY and HOW rows | in memory |
| POST /api/map-service | free text -> service | llama-3-3-70b |
| POST /api/read-note | image -> service + trigger phrase | llama-4-maverick + guard |
| POST /api/route | top 3-5 road times | OSRM table, 3 s timeout, cached |
| GET /api/pack/version, /api/pack/{state} | offline pack | precomputed file |
| GET /api/area/{district}/{service} | planner view (tier 3) | precomputed |
| POST /api/outcome | call outcome | append to a table (write path not tested) |

Coordinates go to the server in POST bodies rounded to 0.01 degree (about 1.1 km); the exact fix stays on the phone
for the echo. Ranking scales are 15 km or more ([Spec] 6.4), so rounding changes no ranking (Safety 7.2). Never log
lat, lon, PIN and service together with a user id.

Tables read (one Unity Catalog schema in the `workspace` catalog, created by the build phase, read once at startup
through warehouse 6a2f5637720a2c17 with databricks-sql-connector; app resources sql_warehouse CAN_USE and table
SELECT per [Cap]): pair_scores, pair_contributions, facility_scores, facility_contributions, claim_atoms,
band_record, weights, calibration, benchmark_answers, plans_by_pin, area_metrics (tier 3), pin_centroids,
post_offices. Prototype parquet sizes: pair_scores 1.7 MB, pair_contributions 1.9 MB, claim_atoms 1.4 MB (measured),
which fit easily in 6 GB.

Endpoints called (serving_endpoint resources with CAN_QUERY, [Cap]): databricks-meta-llama-3-3-70b-instruct (free
text), databricks-llama-4-maverick (note). Gemma-3-12b is not used anywhere.

Precomputed in a notebook (not in the request path): plans_by_pin for 19,584 PINs x 7 services (the same decision
code as /api/plan), state packs (normalized) and /api/pack/version, area metrics and ten-call lists (tier 3), offline
HTML per state (tier 3), cached demo replies for the demo note and demo queries.

Internet services and fallbacks ([Net]: all reachable from a deployed App; data.gov.in and hospitals.pmjay.gov.in
are not, so nothing depends on them):

| Service | Used for | Fallback |
| --- | --- | --- |
| Phone data | everything live | offline mode (section 3.2.3) |
| Databricks App and login | shell, plan | cached shell + pack; "Sign in again" on opaqueredirect; offline HTML |
| SQL warehouse | startup load only | app does not start; restart before judging |
| llama-3-3-70b | describe it | lexicon, then tiles |
| llama-4-maverick | note scan | tiles; demo uses a cached reply, labelled |
| OSRM demo server | top 3-5 road times | straight km x 1.26 at 69-40 km/h, "rough". No bulk calls (19,584 requests would be 5.4 h at 1/s; demo-server terms) |
| Nominatim | village search, friendlier place name | post-office gazetteer, PIN, district; 1 req/s across the whole App (one AWS IP), cached, generic User-Agent, rounded point only |
| OSM tiles + cdnjs | drop a pin, map | list only, typed coordinates |
| Google Maps, Uber, Ola, WhatsApp | actions | tel: and sms: always shown |
| Keyboard voice typing (Google, server-side on Android) | voice into the text field | typing, tiles |
| Mobile voice network | calls, 108/102, SMS | "Show big" slip; nothing replaces a call |

## 9. Safety guardrails

All from judging/SAFETY.md; section numbers in brackets.

Input and diagnosis
1. No condition photos. Note scan only, with consent screen, cover the name, crop, EXIF dropped by canvas
   re-encode, accurate retention wording, no image or reply in logs [1, 2].
2. Danger words run before the LLM; chest-pain words never reach cardiac_surgery; "symptoms_only" enum; planned
   tiles carry "Chest pain or stroke now? Call 108" [3, 4].
3. If the note names a hospital, show it first with our evidence; never silently override the doctor [1].
4. Every model output is confirmed by the user; gemma is not used [3].

Emergencies
5. Call 108 on every emergency-profile screen, including GPS search and offline; the danger row is never a gate [5].
6. 108 first, then call ahead while waiting; "Do not wait for this call to send the patient" [10.1].
7. Crew fallback to the best public place always named; 112 as a small line [11].
8. Ride links in emergencies only after "Ambulance not coming or refused", with "A car has no medical crew"; cars
   only for labour and newborns [12].

Location and privacy
9. Place and its source echoed on every plan, card and slip; amber over 1,500 m, hold over 5,000 m, hold when the
   fix is older than 6 h until "Patient is here" [6].
10. "Is the patient here?" has no default in Compare and Area [6.2].
11. One last fix on the phone, up to 5 recent PINs, "Forget my locations"; coordinates rounded to 0.01 degree in POST
    bodies; uvicorn access log off; proxies send only rounded points [7].
12. No accounts, no patient names, no stored photos; the slip has a paper blank for the name [13, 21].

Confidence and wording
13. Quick: band word plus words, no decimals; "about the listing, not about today"; "very unsure" over 0.4 width;
    "too few checks" under n = 10; dev label until test [8].
14. No "chance at least one works" on Quick or the slip [8.3].
15. "Our data has no public evidence", never "does not offer"; why-not lines link to the sentence; Unlikely keeps a
    Call button [9].
16. Every private option says "private: may charge"; the best public option in reach is always listed [8.7].
17. Faithfulness failure shows the list without numbers, never a blank screen [8.8].

Calls and outcomes
18. tel: only after e164_india and the phone-trust check; identity check is line 1; no patient name on the call [10].
19. "Said yes on the phone, 14:05", never "confirmed"; outcomes beside the score, never inside; emergency "No
    answer" does not demote; Undo for 1 minute [10].

Sharing, offline, languages
20. Slip: no patient name or location, no decimals, made time and "call before going if more than a day old", "Ask
    the patient before sending"; the app never asks for or stores a recipient number [13].
21. Two dates on every offline answer; amber 30 days, red 90; fallback-model packs labelled demo data [15].
22. Offline HTML for the user's own phone only, with dates and hash; no forwarding in the pitch [16].
23. SMS bot demo only, number never shown, allowlisted [17].
24. No language ships unreviewed; Hindi shows "draft, not reviewed" until a native speaker checks the templates,
    script, checklist and danger words; no runtime LLM translation of actionable text [14].

Planner and demo
25. "No public evidence of care" instead of "care gap"; web-presence caveat on screen, CSV, brief and wall chart;
    wall chart prints "Replace by <date + 90 days>" [19].
26. Demo GPS switch exists only behind a server environment flag (404 when off); every screen and slip says DEMO
    LOCATION; in demo mode every facility tel: dials the team phone, labelled [20].

## 10. Build plan and demo script

### 10.1 Roles (4 people; with 3, C also takes D's tier-1 items)

| Person | Owns |
| --- | --- |
| A, backend and data | app.yaml, FastAPI, startup table load, /api/plan, /api/why, /api/resolve, plans_by_pin and pack precompute, faithfulness release test |
| B, Quick path front end | S1, S1b, S1c, S2, S3, S3x, S4, S4b, S6, S7, S8; strings files; axe gate |
| C, location and offline | GPS ladder, Permissions, IndexedDB, service worker, S1a, S9, S14, pack download and swap; deploys probe_app and runs phone tests |
| D, reasoning and depth | S5, S13 model card, S10 Compare, S11/S12 Area, call-question rules, Hindi templates, note scan and describe-it endpoints, demo prep |

### 10.2 First two hours (gate, before building on any untested platform behaviour)

1. C deploys feasibility/offline/probe_app as the second app slot and, on an Android phone: opens it online,
   reloads, airplane mode outdoors, reloads, taps the high-accuracy, low-accuracy and cached GPS buttons; repeats
   indoors. Opens out/referral_bihar.html from Downloads. Results arrive as PROBE_RESULT lines in the app log.
2. Same phone: tap_test.html from the actions folder (tel:, sms:, wa.me, Maps, Uber, Ola, intent:). Do not press
   Call, Book or Send. Repeat once from inside the deployed App.
3. A loads the prototype parquet files into the workspace schema and confirms the App can read them.
4. D adds judges as workspace users with CAN_USE (no anonymous access, [Cap]).
If the service worker fails on the real proxy, offline mode moves to the offline HTML copy (promote it to tier 1).

### 10.3 Cut lines

Tier 1 (never cut): GPS default with the full online and offline ladder; Change location for PIN, coordinates,
district, village; tiles and lexicon; inline danger row and the 108 rules; Quick plan with WHY card, why-not and
abstention; call script with tel: and outcome buttons; directions; slip by SMS and WhatsApp; state pack, service
worker and S9; faithfulness check; demo flag; axe gate.

Tier 2 (cut second): S5 HOW card; model card S13; Compare S10; note scan; weakest-term call questions; read aloud;
ride links behind the ambulance button; drop a pin; trust receipts; describe it in words.

Tier 3 (cut first among features): Area depth (S11) with the gap split and ten calls (S12, needs [Spec] 6.8 which is
"optional, cut second" and a fitted model); gap table; NFHS-5 context (point-in-polygon join only); print
stylesheet; referral record export; Maps link paste; offline HTML copy; hotspot points; outcome table write.

Tier 4 (stretch): SMS demo bot.

### 10.4 Order across the weekend

- Saturday: gate (10.2); A ships /api/plan on prototype rows; B ships S1-S4 against a static JSON; C ships the GPS
  ladder and pack in IndexedDB; D ships templates, call rules and Compare.
- Saturday night: tier 1 end to end on the phone, online and in airplane mode; axe gate on every state.
- Sunday morning: tier 2; regenerate every number from the fitted model; freeze strings.
- Sunday before judging: restart the App (24 h auto-stop, [Cap]); pre-run and cache demo queries and the note reply;
  demo flag on for the demo build only; release gates from Safety.

### 10.5 3-minute demo script

Setup: deployed App at its own URL on an Android phone mirrored to the screen, plus a laptop. Demo flag on, so the
phone reports "DEMO LOCATION: Singwahini, Sitamarhi" (a phone in Pittsburgh reports Pittsburgh); DevTools sensor
override as backup. Bihar pack already saved. Demo tel: links dial a teammate. The demo note is
feasibility/vision/images/01_referral_dialysis.png printed on paper.

- 0:00-0:15 "An ASHA in Sitamarhi has a patient whose PHC note says dialysis. Cheap phone, one bar."
- 0:15-0:40 App opens; GPS fills "Near Singwahini, PIN 843317" by itself. Scan the note: consent screen, photo,
  "We read: 'Refer to higher centre for dialysis'". Tap yes. Danger row: none.
- 0:40-1:05 Plan: first choice, two backups, CALL FIRST. "The nearest listing that mentions dialysis is 9 km away.
  Why is it not here?" Why-not: its dialysis sentence names another hospital, shown as ignored.
- 1:05-1:35 Option 1: "Say this to the family" plays in Hindi. WHY card: quotes with source pages, track record in
  words, the one sentence on why it beats the nearer government hospital. "Show the numbers": the points add up to
  the score; the app checks this before it renders.
- 1:35-2:00 Call ahead: the teammate answers "no slot today". Tap "Said no": backup 1 moves up and the script for it
  opens. Then the slip goes out by SMS with no decimals and the made time.
- 2:00-2:25 Airplane mode, reload. "No internet. Facility data from <date>. Saved 21 Nov." GPS from satellites (or the
  last fix at once), the same plan from the pack, and the call button still works because calls use the SIM.
- 2:25-2:50 Laptop, Area depth, trauma near the NH-19 point by Mohania (benchmark q29): the app abstains honestly,
  shows where calls could close the gap versus where there is no public evidence of care, and the ten calls to make.
  "This standing plan is the offline pack you just saw." If tier 3 was cut: show S3x abstention for q29 instead.
- 2:50-3:00 Model card: calibration, track record with n, baselines including an LLM judge that trusted a
  contaminated record. Close: "Every answer shows its evidence, how sure we are, and the one call to make."

Backup for the live parts: cached note reply (labelled), screen recording of the airplane-mode segment, and the
offline HTML copy.

## 11. Open questions and what was not tested

Open questions for the team
1. Road factor and speeds: decision layer to switch from 1.3 at 40-25 km/h to the measured 1.26 at 69-40 km/h?
   (5.5)
2. The fitted model: today 2 Likely pairs of 69,713 and Likely n = 0 on test (measured, [Proto]). If that does not
   change, the demo leads with abstention and "call to confirm", and the Area view's "access now" reads near zero.
   Decide by Sunday morning which demo query shows a Likely option.
3. Where call outcomes and referral records are written (a workspace table or Lakebase) and who can read them;
   delete after the hackathon? Write path not tested.
4. Who reviews the Hindi strings, call script, checklist and danger words? Without a reviewer, everything Hindi is
   labelled draft.
5. Uttar Pradesh pack is 228 KB gzip against the 150 KB target: accept, or split by region?
6. Marketplace terms on redistributing derived data (offline HTML, SMS bot): who reads
   https://cms.databricks.com/sites/default/files/2023-01/marketplace-consumer-terms_0.pdf?
7. Is the planner view worth building if [Spec] 6.8 is cut? Without it, Area shows only the standing plan per PIN.
8. Danger checklist wording: which official ASHA or NHM module to cite?

Killed ideas and why
- Photo of the patient's condition for self-triage: diagnosis, out of scope; models misread detail (palm vs back of
  hand) and severity (gemma called a scratch a deep laceration) [F-vision]; may make the app a medical device
  (Safety 2).
- "It does everything for you" from one photo, and auto-booking an Uber, auto or ambulance: Uber's request scope is
  privileged, Ola is invite-only, there is no public 108/102 dispatch API, and Chrome needs a user tap [F-actions].
- LLM chatbot, LLM-written explanations, LLM judge on the trust path: confidence 1.0 on contaminated records [Cap].
- Runtime direct LLM translation: broke a span in 4/4 runs [F-voice].
- Gemma-3-12b anywhere: obeyed an injected instruction 2/2, 3/11 calls hit 429, sent chest pain to trauma
  [F-vision], [F-voice].
- Custom Web Speech mic button and the faster-whisper fallback: online only on Android, untested, and keyboard voice
  typing in the text field does the same job with no code.
- Streamlit, Dash or Gradio front end: 1.0-1.5 MB per visit, 40-50 s to the first button on 2G, axe violations,
  no offline reload [F-a11y].
- Map-first results and a colour-only gap heat map: about 220 KB, dead offline, not accessible alone.
- A single 0-100 trust score: hides the three separate doubts (exists, where, offers).
- Referral Desk's "POSSIBLE" verdict: not a band in [Spec] 5.5.
- Pareto view: the compare table and the trade-off sentence say it more plainly.
- Live assumption sliders: invite tuning during the demo; assumptions are stated in words on the model card.
- Typed location as anyone's default: breaks the team rule.
- App link or QR code on the slip: no anonymous access to Apps [Cap].
- Continuous watchPosition online, and maximumAge as the last-known store: battery and privacy cost; the browser may
  evict the cache.
- District-sized packs: no saving, lose facilities across district lines.
- USSD and a live two-way SMS service this weekend: operator negotiation and DLT registration take days to weeks.
- Accounts, patient records, stored note photos, crowd ratings, separate apps per persona, dialysis .ics reminders
  and push notifications, bulk OSRM or Nominatim, district-name string joins to NFHS, separate text-size controls.

Not tested
- Anything on a real Android phone: GPS accuracy and offline time to first fix, indoor behaviour, the permission
  prompt on *.databricksapps.com, camera capture and crop, EXIF dropping, keyboard voice typing, Hindi
  speechSynthesis voice, every tel:, sms:, intent:, Uber, Ola and WhatsApp link, opening the offline HTML from
  Downloads, TalkBack, low-end phone performance.
- The service worker, manifest and session expiry on the real Databricks Apps proxy (only a local simulation passed).
- Model endpoint latency and 429 behaviour from inside the App and under several judges at once (laptop only).
- Ola drop-off without an affiliate token; Uber destination on Android; Rapido and Namma Yatri landing screens.
- Response compression behind the proxy; plan JSON size; repeat-visit size.
- Free Edition retention and training terms for pay-per-token endpoints; whether App logs are readable by other
  workspace users; Marketplace redistribution terms; CDSCO and DPDP applicability (secondary sources only).
- 102/108/112 roles per state (national NHM pages and Wikipedia only).
- Native-speaker review of any Hindi or Marathi string.
- The danger checklist against an official module.
- Writing call outcomes or records to a table from the App.
- Real phone audio, real handwriting, scripts other than Devanagari in the note scan (9 synthetic images, 1
  injection pattern).
