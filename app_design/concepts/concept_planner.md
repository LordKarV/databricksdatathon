# Concept: Setu, standing referral plans you can defend (planner lens)

Setu (Hindi for bridge) is one Databricks App with two inputs, a service and a location, and three depths of answer.
A field worker gets one place to go, a call script and a share slip. A coordinator gets a side-by-side
comparison and a printable record. A district planner gets an area-level standing referral plan: for every PIN in a
district or around a hotspot, the primary and fallback facility, travel time ranges, calibrated confidence, and a
split of the access gap into "we do not know" (data gap) and "there is nothing there" (care gap), plus the ten phone
calls that would close the most of the data gap.

Status: design only. Nothing here is deployed. Numbers marked (measured) come from a file or test named next to them.
Numbers marked (prototype) come from the current fusion prototype, model_hash 4e3dc4f12c451f98-fallback, which runs
on fallback features and is not the shipped model. Numbers marked (assumption) are policy knobs shown in the App.
Anything marked (not tested) has not been run.

## 1. Who uses it and what each one needs

| user | where they are | location they give | what they need back | depth |
| --- | --- | --- | --- | --- |
| community health worker, rural Bihar | standing with the patient, phone, weak or no data | GPS (default) | one place, why, the call to make first, 108/102, a slip for the family | Quick |
| NGO coordinator, Maharashtra | office or phone, elsewhere from the patient | GPS by default, usually changed to the patient's PIN, village or a dropped pin | 3 options side by side, trade-offs, a record they can file and forward | Compare |
| district planner | office laptop, online | GPS by default, usually changed to a district or hotspot coordinates | a standing plan per PIN, where evidence is weak, where care is missing, numbers that hold up in a meeting | Area plan |

The app never diagnoses. The user already knows the service. The photo feature reads a doctor's referral note to
fill the service field and nothing else.

## 2. The two-input flow

The whole product is two inputs and one "Find" tap. Depth is chosen after the answer, as tabs on the result
(Quick / Compare / Area plan), so nobody has to pick a persona before they see anything.

### 2.1 Service input

Three ways in, one confirmed result. The confirmed service is always shown as a chip with its source before any
search runs.

1. Tile grid (default, no model, demo-safe). Seven tiles, one per service the model scores: dialysis, emergency
   C-section, NICU (newborn intensive care), cardiac surgery, MRI, burn care, trauma and emergency. Each tile has an
   icon, a Hindi label in Devanagari and an English label (for example "dialysis / khoon saaf karna"). An eighth tile
   "Not sure / describe it" opens option 2.
2. Search box above the grid. Matches as you type against the lexicon synonyms in English, Hindi and Marathi
   (cleaning/claims/out/service_lexicon.csv, the same table the evidence layer uses), so "LSCS", "operation se
   delivery", "kidney machine" and "accident" all land on a tile. Pure string match, no model.
3. Describe it, by typing, keyboard voice typing, or the mic button. Free text goes to
   databricks-meta-llama-3-3-70b-instruct at temperature 0 with a strict json_schema whose service field is an enum.
   Measured: 36/36 correct over English, Hindi, Hinglish and Marathi, decisive phrase verbatim 36/36, median 876 ms
   (feasibility/voice_language). The answer is shown as a confirm chip: "Dialysis, because you wrote 'khoon saaf
   karwana'. Correct?" If the decisive phrase is not a substring of the input, or the service is "other", the grid
   opens instead. The mic uses webkitSpeechRecognition where it exists; on Android it is server-side and needs data
   (MDN compat data), so the mic button is hidden when offline. Gemma-3-12b is not used: it sent chest pain with a
   numb left arm to trauma.
4. Scan a referral note (camera icon in the search box). The photo is resized in the browser to about 1024 px,
   sent once to databricks-llama-4-maverick with a 15 s timeout, never stored. Measured: 9/9 correct services on
   documents, including a Hindi note and a degraded photo, and it resisted a prompt injection written into the image
   (feasibility/vision). A deterministic guard checks that the trigger phrase appears verbatim in the detected text
   and that the lexicon agrees. The confirm screen quotes the note: "We read: 'Refer to higher centre for dialysis'.
   Looking for: a dialysis centre." That quote is carried into the WHY card, so the chain of reasoning starts from
   cited text. Any 400, 429, timeout or guard failure falls back to the grid with no error page.

Red flags come from a fixed tap checklist on the Quick tab (heavy bleeding, breathing difficulty, unconscious, labour
with bleeding, chest pain, large or facial burn) plus a deterministic danger-word list over any typed text, never from
a model alone. Any tick puts a full-width "Call 108" button above everything else.

### 2.2 Location input (GPS is the default for every user)

Team rule, followed exactly: the location field is pre-filled from GPS for everyone, including the planner.
"Change location" is always visible directly under it as the second control on the screen, never hidden in a menu,
but it is never the default.

GPS call, on the user's first tap of "Use my location" (browsers ask for permission on a gesture, web.dev):
`getCurrentPosition({enableHighAccuracy: true, timeout: 15000, maximumAge: 600000})`. enableHighAccuracy must be
true: Chromium maps false to balanced-power positioning (Wi-Fi and cell), which needs data, while true asks the OS for
a satellite fix (LocationProviderGmsCore.java, feasibility/offline). The app saves {lat, lon, accuracy, time} itself
in IndexedDB on every fix, because the browser's own cached position is per page load and can be evicted (W3C
Geolocation spec). On later visits the saved fix is shown at once with its age while a fresh fix is requested.

The resolved place is echoed as text, never only as a dot: "Near Mohania, Kaimur (Bhabua), Bihar, PIN 821109.
GPS accuracy 40 m." The district comes from offline point-in-polygon on geoBoundaries ADM2 (ODbL), which is the
primary method; nearest PIN alone was wrong about 1 time in 8 (87.2% right over 1,972 points, 77% within 5 km of a
boundary, feasibility/geo_routing). Locality name and PIN come from the nearest post office (median 1.9 km away).
If accuracy is worse than 1,500 m the line says "approximate" and asks "Is this where the patient is?" with a PIN
box beside it.

"Change location" opens one sheet with five options, all resolved by the app and echoed back the same way:

| option | how it resolves | works offline |
| --- | --- | --- |
| PIN code (6 digits, numeric keypad) | India Post centroid, 19,584 PINs | yes (in the pack) |
| District | district list per state, then the district polygon; area plan uses all PIN centroids inside it | yes (names and centroids in the pack) |
| City, town or village name | Nominatim search with countrycodes=in, candidates listed with district and state, the user picks; "Muhra" alone matched Gaya and Damoh, so it never guesses | no; offline it searches post-office names in the pack (found 1 of 4 test names) |
| Coordinates | "25.1546, 83.6814" or degrees-minutes pasted from a crash report; validated inside India's bounding box | yes |
| Drop a pin | Leaflet map loaded on demand (about 220 KB first view) | no (tiles need data); offline this option is greyed with "needs internet" |

Planner extra on the same sheet: "Add another point" turns one point into a short list of hotspot points (for
example several blackspots along NH-19). The area plan then runs over that list instead of a district. This keeps the
two inputs: the location is still one field, it just holds one or more points.

GPS failure ladder (identical online and offline): fresh GPS fix, then the app's last saved fix of any age with
"from 3 days ago" shown, then the PIN or district picker with focus moved to it and a live-region message ("Could not
get location. Type the PIN code."). If permission is denied, the Permissions API switches the field to the PIN
picker on load, and GPS remains one tap away.

## 3. Screens

All wireframes are at phone width (360 px). The planner uses the same screens on a laptop, where Compare and Area plan
show as two columns.

### S0. Start (one screen, both inputs)

```
+------------------------------------------+
| Setu                       [EN | hi] [?] |
|  Where is the best place for this care?  |
|                                          |
|  1  Location                             |
|  +------------------------------------+  |
|  | (o) Near Mohania, Kaimur (Bhabua), |  |
|  |     Bihar  PIN 821109              |  |
|  |     GPS, accuracy 40 m, now        |  |
|  +------------------------------------+  |
|  [ Change location ]                     |
|                                          |
|  2  Service needed                       |
|  [ search: dialysis, LSCS, accident  (cam)(mic) ]
|  +--------+ +--------+ +--------+        |
|  |dialysis| |C-section| | NICU  |        |
|  |khoon   | |operation| |navjaat|        |
|  |saaf    | |se prasav| |ICU    |        |
|  +--------+ +--------+ +--------+        |
|  +--------+ +--------+ +--------+        |
|  | cardiac| |  MRI   | | burns  |        |
|  +--------+ +--------+ +--------+        |
|  +--------+ +-------------------+        |
|  | trauma | | Not sure? Describe|        |
|  +--------+ +-------------------+        |
|                                          |
|  [            Find               ]       |
|  Data saved 21 Nov 2026 | Online         |
+------------------------------------------+
```

Before the first GPS tap the location box shows one large button "Use my location (GPS)" with "Change location"
under it. Tile labels are icon plus word in both scripts; the wireframe shortens them.

### S1. Service confirm (after describe, voice or photo)

```
+------------------------------------------+
| < Back            Confirm the service    |
|                                          |
|  From the referral note you scanned:     |
|  "Refer to higher centre for dialysis"   |
|                                          |
|  We will look for:                       |
|  +------------------------------------+  |
|  |  DIALYSIS  (khoon saaf karna)      |  |
|  +------------------------------------+  |
|  [ Yes, search ]   [ Pick another ]      |
|                                          |
|  The photo was read once and not saved.  |
+------------------------------------------+
```

If the guard fails: "We could not read a service clearly. Please pick one." with the grid below.

### S2. Change location sheet

```
+------------------------------------------+
| Change location                      [x] |
|  [ Use GPS again ]                       |
|  ( ) PIN code      [ 6 digits      ]     |
|  ( ) District      [ state v ][ district v ]
|  ( ) Town/village  [ type a name   ]     |
|  ( ) Coordinates   [ 25.1546, 83.6814 ]  |
|  ( ) Drop a pin    [ Open map ]          |
|  [ + Add another point ] (area plans)    |
|                                          |
|  Using: Kaimur (Bhabua) district,        |
|  9 PIN areas, 1 hotspot point            |
|  [ Use this location ]                   |
+------------------------------------------+
```

### S3. Answer, Quick tab (field worker default)

The service here is trauma at the NH-19 hotspot (benchmark query q29). Facility names and numbers are from the
prototype (fallback model) and will change when the fitted model lands; they show the layout honestly, including the
case where nothing is verified.

```
+------------------------------------------+
| Trauma near Mohania (PIN 821109)         |
| [Quick] [Compare] [Area plan]            |
|==========================================|
| [ CALL 108  ambulance ]   (if red flag)  |
|------------------------------------------|
| ! No facility within 150 km has enough   |
|   public evidence that it treats trauma. |
|   Best options to call and confirm:      |
|------------------------------------------|
| 1  NOT VERIFIED - call to confirm        |
|    Sharda Hospital                       |
|    about 54 km by road, 47-81 min        |
|    (rough estimate)                      |
|    How sure: 0.49 (range 0.31-0.91)      |
|    "<quoted trauma sentence>" [procedure]|
|    [ Call first ] [ Why? ] [ Directions ]|
|------------------------------------------|
| 2  NOT VERIFIED  G. S. Memorial Plastic  |
|    Surgery Hospital And Trauma Center    |
|    about 92 km, 80-138 min  0.64         |
|------------------------------------------|
| Nearest listing (15 km) is Kush Eye Care:|
| not used, no trauma evidence, eye clinic.|
|------------------------------------------|
| Chance at least one works: 0.4x          |
| (assumes options fail independently)     |
| [ Share slip ] [ Read aloud ]            |
+------------------------------------------+
```

Prototype values for q29 (computed for this concept over pair_scores.parquet and facility_scores.parquet): 171
facilities within 150 km, 113 Unverified and 58 Unlikely for trauma, none Likely. Sharda Hospital is 42.6 km straight
line, P_S 0.49 (0.31 to 0.91), T = 4, bucket high. The nearest listing, Kush Eye Care at 14.8 km, is Unlikely with
P_S 0.11 and no trauma text. Road km above uses the measured circuity 1.26; the time range uses 69 to 40 km/h (see
section 5). P(at least one works) is computed by the decision layer and is left as "0.4x" here because the
prototype has not written plans yet.

Banding wording is fixed by the model spec: "LIKELY" only when the band rule holds; Unverified cards always begin
"NOT VERIFIED - call to confirm". Band is shown by word and shape (filled check, hollow circle, cross), never by colour
alone.

### S4. Recommendation card, expanded ("Why?")

This is the WHY and HOW for one recommendation. Every line is a template filled from one stored row; the source table
is in brackets on the developer build and hidden in the user build.

```
+------------------------------------------+
| < Sharda Hospital                        |
| NOT VERIFIED - call to confirm           |
|==========================================|
| WHY THIS FACILITY                        |
| Offers trauma care? Its listing says:    |
|  [procedure] "<own unit sentence 1>"     |  [claim_atoms.text, cited_atom_ids]
|  [capability] "<own unit sentence 2>"    |
|  Source: one of these 50 pages (list)    |  [record source_urls; no sentence-URL map]
| Is it real?  own website; mobile number  |  [existence contributions]
|  not shared with other listings          |
| Is it there? PIN, map point and city     |  [location votes]
|  agree within 3 km                       |
| What we ignored:                         |  [rejected_atom_ids, rejected_reason]
|  "<sentence>" - names another hospital   |
|------------------------------------------|
| HOW SURE                                 |
|  0.49, range 0.31 to 0.91                |  [p_s, p_s_lo, p_s_hi]
|  Track record for scores like this:      |  [band_record.parquet]
|  of 65 checked, 25 confirmed, 6 wrong,   |
|  34 no public info (dev, not final test) |
|  Without the 2 quoted sentences: 0.2x    |  [p_s_without_cited]
|------------------------------------------|
| HOW WE DECIDED  (points, 20 = 2x odds)   |  [pair_contributions]
|  start (hospital, beds 30-99)    -20     |
|  own text, 2 fields          +   38      |
|  record merges 50 web pages  -   27      |
|  no contamination found          0       |
|  prerequisites (ICU, OT)     +    8      |
|  total                       =   -1  ->0.49
|  Band rule:  [ ] P_S >= 0.70  [x] T >= 2 |
|              [x] P_L >= 0.70 [x] P_E>=0.70
|------------------------------------------|
| DISTANCE                                 |
|  42.6 km straight, x1.26 = 54 km road    |
|  47-81 min (69 to 40 km/h, rough)        |
|  Road check: OSRM 51 km, 44 min (free    |
|  flow, optimistic)          [if online]  |
|------------------------------------------|
| WHY NOT THE OTHERS                       |
|  Kush Eye Care, 15 km: eye clinic, no    |
|   trauma sentence (Unlikely, 0.11)       |
|  Ghazipur Nursing Home, 49 km: farther   |
|   and no cited own unit (T < 2)          |
|  (a nearer-but-ranked-lower option gets  |
|   the exact ratio sentence, 6.7 of spec) |
|  [ Show all 171 within 150 km ]          |
|------------------------------------------|
| If a call confirms option 2, it would    |
| rank first. Most useful call: option 2.  |
+------------------------------------------+
```

The waterfall rows are illustrative: the real ones come from pair_contributions.parquet. The point values sum
exactly to the logit; the prototype's additivity test passes on all 69,713 pairs with a maximum error of 8.9e-16
(model/proto/fusion/tests_report.json, measured). The track-record line is the current dev out-of-fold record for the
Unverified band (65 pairs: 25 confirmed, 6 contradicted, 34 no info, band_record.parquet, measured) and is labelled
"dev, not final test" until the sealed test runs. When a band has fewer than 10 checked pairs (the Likely band has 2
today), the line says "too few checks to give a track record (2 checked)" instead of a percentage.

"Why not the others" has two kinds of line, both computed:

- Excluded nearby: the band and the band_reason the model stored ("eye clinic: scope conflict", "the dialysis
  sentence names Nair Hospital, Mumbai", "PIN and map point say Mumbai, name says Nagpur").
- Outranked but nearer: the exact identity from the spec, U_A / U_B = (evidence ratio) x (location and distance
  ratio), printed as one sentence with both factors. The App recomputes U and the order from the numbers on screen
  and refuses to render if they disagree (model spec 7.4).

### S5. Compare tab (coordinator)

```
+-------------------------------------------------------------+
| Trauma near Mohania       [Quick] [Compare] [Area plan]     |
|-------------------------------------------------------------|
|                 | 1 Sharda      | 2 G.S. Memorial | 3 Dr.Asia|
| band            | not verified  | not verified    | not ver. |
| how sure        | 0.49 .31-.91  | 0.64 .37-.96    | 0.28     |
| road km / min   | 54 / 47-81    | 92 / 80-138     | 71 / ... |
| own evidence    | 2 fields      | 3 fields, unit  | 1 unit   |
| ignored text    | none          | none            | none     |
| record merges   | 50 pages      | 12 pages        | 4 pages  |
| location agree  | yes, 3 km     | yes             | yes      |
| phone           | own mobile    | landline        | shared?  |
| public / private| private       | private         | private  |
| free under JSSK | no            | no              | no       |
| best if         | nearest with  | strongest text  |          |
|                 | real text     |                 |          |
|-------------------------------------------------------------|
| Outside option: nearest district hospital in our data:      |
| <name>, 38 km. The public standard says it should handle    |
| emergencies; not verified in our data.                      |
|-------------------------------------------------------------|
| [ Print / save PDF ]  [ Share on WhatsApp ]  [ Copy text ]  |
+-------------------------------------------------------------+
```

Cells for option 3 and the outside option name are placeholders. The "best if" row comes from the Pareto view for
elective services (not dominated on P_succ and distance) and states the one axis each option wins on.

### S6. Area plan tab (planner)

Input: a district, a list of hotspot points, or the current point with a radius. The plan is computed per PIN
centroid inside the district (or per hotspot point) and is precomputed for all districts and services, so it opens
in under a second (target).

```
+-------------------------------------------------------------+
| Standing referral plan: TRAUMA                              |
| Kaimur (Bhabua), Bihar | 9 PIN areas + 1 hotspot (NH-19)    |
| [Quick] [Compare] [Area plan]   service [trauma v]          |
|=============================================================|
| HEADLINE                                                    |
| 6 of 9 PIN areas have no trauma candidate within 60 min.    |
| None has a verified one.                                    |
|                                                             |
| Access within 60 min (P at least one works)                 |
|   now                     0.11 avg  [##........]            |
|   if calls confirm        0.22 avg  [####......]            |
|   data gap   0.11  (a phone call can close this)            |
|   care gap   0.78  (no candidate at all; calls cannot fix)  |
|-------------------------------------------------------------|
| PLAN BY AREA                       primary      fallback    |
| PIN 821109 Mohania  (hotspot)      Sharda 47-81  G.S. 80-138|
|                                    0.49 NV       0.64 NV    |
| PIN 821101 Bhabua                  <name> ...    <name> ... |
| PIN 821105 ...                     none in 60 min: nearest  |
|                                    candidate 96 km           |
| ... 6 more                         [ show all ]             |
|-------------------------------------------------------------|
| WHERE THE EVIDENCE IS WEAK                                  |
|  4 facilities carry the plan; all are NOT VERIFIED          |
|  2 rely on records that merge 30+ web pages                 |
|-------------------------------------------------------------|
| [ Map ] [ Verification calls ] [ Gap matrix ] [ Brief ]     |
| Assumptions: 60 min, 40 km/h low speed, x1.26 road factor,  |
| confirmed call = 0.95  [ change ]                           |
+-------------------------------------------------------------+
```

Prototype values for Kaimur trauma (computed for this concept): the PIN gazetteer has 9 Kaimur (Bhabua) PINs; at
1.26 x straight line and 40 km/h, 6 of 9 have no non-Unlikely trauma candidate within 60 minutes; mean P(at least
one works) is 0.11 now and 0.22 if every candidate with own text (T >= 2) were confirmed by a call (confirmed set to
0.95, assumption). These are fallback-model numbers and only show the shape of the output.

How the area numbers are defined (all exact, no extra model):

- For PIN area x and service s, candidates are non-Unlikely facilities within the time budget at the low speed.
- access(x) = 1 - prod over candidates (1 - P_E P_S P_L). This is P(at least one works), under the stated
  independence assumption, with members of one leakage group merged first so copied records count once.
- upper(x) = the same with P_S set to 0.95 for every candidate with T >= 2 (own text exists, so a call can
  plausibly confirm it). The assumption 0.95 is a knob.
- data gap(x) = upper(x) - access(x); care gap(x) = 1 - upper(x). The headline is the population-free mean over PIN
  areas. NFHS-5 district indicators are shown next to it as context, never mixed into the score (Kaimur (Bhabua):
  institutional births 83.3%, births by C-section 7.4%, measured from the NFHS-5 parquet).
- Expected providers per district = sum of P_E P_S P_L, with P(none) from the exact Poisson-binomial (model spec 6.8).

The care gap carries a permanent caveat line: "Our data comes from web pages. Government facilities with little web
presence may exist and not appear here. A care gap here means no evidence, so check the state facility list before
acting." This is the single most important sentence for a planner, because a missing CHC looks exactly like a gap.

### S7. Verification calls (planner)

```
+-------------------------------------------------------------+
| 10 calls that close the most of the data gap (trauma)       |
| Kaimur (Bhabua) + NH-19 hotspot                             |
|-------------------------------------------------------------|
| #  facility               phone        areas  access gain   |
| 1  G.S. Memorial ...      landline      4     +0.06         |
| 2  Sharda Hospital        own mobile    3     +0.04         |
| 3  ...                                                      |
|-------------------------------------------------------------|
| Script for each call [ open ]                               |
| Record outcome:  [Yes, they can] [No] [Could not reach]     |
|   Recorded outcomes show on cards as "Confirmed by phone,   |
|   23 Nov, by <role>". They do not change the model score.   |
| [ Send this list on WhatsApp ]  [ Download CSV ]            |
+-------------------------------------------------------------+
```

Gain for facility j = sum over PIN areas of (access with j confirmed at 0.95) - (access now), divided by the number
of areas. This is the planner version of the spec's "if a call confirms B it ranks first" counterfactual. Call
outcomes are stored as a separate, dated, human witness in an app table (build phase, not tested) and displayed
beside the model score, never inside it, because the spec keeps the model deterministic and sealed.

### S8. Gap matrix (planner, one district or a whole state)

```
+-------------------------------------------------------------+
| Gaps: Bihar, by district x service   [ access within 60 min]|
|               dial  CS   NICU  card  MRI  burn  trauma      |
| Kaimur        D 0.2 C .. D ..  C ..  .. C ..   D 0.11       |
| Patna         V .9  V .. ...                                |
| ...                                                         |
| Legend: V verified access  D data gap dominates             |
|         C care gap dominates  (letters, not only colour)    |
| [ Sort by care gap ] [ Table / CSV ]                        |
+-------------------------------------------------------------+
```

Each cell is a link to S6 for that district and service. Cells carry a letter plus the number so the matrix works
for screen readers, greyscale printing and colour-blind readers. Districts come from point-in-polygon, not name
matching: the dataset's "Balasore" is "Baleshwar" in NFHS-5 (measured), so a string join would drop it silently.

### S9. Meeting brief (export, planner and coordinator)

One A4 page, made with the browser's print-to-PDF from a print stylesheet, so no PDF library.

```
+-------------------------------------------------------------+
| Standing referral plan: trauma, Kaimur (Bhabua), Bihar      |
| Prepared 21 Nov 2026 | data snapshot <date> | model <hash>  |
|-------------------------------------------------------------|
| Plan by PIN area (primary, fallback, minutes, confidence)   |
| Evidence for each named facility (2 quotes, field, source)  |
| Ignored evidence and why                                    |
| Access, data gap, care gap, with the definitions            |
| Verification calls and their outcomes so far                |
| Assumptions: speeds, road factor, time budget, 0.95         |
| Known limits: web-derived data; government facilities may   |
| be missing; travel times are estimates, not measured trips  |
| How the score works: 1 paragraph + link-free method note    |
+-------------------------------------------------------------+
```

The brief is the "holds up in a meeting" artefact: every number on it has its definition and source on the same
page, and the model hash plus data snapshot date let someone reproduce it later.

### S10. Call ahead (all users)

```
+------------------------------------------+
| Call Sharda Hospital first               |
|  [  Call +91 9xxxx xxxxx  ]              |
|  Number looks like the hospital's own    |
|  Ask:                                    |
|  1 Is this Sharda Hospital in <town>?    |
|  2 I have a patient who needs trauma care|
|  3 Is a surgeon on duty now? Is the OT   |
|    free? Is there blood?                 |
|  4 If you cannot, which hospital can?    |
|  5 Whom do we ask for when we arrive?    |
|  After the call:                         |
|  [Yes, they can] [No] [Could not reach]  |
|  No -> shows the fallback, already ranked|
+------------------------------------------+
```

Script text comes from SERVICE_QUESTIONS in feasibility/actions/links.py. The call button appears only when the
number passes links.e164_india (9,448 of 10,088 phones are dialable; 76 are refused, including one '100', the
police number, measured) and is not a directory number shared by 3+ cities.

### S11. Offline answer (any user, no data connection)

```
+------------------------------------------+
| OFFLINE - answers from saved data        |
| Saved 21 Nov 2026 (3 days ago)           |
|------------------------------------------|
| Location: GPS (satellite), 25 m, now     |
|   [ Change location: PIN / district ]    |
| Service: DIALYSIS                        |
|------------------------------------------|
| [ CALL 108 ]  [ CALL 102 ]               |
| 1  <facility>  ~23 km straight line      |
|    LIKELY 0.8 | "<quote>" [equipment]    |
|    [ Call first ]  [ SMS slip ]          |
| 2  <backup>    ~31 km                    |
| 3  <backup>    ~40 km                    |
|------------------------------------------|
| Distances are straight line; times need  |
| internet. Phone numbers may have changed.|
| Map, voice and photo need internet.      |
+------------------------------------------+
```

The saved date turns amber after 30 days and red after 90 with "phone numbers may have changed".

### S12. How we decided (model card page, judges and planners)

```
+-------------------------------------------------------------+
| How Setu decides                                            |
| 1 Funnel: 10,088 rows > 9,959 records > 69,713 pairs        |
|   > 7,300 with a service sentence > bands                   |
| 2 Evidence rules: whose sentence is it? (examples, n)       |
| 3 Weights table: prior, learned, 90% interval, sign         |
| 4 Calibration plot with Wilson bars (test, once sealed)     |
| 5 Track record per band: confirmed / wrong / no info        |
| 6 Baselines: nearest mention, keyword count, rule grade,    |
|   LLM judge; ours vs each with 95% intervals                |
| 7 Knobs: speeds, road factor, radii, thresholds [sliders]   |
| 8 Two failures walked through: Aravind Eye Hospital         |
|   "offers dialysis", Wockhardt Nagpur with Mumbai sentences |
| 9 Versions: data hash, model hash, labels hash, test date   |
+-------------------------------------------------------------+
```

Sliders re-rank live and show what changed: "With 25 km/h instead of 40, PIN 821105 loses its only candidate."

## 4. How the reasoning for each recommendation is backed by data

| question a user or judge asks | what the card shows | source of every value |
| --- | --- | --- |
| Does it exist? | own website or not, phone class, number of sources | facility_contributions (existence head), existence_signals |
| Does it offer this service? | up to 3 quoted own sentences with field labels, "one of these pages" sources | claim_atoms.text, which must equal the raw parquet item (build fails otherwise) |
| Could the text be someone else's? | "What we ignored" list with reason | rejected_atom_ids, rejected_reason |
| Is it where we think? | which location witnesses agree, conflicts named | facility_contributions (location head) |
| How sure? | P_S with 5th to 95th percentile range, band word | pair_scores |
| Can I trust that number? | three-outcome track record with N, dev or test label | band_record.parquet with labels hash |
| How was it scored? | points waterfall that sums exactly to the logit, band checklist | pair_contributions, tests_report.json (additivity passes, measured) |
| What if the quotes are wrong? | "Without the quoted sentences: 0.2x" | p_s_without_cited |
| How far, how long? | straight km, road km with factor, minutes range, optional OSRM check, source label | section 5 |
| Why not the nearer one? | one exact sentence with both ratios, or the stored exclusion reason | U factors, band_reason |
| What is the most useful call? | "If a call confirms option 2, it ranks first" | live counterfactual |
| What did a human find? | "Confirmed by phone, date, role", separate from the score | call outcome table |

No LLM writes or rewrites any rationale (model spec 7.4). Hindi cards come from Hindi templates with numbers inserted
by code. Where an LLM translates (Marathi and others), facility names, quotes and numbers are swapped for
placeholders first; that passed 4/4 automated verbatim checks, while direct translation failed 4/4
(feasibility/voice_language). Quotes stay in their original language as the citation.

## 5. Distance and travel time

- Straight line from the user to the facility's resolved point p1 (and p2 when the location head is unsure).
- Road km = straight km x 1.26. Measured median circuity over 50 rural Bihar OSRM pairs, 95% CI 1.23 to 1.34
  (feasibility/geo_routing). This replaces the spec's assumed 1.3 and the decision proposal's 1.4. Leave-origin-out
  error 16.5% MAPE, worst across rivers (1.64 to 1.73).
- Minutes shown as a range at 69 km/h (OSRM free-flow median, optimistic) to 40 km/h (assumption), labelled
  "rough estimate". Ranking does not separate options whose times differ by less than about 20%, and the card says
  "about the same distance" instead.
- Online and optional: one OSRM table call for the top 3 to 5 options only, 3 s timeout, cached, shown as a second
  line "Road check: OSRM 51 km, 44 min (free flow)". Measured 307 to 338 ms for a 1x10 table. Never bulk-queried:
  area plans use the factor, not OSRM, because 19,584 PIN calls would break the demo server's terms.
- Offline: straight line only, labelled as such, times hidden.

## 6. Actions

| action | how | offline | tested |
| --- | --- | --- | --- |
| Call ahead with script | tel: link through links.e164_india, script screen S10, outcome buttons | yes (uses the SIM) | link builders self-check passes; real phone not tested |
| Call 108 / 102 / 112 | tel:108, tel:102 next to it for pregnancy and infants (JSSK), 112 as the integrated number | yes | numbers from NHM pages and Wikipedia; per-state check not done |
| 108/102 note | "Ask the crew to take you to A. If they cannot, the best public facility in reach is B." Dispatch picks the nearest centre and 102 carries to government facilities | yes | from NHM text, not field-tested |
| Directions | Google Maps dir link with destination coordinates, or "name, town" when location is unsure | needs data in Maps | documented; not tap-tested |
| Ride | Uber /looking?drop[0]= and Ola universal link with drop coordinates, car categories only for labour or a sick newborn; ride links always sit below the ambulance button for emergency services | no | probes returned 200/302 with params kept; Ola drop-off without affiliate token not tested |
| Share referral slip | WhatsApp wa.me/?text= and sms:?body= with a self-contained text: facility, address, Maps link, phone, call questions, why in one line, saved date. No app link, because Apps have no anonymous access | yes for SMS | encoding self-check passes; Android not tested |
| Print / PDF | browser print of S5 or S9 | yes once loaded | not tested |
| Download offline copy | single-file HTML with the state pack embedded (Bihar 112 KB gzip), shareable as a WhatsApp document | yes | works from file:// in desktop Chromium; Android not tested |
| Planner: send call list | WhatsApp text or CSV of S7 | yes for text | not tested |

Booking a ride or an ambulance through an API is killed (section 10).

## 7. Offline mode (the exception to GPS-only-online)

GPS stays the default offline. What still works with no data connection, and what does not:

| part | offline behaviour | evidence |
| --- | --- | --- |
| GPS | works: satellite fix through the OS when enableHighAccuracy is true. First fix may take 2 to 4 minutes cold; the screen says "Stand outside, up to 2 minutes" with "Choose place instead" one tap away | Chromium source; time to first fix not measured on a phone |
| Network location | does not work (needs Wi-Fi/cell lookup over data) | Chromium source |
| Location fallback | last saved fix (any age, shown), then offline PIN picker, then district then post office (9,058 Bihar post offices in the pack) | tested in a local browser simulation |
| App shell | service worker, network-first for pages, cached shell on network error or status >= 500 | tested in a simulated cookie proxy; real Databricks proxy not tested |
| Data on the phone | referral pack per state: for every PIN and service, the decision layer's top pick and 2 backups, band, P_S and range, track-record line, 2 shortest own quotes with claim ids and source URL, call-first number with phone trust, Hindi names, call script template, snapshot date and model hash | Bihar pack plus picker measured at 110 KB gzip, 196 KB in IndexedDB; all India 1.85 MB gzip |
| Pack download | in the background after the first online answer for the state of the first GPS fix; planners and coordinators can choose "all India" | design |
| Refresh | on every online open, fetch /api/pack/version; if snapshot + model hash changed, download in the background and swap in one transaction; never block | design |
| Ranking offline | uses the precomputed per-PIN plan for the nearest PIN to the fix, then re-sorts the pack's candidates by straight-line distance from the actual fix | tested with an unfiltered pack, which put a dental clinic second; the real pack is filtered by service |
| Area plan offline | the planner's last viewed district plans are saved with the pack; the gap matrix is not | design |
| Voice, photo, map, OSRM, Nominatim, describe-it | hidden or greyed with "needs internet" | by design |
| No-internet channels | tel:, sms: and WhatsApp share links use the SIM. A demo SMS bot (team Android phone running android-sms-gateway, Apache-2.0, answering "DIALYSIS 842001" from the pack via sms_reply.py) is shown as a demo, not a service | reply formatter tested (310 characters, 3 segments); phone bot not tested. Real two-way SMS needs DLT registration through an Indian entity: roadmap |

Offline detection does not trust navigator.onLine alone: a failed or slower-than-8-s API call also switches the
banner. fetch with redirect: 'manual' tells "session expired" from "offline" (tested in the simulation).

## 8. Accessibility

Target WCAG 2.2 AA, gated by axe-core with zero violations in every state (start, locating, results, GPS denied,
offline, area plan), reusing feasibility/accessibility/measure.py and offline_test.py. The FastAPI plus plain HTML
probe had 0 violations; Streamlit, Dash and Gradio each had 3 rule types (measured).

- Targets at least 48 x 48 CSS px, nothing under 24 x 24 (WCAG 2.5.8).
- Contrast 4.5:1 for text and 3:1 for UI, light and dark.
- lang on html and on every Hindi or Marathi string; Noto Sans Devanagari as a system-font fallback, no downloaded
  web fonts.
- Status messages in a role=status live region; focus moves to the next input on failure.
- Bands, gap letters and confidence never rely on colour: word, shape icon and number every time.
- Charts (waterfall, access bars, calibration plot) each have a table alternative directly below them; the gap matrix
  is a real HTML table.
- The map is optional and never the only place information appears; every marker has a unique title.
- Reflow at 320 px and 200% text; prefers-reduced-motion honoured; no time limits.
- Low literacy: icon plus word on every action, one decision per screen on the Quick tab, Western digits with units
  ("54 km", "47-81 min"), a Read aloud button using speechSynthesis only when a voice exists for the language. NFHS-5
  women's literacy is under 60% in 96 districts (measured), which is why Quick never needs reading a paragraph.
- Languages: English and Hindi templates at launch; Marathi through placeholder-protected translation; others
  later. Hindi is the first language of about 44% of people, so the language switch is on every screen.
- Low bandwidth budget: critical path to the location button 50 KB or less in 5 requests, no third-party hosts; a
  results response 20 KB of JSON or less; repeat visits about 5 KB through the service worker; map and Leaflet only
  on "Map". The FastAPI probe showed the first button in 0.44 s on the 2G profile versus 44 s for Streamlit
  (measured, emulated).
- One known gap: the Databricks workspace sign-in is outside our control, so WCAG 3.3.8 cannot be claimed for it.

## 9. Creative features

1. Data gap versus care gap. The planner's headline separates "we do not know" from "there is nothing there", with
   exact definitions, so a district meeting argues about the right thing: make calls, or build capacity.
2. Ten calls that close the most gap. A ranked verification list with access gain per call, a script, and outcome
   buttons. Outcomes become dated human witnesses shown next to (not inside) the score.
3. Hotspot points as a location. A planner pastes crash coordinates or drops several pins; the standing plan runs
   over them. Still one location field.
4. Why-not lines that are arithmetic (illustrative numbers). "B is 7 km nearer; distance favours B 1.3x; A's evidence is 2.0x stronger, so
   A ranks first." The App refuses to render if the displayed numbers do not reproduce the order.
5. "What we ignored." Contaminated sentences are shown with the hospital or place they actually name, so a user sees
   why the eye hospital's dialysis claim did not count.
6. Referral note as input. Photograph the doctor's slip; the quote from the slip becomes line one of the reasoning.
7. Meeting brief with a reproducibility stamp (data snapshot, model hash, labels hash, assumptions).
8. Live assumption sliders that state what changed in plain words.
9. Offline standing plan: the planner's district plan travels with the field worker's phone and the printed brief
   goes on the control-room wall.
10. Public-facility fallback for 102/108: the plan always names the best public option the ambulance can take.

## 10. Ideas killed and why

| idea | why it is killed |
| --- | --- |
| Photo of the patient's wound or burn to triage | Users are intermediaries; the app does not diagnose. Both vision models misread detail (back of hand called palm) and gemma overcalled severity (feasibility/vision) |
| Auto-calling an Uber or auto for the patient | Uber's request scope is privileged, Ola is invite-only, Chrome will not launch an app without a tap; an emergency should get 108, not a car |
| Ambulance booking via API | no public 108/102 dispatch API found |
| LLM-written explanations or an LLM judge on the trust path | llama-3-3-70b said "offers dialysis, confidence 1.0" for contaminated records; trust and text stay deterministic |
| Chatbot as the main interface | slower, unbounded, and its answers cannot be checked line by line against stored rows; the free-text box covers the useful part |
| Streamlit | 1.25 MB per visit, 44 s to first button on 2G, no offline reload, critical axe violations in its own chrome (measured) |
| QR code or link to the App on the slip or brief | Apps have no anonymous access, so family and other offices cannot open it; the slip is self-contained text |
| Heat map as the gap view | colour-only, unreadable to screen readers and in print; replaced by a lettered table with numbers |
| District-name string joins for NFHS | Balasore is Baleshwar in NFHS-5; point-in-polygon instead |
| Bulk OSRM or Nominatim for area plans | demo-server terms; one shared AWS IP; the measured factor is good to about 17% |
| Live "minutes" without a range | OSRM is free flow at a 69 km/h median and there are no ground-truth trips |
| USSD | negotiated with operators, not feasible this weekend |
| Crowd ratings of hospitals | no users yet, easy to game, and nothing to calibrate them against |
| Separate apps per persona | same two inputs serve all three; depth tabs after the answer are enough |
| gemma-3-12b anywhere on the path | obeyed an injected instruction 2/2, misrouted a heart attack, 429s on sequential calls |

## 11. Tech stack

- Databricks App, FastAPI (pre-installed, 0.115) serving one hand-written HTML page, vanilla JS, a print stylesheet,
  a web manifest (crossorigin=use-credentials) and a service worker at the app root. JSON endpoints: /api/answer,
  /api/area, /api/card, /api/pack/version, /api/pack/{state}, /api/map-service (LLM mapping), /api/scan.
- Data: the evidence, fusion and decision outputs (pair_scores, pair_contributions, facility_scores,
  facility_contributions, claim_atoms, band_record, weights, calibration) copied to Delta in one Unity Catalog schema
  during the build phase, read once at start through the SQL warehouse, held in memory with numpy and pandas
  (2 vCPU, 6 GB). Ranking, U, plans and cards are computed in memory.
- Precompute (notebook, build phase): per PIN and service plans for all 19,584 PINs, per district area metrics,
  verification lists, gap matrix, state packs. About 195 million haversine pairs per service in numpy (estimate,
  not run).
- Geo: geoBoundaries ADM2 (ODbL, 8 MB simplified) for point-in-polygon, India Post centroids and post offices,
  in memory on the server and in the pack.
- Map: Leaflet 1.9.4 from cdnjs with OSM tiles, on demand, attribution visible.
- Models: databricks-meta-llama-3-3-70b-instruct for free-text mapping and placeholder translation;
  databricks-llama-4-maverick for referral-note photos. Neither is on the trust path.
- Server speech fallback only if Web Speech is missing: faster-whisper small int8 in the container (Hindi CER 0.13
  to 0.21 on clean synthetic clips, measured on a laptop; not tested in the container).
- Call outcomes: an app table written through the warehouse (build phase; not tested).

## 12. Internet dependencies and fallbacks

| dependency | needed for | fallback | status |
| --- | --- | --- | --- |
| Databricks App server and login | online answers, area plans | cached shell plus state pack; single-file offline HTML | proxy behaviour untested |
| SQL warehouse | loading tables at start | none needed at query time (in memory) | design |
| GPS satellites | default location | last saved fix, PIN picker | no data needed (source code); TTFF not measured |
| Nominatim | village search, friendlier place names | offline post-office names; PIN | tested reachable from the App network |
| OSRM demo server | road check for top 3 to 5 | x1.26 factor range | tested reachable |
| OSM tiles | map and dropped pin | list view; PIN or coordinates | tested reachable |
| Llama 3.3 70B endpoint | describe-it mapping, translation | tile grid; English card | measured 36/36 |
| Maverick endpoint | referral-note scan | tile grid | measured 9/9 on documents |
| Web Speech (Google servers on Android) | mic | typed text, keyboard voice typing | not tested on a phone |
| Phone network (SIM) | calls, SMS slip | none needed | works without data by nature |
| WhatsApp | share slip | SMS | not tested |

data.gov.in and hospitals.pmjay.gov.in are unreachable from the App (no route or timeout, measured), so nothing
depends on them at runtime.

## 13. How it scores

Creativity. The gap split, the verification-call list with access gain, hotspot points as a location, arithmetic
why-not lines, "what we ignored", and the referral-note-as-first-citation are not features a generic facility search
has. The offline state pack makes the planner's plan usable by the field worker without data.

Modeling. The planner view adds no new model: it aggregates the glass-box scorecard's calibrated P_E, P_S and P_L
with exact, stated formulas, so every district number decomposes into facility cards and then into quoted
sentences and points. The scorecard is additive to 1e-15 on all 69,713 pairs and passes the deletion and
monotonicity tests (measured, prototype). Track records come from a sealed test with three outcomes and Wilson
intervals, against baselines B0 to B5 including an LLM judge. The design shows uncertainty everywhere a number
appears, and says "too few checks" when that is the truth.

Impact. One app serves the three users the brief names at the depth each needs. It works without data, in Hindi,
with icon-and-word controls, and hands the user an action (a call with a script, 108 with the public fallback, a
slip). For a planner the output is a decision: which ten facilities to verify this week, and which areas have no
care at all.

## 14. Three-minute demo story

0:00 to 0:20. The problem. "A district planner in Kaimur, Bihar wants to know where to send trauma cases from crashes
on NH-19 near Mohania. Our data lists 171 facilities within 150 km. The nearest is 15 km away. It is an eye clinic."

0:20 to 0:50. Two inputs. On the laptop the location is already filled by GPS (her office). She taps "Change
location", pastes the hotspot coordinates 25.1546, 83.6814 from a crash report, and the app echoes "Near Mohania,
Kaimur (Bhabua), Bihar, PIN 821109". She taps the trauma tile. Find.

0:50 to 1:30. The answer is honest. "No facility within 150 km has enough public evidence that it treats trauma."
The best option to call is shown as NOT VERIFIED with 0.49 (range 0.31 to 0.91), two quoted sentences, the points
waterfall, and why the eye clinic was not used. One tap on "Why?" shows the band checklist and the track record.

1:30 to 2:10. Area plan. She switches to the Area plan tab for Kaimur: 6 of 9 PIN areas have no trauma candidate
within 60 minutes. Data gap 0.11, care gap 0.78. The ten-call list names the facility whose confirmation helps most.
She opens its call script, and we press "Yes, they can" on a pre-recorded call: the card now reads "Confirmed by phone,
today" next to the unchanged model score, and the area plan updates.

2:10 to 2:35. The field worker. On a phone in airplane mode, the same app opens from the service worker: "OFFLINE,
saved 21 Nov". GPS gives a satellite fix (or the PIN picker if indoors); dialysis; three options with quotes, Call
108, Call first, and an SMS slip that needs no app.

2:35 to 3:00. Why trust it. The model card: every point sums to the score, every quote equals the raw record, the
Aravind Eye Hospital "dialysis" claim is shown as caught, and the track record is from a sealed test. Close on the
printed meeting brief with its model hash.

Demo safety: pre-run the demo queries and cache their answers and the scan reply; restart the App before judging;
judges must be added as workspace users; the offline copy HTML is the backup if the real proxy breaks the service
worker. The Kaimur numbers above are from the fallback prototype and must be regenerated from the fitted model before
the demo.

## 15. Risks

- The current prototype bands almost everything Unverified or Unlikely (only 2 Likely pairs across 69,713, prototype),
  so the demo may show "nothing verified" everywhere. The design handles that honestly, but the area plan's
  "verified access" will read as zero until the fitted model and more gold labels land.
- Care gaps are confounded with missing web presence: government CHCs and PHCs are thin in a web-scraped dataset.
  The caveat line and the outside option reduce, not remove, this.
- Area access assumes facilities fail independently except within a leakage group; correlated failures (one
  surgeon covering two hospitals) are not modelled.
- Travel times are factor-based ranges from 50 rural Bihar pairs; hills, the North East and river crossings are
  worse. No ground-truth trip times exist.
- Not tested on a real Android phone or inside the deployed App: geolocation prompt, offline GPS time to first fix,
  service worker on *.databricksapps.com, tel:/intent: from the App, mic permission, camera capture.
- The PIN gazetteer has only 9 PINs for Kaimur (Bhabua) and some centroids are placeholder points shared by several
  offices, so area plans at PIN grain are coarse; a 10 km grid (491 cells for Bihar, 47 KB gzip, measured) is the
  alternative.
- Call outcome storage needs a writable table during the build phase and has a privacy rule: store role and date,
  never patient data.
- Publishing packs and offline HTML outside the App redistributes data from a Marketplace share; the terms were not
  checked.
- Emergency numbers 108, 102 and 112 were checked against national NHM pages and Wikipedia, not per state.
