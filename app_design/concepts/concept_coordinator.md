# Concept: Referral Desk (coordinator lens)

Status: design concept, nothing built. Every claim about what works points to a feasibility test in
/Users/karthikvattem/projects/datathon/app_design/feasibility/ or a doc URL listed there. Anything else is marked
"not tested". Model terms (P_E, P_S, P_L, U, band, track record, leakage group) follow
/Users/karthikvattem/projects/datathon/model/design/MODEL_SPEC_v1.md.

## 1. One sentence

Referral Desk is one Databricks App that answers "where should this patient go for this service, from here, and
why", at three depths: a quick answer for the field worker, a side-by-side comparison with a signed referral record
for the NGO coordinator, and a standing referral plan with a gap view for the district planner.

## 2. Who it is for, and what each one needs

| user | where they are | location they need | what they need from us |
| --- | --- | --- | --- |
| community health worker (ASHA, ANM) | with the patient | their own GPS (default) | one answer, a call button, 108/102, a slip for the family |
| NGO coordinator (this lens) | at a desk or on the phone, patient elsewhere | GPS by default, then "change location" to the patient's PIN, district, village, coordinates or a pin | 3 to 5 options side by side, quoted evidence, uncertainty, the facts to verify by phone, a record of the decision, a message for the field worker and family |
| district planner | office, planning ahead | GPS by default (their district), then a district or a hotspot pin | a standing plan per area and service, where coverage is thin, exportable |

The app never diagnoses. The user already knows the service. The app finds, ranks, explains and helps them act.

## 3. Location input

### 3.1 The rule

GPS is the default location for every user and every screen. Typing a PIN, district, city, village, coordinates,
pasting a map link or dropping a pin is reached through one "Change location" control. It is never the default.
The single exception is offline mode (section 9), where GPS satellite fixes still come first but the fallback ladder
is different.

### 3.2 GPS behaviour (online)

- First visit: the location row shows one large button "Use my location (GPS)". The permission prompt is shown only
  on that tap, as web.dev recommends (https://web.dev/articles/user-location). Call:
  getCurrentPosition({enableHighAccuracy: true, timeout: 15000, maximumAge: 60000}).
  enableHighAccuracy must be true: without it Chromium on Android asks for balanced power (Wi-Fi and cell, needs
  data) (offline feasibility, LocationProviderGmsCore.java lines 110-127).
- Later visits: if permission is already granted (Permissions API), the app fills GPS on open without a tap and
  shows the saved fix at once while a fresh one arrives. Not tested on a device.
- The resolved place is always echoed as text: "Your GPS: near Ashti BO, PIN 444801, Amravati district,
  Maharashtra (accurate to 40 m)". District comes from point-in-polygon on a district layer (88.5% right via nearest
  office, polygon is the primary method; geo_routing feasibility, district_eval.json). Nominatim is used only for a
  friendlier village name, cached, one call per fix.
- Accuracy rule: up to 1,000 m is accepted silently; 1,000 to 2,000 m is shown as "approximate, confirm" with the
  PIN prefilled; over 2,000 m asks the user to allow precise location or pick a place.
- Permission denied or timeout: the location row switches to "Location blocked. Enter the patient's PIN or
  district" and focus moves to that field (tested in accessibility feasibility, offline_results.json).

### 3.3 "Is the patient here?" (the coordinator hinge)

Right under the GPS line there is one question with two big buttons: "Patient is here" and "Patient is somewhere
else". A coordinator taps "somewhere else" and gets the Change location sheet. The app remembers the answer per
user for 12 hours (localStorage, per-viewer convenience only), so a coordinator making 10 referrals does not answer
it 10 times, but the GPS default is restored the next day.

### 3.4 Change location sheet (all four input types plus a pin)

One text box that accepts anything, parsed in this order (all parsing is deterministic code, no LLM):

| what the user types or pastes | how it is read | online needed |
| --- | --- | --- |
| 6 digits, e.g. 444801 | India Post PIN centroid; list post offices of that PIN to refine | no |
| two numbers, e.g. 21.05, 77.64 or 21.05 77.64 | coordinates, checked to be inside India's bounding box | no |
| a Google Maps link with @lat,lng or q=lat,lng | coordinates extracted from the URL | no (short links like maps.app.goo.gl need one redirect, online, not tested) |
| a district name, e.g. "Gadchiroli" | district layer; result is the district centroid plus "pick a block or PIN to be precise" | no |
| a city, town or village name | offline post office gazetteer first, Nominatim search (countrycodes=in) when online; always a candidate list with district and state, never a guess ("Muhra" matched two states in the test) | partly |
| "Drop a pin" button | opens the Leaflet map on demand, tap to place | yes (tiles) |

The field worker's own location can reach the coordinator without our app, because the field worker usually cannot
open it (no anonymous access to Databricks Apps). The field worker shares their location in WhatsApp or sends the
6-digit PIN by SMS, and the coordinator pastes it. The format of a WhatsApp location share pasted as text was not
tested.

The resolution is always echoed with its precision: "Using PIN 444801 (Ashti BO), Amravati, Maharashtra. PIN
centroid: the patient may be up to 9 km from this point." (PIN centroid error: median 3.8 km, p90 9.5 km;
district_eval.json.)

## 4. Service input

The intermediary already knows the service. Input is built so the common case is one tap or a few keystrokes, and
anything a model reads is shown back for a one-tap confirmation.

1. Service tiles (default, no model, works offline): 7 services from the gold set (dialysis, emergency C-section,
   NICU, trauma and emergency, burn care, MRI, cardiac surgery), plus "Other / not sure". Each tile has an icon, the
   English name and the local name (Hindi; Marathi when the resolved state is Maharashtra), e.g.
   "Dialysis / dayalisis, khoon saaf karna / dayalisis".
2. Search box (desk users): a combobox (ARIA 1.2 pattern) over the synonym lexicon in English, Hindi, Marathi and
   Hinglish: "LSCS", "caesarean", "operation se delivery", "seezer", "bachcha dani", "kidney machine". Keyboard:
   "/" focuses it, arrows move, Enter picks. Works offline from the lexicon.
3. Describe it in your words: free text or the mic button (Web Speech API where present, lang hi-IN, mr-IN,
   en-IN). Mapped by databricks-meta-llama-3-3-70b-instruct at temperature 0 with a strict json_schema enum
   (36/36 correct in the voice feasibility test, decisive phrase verbatim every time). Shown back as a chip:
   "Emergency C-section, because you wrote 'operation se delivery karna padega'. [Yes] [Change]". If the decisive
   phrase is not a substring of the input, or the answer is "other", the tiles open instead. Gemma-3-12b is not
   used here (it sent chest pain to trauma). Voice on Android Chrome is server-side and needs data; not tested on a
   phone.
4. Scan a referral note: camera or file input, resized in the browser to about 1024 px, sent once to
   databricks-llama-4-maverick with json_schema (9/9 correct, resisted the injection test). A deterministic guard
   checks that the trigger phrase appears verbatim in the detected text and that the keyword lexicon agrees. The
   confirm screen quotes the note: "We read: 'LSCS advised, previous caesarean'. Looking for: emergency C-section.
   [Yes] [Change]". The photo is held in memory for one call and never stored. Timeout 15 s, then the tiles.

Red flags are a fixed tap checklist (heavy bleeding, fits, unconscious, breathing difficulty, labour with bleeding,
chest pain, large or facial burn), OR-ed with a danger-word list on any free text. Model red flags are never used
alone (inconsistent across near-identical inputs in the vision test). Any red flag puts a full-width
"Call 108 now" bar above every result.

## 5. Screens

All wireframes are for a 360 px phone unless marked "desk" (1280 px). The desk layout is the same page with
columns side by side. Labels in brackets are buttons; text in single quotes is quoted facility text.

### 5.1 Start (GPS default)

```
+--------------------------------------------+
| Referral Desk                [EN|hi|mr] [?] |
|--------------------------------------------|
| WHERE                                      |
| (o) My location (GPS)                      |
|     near Wardha Rd, Nagpur  +-40 m          |
|     district Nagpur, MH     [Use my GPS]    |
|                                            |
| Is the patient here?                       |
| [ Patient is here ] [ Somewhere else ]     |
|--------------------------------------------|
| WHAT SERVICE                               |
| [/ Search: LSCS, dialysis, NICU...   ]     |
| +----------+ +----------+ +----------+     |
| | Dialysis | | C-section| |  NICU    |     |
| | dayalisis| | operation| | navjaat  |     |
| +----------+ +----------+ +----------+     |
| | Trauma   | | Burns    | |  MRI     |     |
| | Heart op | | Other / not sure        |     |
| [Describe in words / mic] [Scan a note]    |
|--------------------------------------------|
| Danger signs? (tap any)                    |
| [ ] heavy bleeding [ ] unconscious         |
| [ ] breathing      [ ] labour + bleeding   |
|--------------------------------------------|
| [        Find the best place        ]      |
| Data saved 21 Nov 2026 - Online            |
+--------------------------------------------+
```

### 5.2 Change location sheet

```
+--------------------------------------------+
| Where is the patient?                 [x]  |
|--------------------------------------------|
| [ PIN, district, village, 21.05,77.64  ]   |
|   or paste a Google Maps / WhatsApp link   |
|--------------------------------------------|
| Matches for "Ashti":                       |
| ( ) Ashti BO, PIN 444801, Amravati, MH     |
| ( ) Ashti, PIN 414203, Beed, MH            |
| ( ) Ashti, PIN 442707, Gadchiroli, MH      |
|--------------------------------------------|
| [Drop a pin on map]   [Back to my GPS]     |
| Recent: 444801 Ashti BO   442605 Gadchiroli|
+--------------------------------------------+
```

The "Matches" rows are examples of the layout; the real list comes from the gazetteer (PIN values above are
illustrative, not looked up).

### 5.3 Results, coordinator view (desk: comparison table)

```
+------------------------------------------------------------------------------------------+
| Emergency C-section near Ashti BO (PIN 444801), Amravati, MH    [Change] [EN|hi|mr]     |
| Danger sign ticked: labour with bleeding  ->  [ CALL 108 NOW ]  [ Call 102 (free, JSSK)] |
|------------------------------------------------------------------------------------------|
| PLAN: go to A. If A says no: B. If B says no: C.  Chance at least one works: 0.86       |
|       (assumes the options fail independently; B and C are not copies of each other)    |
|------------------------------------------------------------------------------------------|
|                      | A  (plan: first)     | B  (backup)          | N  (nearest)         |
|----------------------+----------------------+----------------------+----------------------|
| Verdict              | LIKELY offers it     | LIKELY offers it     | NOT VERIFIED         |
| How sure (P_S)       | 0.78 (0.66-0.87)     | 0.71 (0.57-0.82)     | 0.22 (0.10-0.41)     |
| Track record of band | 18/22 confirmed      | 18/22 confirmed      | 4/19 confirmed       |
| Distance / time      | 41 km, 45-70 min     | 58 km, 60-90 min     | 16 km, 18-30 min     |
|   time source        | road route (OSRM)    | road route (OSRM)    | road route (OSRM)    |
| Exists (P_E)         | 0.95 own website     | 0.90                 | 0.60 directory only  |
| Location agrees      | PIN+map+city <3 km   | PIN+city             | PIN vs map 12 km off |
| Strongest quote      | 'Emergency LSCS      | '24 hour labour room | 'Gynaecology OPD'    |
|                      |  available 24x7'     |  and OT'             |                      |
| Evidence ignored     | none                 | 1 sentence (other    | none                 |
|                      |                      |  hospital named)     |                      |
| Listed as            | public (claim)       | private (claim)      | private (claim)      |
| Phone                | mobile, unique       | landline, unique     | shared by 4 cities   |
| Verify by phone      | anaesthetist now?    | OT free? blood?      | do they do LSCS?     |
|----------------------+----------------------+----------------------+----------------------|
|                      | [Why A] [Call A]     | [Why B] [Call B]     | [Why not N]          |
|------------------------------------------------------------------------------------------|
| Why A before N: N is 25 km nearer. Distance alone favours N by 2.3x. A's evidence is     |
| 5.7x stronger (0.74 vs 0.13). So A ranks first.            [show the arithmetic]         |
|------------------------------------------------------------------------------------------|
| [Choose A and record]  [Share plan]  [Print slip]  [Map]  [Download offline copy]        |
+------------------------------------------------------------------------------------------+
```

All numbers in the wireframes are illustrative layout values. On the phone the table becomes swipeable cards with the
same rows in the same order, one option per card, and a sticky "compare 3" toggle that shows the rows as a 3-column
grid of short values.

Column rules: A and the backups come from the decision layer's plan; the nearest non-Unlikely option is always added
as column N when it is not in the plan, because "why not the closer one" is the first question a family asks.
When the 108/102 path is used, a fourth column "best public facility in reach" is added (108 dispatch goes to the
nearest centre and 102 carries to CHC or government hospitals; actions feasibility, NHM pages).

### 5.4 Results, field worker view (phone, default depth for "Patient is here")

```
+--------------------------------------------+
| Dialysis near you (GPS, +-40 m)    [Change]|
|--------------------------------------------|
| GO TO                                      |
| A. <facility name>, Darbhanga              |
| LIKELY offers dialysis - sure 0.81         |
| 19 km by road, 25-40 min                   |
| 'Six haemodialysis machines in a dedicated |
|  unit'  (from its listing)                 |
| [ CALL FIRST  +91 9xxxx xxxxx ]            |
| [ Directions ] [ Uber/Ola ] [ Send family ]|
| [ Read aloud ]                             |
|--------------------------------------------|
| If they say no: B. <name>, 31 km [Call]    |
|--------------------------------------------|
| [ Why this one? ]  [ Compare all ]         |
+--------------------------------------------+
```

Depth follows the "Is the patient here?" answer and can be switched any time with "Compare all" or "Quick answer".

### 5.5 WHY / HOW card for one option (opens from [Why A])

```
+--------------------------------------------+
| A. <facility name>                    [x]  |
| LIKELY offers emergency C-section          |
|--------------------------------------------|
| 1 WHY WE THINK IT OFFERS IT                |
|  [procedure] 'Emergency LSCS available     |
|              24x7'                         |
|  [capability] 'Level II obstetric unit     |
|              with blood storage'           |
|  Source: one of these pages (3)  [open]    |
|  Ignored: 'C-section at City Hospital,     |
|   Pune' - names a different hospital       |
|--------------------------------------------|
| 2 IS IT REAL, IS IT THERE                  |
|  Own website; phone not shared with other  |
|  listings. PIN, map point and city agree   |
|  within 3 km.                              |
|--------------------------------------------|
| 3 HOW SURE                                 |
|  0.78 (range 0.66 to 0.87)                 |
|  Of 22 checked facilities scored like this,|
|  18 were confirmed, 1 was wrong, 3 had no  |
|  public information.                       |
|--------------------------------------------|
| 4 HOW WE SCORED IT (points)                |
|  base for this kind of record    -0.9      |
|  procedure sentence, specific   +1.6 ####  |
|  capability sentence            +0.9 ##    |
|  record merges 12 pages         -0.3 #     |
|  total 1.3 -> 0.78 (calibrated)            |
|  [full waterfall] [model card]             |
|--------------------------------------------|
| 5 DISTANCE                                 |
|  41 km road, 45-70 min (OSRM route, free   |
|  flow, real trips are slower)              |
|--------------------------------------------|
| 6 WHAT A CALL WOULD CHANGE                 |
|  If a call confirms N, N ranks first.      |
|  Without the 2 quoted sentences, sure      |
|  would be 0.34.                            |
|--------------------------------------------|
| [Read aloud] [Copy as text] [Hindi]        |
+--------------------------------------------+
```

### 5.6 Verify by phone (call-ahead with checklist)

```
+--------------------------------------------+
| Call A before the patient leaves           |
| +91 9xxxx xxxxx  (mobile, not shared)      |
| [ CALL ]                                   |
|--------------------------------------------|
| Say:                                       |
| 1 Is this <A> in <town>?          [Yes][No]|
| 2 I have a patient who needs an            |
|   emergency C-section.                     |
| 3 Is an obstetrician AND an                |
|   anaesthetist on duty now?       [Yes][No]|
| 4 Is the OT free, is blood there? [Yes][No]|
| 5 If you cannot, which hospital nearby     |
|   can?   [ note: ____________ ]            |
| 6 Whom do we ask for on arrival?           |
|   [ name/desk: ____________ ]              |
|--------------------------------------------|
| Result: [They can] [They cannot]           |
|         [Could not reach]                  |
| -> They cannot: plan moves to B. [Call B]  |
+--------------------------------------------+
```

Questions 1, 5 and 6 are fixed; 3 and 4 come from SERVICE_QUESTIONS in
/Users/karthikvattem/projects/datathon/app_design/feasibility/actions/links.py. Extra questions are added from the
model's weakest terms (section 6.4). The script is shown in the chosen language from fixed templates.

### 5.7 Referral record (coordinator)

```
+--------------------------------------------+
| Record this referral                       |
|--------------------------------------------|
| Case ref (your own code, no names): [MH-17]|
| Chosen: A. <facility>                      |
| Why (tick, prefilled from the compare):    |
| [x] strongest evidence (0.78 vs 0.71)      |
| [x] confirmed by phone 14:05 (anaesthetist)|
| [ ] nearest option                         |
| [ ] public / free under JSSK               |
| [ ] family preference                      |
| [ ] other: ____________                    |
| Calls made: A yes 14:05; N not reached     |
|--------------------------------------------|
| Saved with: data 2026-11-21, model         |
| 3f9a..., options shown A, B, N             |
| [ Save ]  [ Save and share ]               |
| Saved offline: will sync when online       |
+--------------------------------------------+
```

The record stores what was shown, not only what was chosen: the options on screen with their scores, the model and
data hash, the call outcomes and the reason ticks. A supervisor can open it later and see exactly the screen the
coordinator saw. No patient name, phone or photo is stored; the case reference is the coordinator's own code. The
server-side store (a Unity Catalog table written through the SQL warehouse, or Lakebase) is a design choice not
tested; offline, records wait in an IndexedDB outbox.

### 5.8 Share and slip

```
+--------------------------------------------+
| Share the plan                             |
| To: ( ) field worker  ( ) family           |
| Language: [Marathi v]                      |
|--------------------------------------------|
| Preview (SMS 3 parts / WhatsApp):          |
| Go to: <A>, <address>                      |
| Map: https://www.google.com/maps/dir/...   |
| Call first: +91 9xxxx xxxxx                |
| If they say no: <B>, +91 ...               |
| For 108/102: ask the crew to take you to   |
| <A>; if they cannot, <public P>.           |
| Carry: referral note, ID, JSSK/PM-JAY card |
|--------------------------------------------|
| [WhatsApp] [SMS] [Print slip] [Copy]       |
+--------------------------------------------+
```

The message is self-contained (no link to our app, which the family cannot open). The printable slip is one A5 page
via print CSS: plan, map link as text, phones, the call script, and a "why this facility" line with the top quote
and confidence, so the family can show it at the hospital and the field worker can show it to a supervisor.

### 5.9 Planner view (area)

```
+------------------------------------------------------------------------+
| Area plan: Washim district (your GPS)   Service: [Trauma v] [Change]   |
|------------------------------------------------------------------------|
| Expected verified providers within 60 min: 0.7  (gap: below 1)        |
| NFHS-5 context: <indicator rows for this district, '*' = suppressed>   |
|------------------------------------------------------------------------|
| Standing plan by block / PIN group           | top    | backup | min  |
| Washim PINs 444505-444510                    | A      | B      | 35-60|
| Risod PINs 444506 ...                        | A      | C      | 50-80|
| Highway pin 19.94, 76.15 (dropped)           | D      | A      | 40-70|
|------------------------------------------------------------------------|
| Low web presence looks like a gap. Verify before acting.              |
| [Export CSV] [Print plan] [Show on map] [Build offline pack]          |
+------------------------------------------------------------------------+
```

This is the spec's planner mode (MODEL_SPEC_v1.md 6.8, marked "optional, cut second"). The minimal version is the
table: the same ranking run over each PIN centroid in the district, which the offline pack builder already does per
PIN (offline feasibility, build_pack.py).

### 5.10 Offline states

```
+--------------------------------------------+
| OFFLINE - saved data from 21 Nov 2026      |
| (2 days old). Distances are straight line. |
|--------------------------------------------|
| WHERE                                      |
| GPS: searching satellites... 0:24          |
| Stand outside, up to 2 minutes.            |
| [Use last fix: 3 h ago, Ashti BO]          |
| [Pick a place (PIN / district / office)]   |
|--------------------------------------------|
| C-section near Ashti BO                    |
| A. <name>  LIKELY 0.78  ~41 km straight x  |
|    1.26 road = ~52 km, 45-75 min (rough)   |
|    'Emergency LSCS available 24x7'         |
|    [CALL A]  (calls work without data)     |
| B. <name>  LIKELY 0.71  ~58 km  [CALL B]   |
| [CALL 108] [CALL 102] [SMS plan] [Record]  |
+--------------------------------------------+
```

## 6. How the reasoning is shown for each recommendation

Every recommendation, on every depth, carries the same seven parts. The field view shows parts 1, 3, 5 and 7 in one
line each; the coordinator compare shows all seven as rows; the WHY card and "one click deeper" show the full detail.
Every number is read from the same stored row the ranking used (model spec 7.4). The page recomputes U and the
order from the numbers on screen and refuses to render if they disagree.

### 6.1 The seven parts

1. Verdict in words, tied to a band rule: LIKELY, POSSIBLE, NOT VERIFIED ("call to confirm"). Never coloured as
   verified unless the band rule says so.
2. Quoted facility text: up to 3 verbatim sentences that passed attribution, each labelled with its field
   (procedure, capability, equipment, description) and cited as "one of these pages" with the record's source URLs
   (no sentence-to-URL map exists in the data). Rejected sentences are shown under "what we ignored" with the reason
   (names another hospital, another state).
3. Calibrated confidence with its interval and the band's track record in three outcomes (confirmed, wrong, no
   public information) with n, from band_record.parquet, and the labels hash.
4. Model contributions: a points waterfall per head (exists, location, offers service), each term with its value on
   this record, its weight and how often it fired on checked pairs. Sum of displayed points equals the score.
5. Distance and travel time with the source of the number: "road route (OSRM, free flow)" when the live table call
   succeeded; "precomputed road time" when the PIN table exists; "rough estimate: straight km x 1.26 at 69 to
   40 km/h" otherwise (fallback MAPE 16.5%, geo_routing feasibility). Times are always ranges. Options whose times
   differ by less than about 20% are shown as "about the same time" and the rank says so.
6. Why not the alternatives: the exact factorisation U_A / U_B = evidence ratio x location-and-distance ratio
   (model spec 6.7), printed as one sentence for the nearest option and for each backup, plus the counterfactual
   "if a call confirms B, B ranks first".
7. What to verify and what to do next: the call-ahead questions, phone trust ("mobile, unique" or "may be a
   directory number"), and the plan's fallback.

### 6.2 Abstention

When no Likely option exists within the urgency profile's maximum radius, the result page opens with one sentence:
"No facility within 200 km has enough public evidence that it has a NICU." Below it: "Call to confirm" options
(never coloured as verified), the district hospital as "the public standard says this level should offer it; not
verified in our data" where the spec's outside option applies, and the 108/102 buttons. Gadchiroli NICU (gold query
q18: 15 facilities within 150 km, 1 service mention, 0 strong or medium) is the expected example.

### 6.3 Plain words and Hindi

Every card has a "Say it simply" line built from templates with numbers inserted by code, for the coordinator to
read to a family or paste to a supervisor: "We suggest A because its own listing says it does emergency C-sections
24 hours a day, and of 22 similar hospitals we checked, 18 really did. N is closer, but nothing in its listing says
it does C-sections, so call N only if A says no." Templates are written by the team in English, Hindi and Marathi
(a native speaker review is not done yet). Quotes stay in their original language with a gloss labelled as a
translation. If any LLM translation is used for text outside the templates, it uses placeholder protection and the
verbatim check, and falls back to English if the check fails (4/4 passed with placeholders, 0/4 without; voice
feasibility).

### 6.4 Facts to verify, chosen by the model's weakest terms

The coordinator's "verify by phone" list is not generic. It is generated from the terms that most limit this
option's score, with fixed rules:

| weakest term on this option | question added |
| --- | --- |
| P_L low, or PIN and map point disagree | "What is your full address and nearest landmark?" |
| phone shared by 3+ cities | "Is this <name> in <town>?" moves to the top and is marked required |
| service evidence is only a specialty word, no procedure sentence | "Do you do <service> yourselves, or refer out?" |
| merged record (many source pages) | "Is <service> done at this branch or another one?" |
| time-critical service | the SERVICE_QUESTIONS for that service (staff on duty now, OT, beds) |

Each question shows why it was added ("added because the PIN and map point are 12 km apart"). Answers feed the
plan: "They cannot" drops that option and promotes the next; "They can" marks the option "confirmed by phone at
14:05" on the slip and in the record. Call outcomes are logged as future labels for turn-away rate and phone trust
(as proposed in the actions feasibility), not used to change the model live.

## 7. Actions

All actions are plain links the user taps; nothing books or calls automatically (Chrome needs a user gesture;
Uber's request scope is privileged; Ola is invite-only; actions feasibility). Builders are in links.py. None has
been tap-tested on a real phone yet; tap_test.html exists for that.

| action | link | shown when |
| --- | --- | --- |
| Call 108 | tel:108 | any red flag; first for trauma, burns, labour complication |
| Call 102 (free for pregnant women and infants under JSSK) | tel:102 | C-section, NICU, beside 108 |
| Call the facility | tel:+91... via e164_india (refuses 76 bad values, incl. '100') | phone validated and not marked as a directory number |
| Call-ahead script | screen 5.6 | every option |
| Directions | https://www.google.com/maps/dir/?api=1&destination=LAT,LNG (name and town when coordinates are uncertain) | every option |
| Uber | m.uber.com/looking?drop[0]=... or the /ul/ form, pickup = my location | non-emergency, car only for labour and newborns |
| Ola | universal link with drop_lat, drop_lng (drop-off without utm_source not tested); bk_act=rl "ride later" for dialysis | non-emergency |
| Rapido, Namma Yatri | open the app only, address shown to copy | non-emergency |
| Share to field worker or family | wa.me/?text=..., sms:?body=... | every plan |
| Print slip | print CSS, one A5 page | coordinator |
| Record referral | screen 5.7 | coordinator |
| Download offline copy | single-file HTML with the state pack | coordinator, planner |

Order follows the urgency profile: for emergencies the ambulance button is above everything and ride links sit under
"If no ambulance comes in N minutes". For dialysis the call-ahead and "ride later" come first.

## 8. Accessibility

Target: WCAG 2.2 AA in every state (start, locating, results, compare, GPS denied, offline), checked by axe-core
4.12.1 with wcag2a, wcag2aa, wcag21a, wcag21aa, wcag22aa and best-practice tags before each demo build. The plain
FastAPI page had 0 violations in the accessibility feasibility test; each framework tested had 3 rule types.

- Targets 48 x 48 CSS px for primary actions, nothing under 24 x 24 (2.5.8). Contrast 4.5:1 text, 3:1 UI, light and
  dark. Reflow at 320 px and 200% text (1.4.10, 1.4.4).
- The compare table is a real table with th scope and a caption on desk; on phone the same data is a list of cards
  whose rows have the same labels, so a screen reader hears "A, verdict, likely; how sure, 0.78" in the same order
  for every option. Points bars always have the number next to them.
- Status messages ("Searching satellites", "3 options found", "Saved offline") go to a role=status live region.
  Focus moves to the next input on failure (GPS denied moves focus to the PIN field).
- lang on html and on every Hindi or Marathi string; system fonts with Noto Sans Devanagari as fallback, no web
  fonts.
- Low literacy: icon plus word on every action, one decision per screen on the field view, Western digits with
  units, "Read aloud" with speechSynthesis only when getVoices() has a voice for the language (no Marathi voice on
  macOS; Android voices not tested), and the call button on every result (Medhi et al. 2011: live operators up to
  10x more accurate than text UIs).
- Colour is never the only signal: band words and shapes (filled, half, outline marker) carry the verdict.
- No time limits, honour prefers-reduced-motion, no auto-playing anything.
- Low bandwidth budget: 50 KB or less to the first button, 5 requests or fewer, no third-party hosts on the critical
  path; results JSON 20 KB or less; map opt-in (Leaflet 42.6 KB plus about 22 KB per tile). Measured: the plain page
  shows its button in 0.24 s on slow 4G and 0.44 s on the 2G profile; Streamlit took 8.2 s and 44 s.
- Known gap: the Databricks workspace sign-in (3.3.8 accessible authentication) is outside our control.

## 9. Offline mode

GPS stays the default offline. What changes is where the data comes from and what replaces network services.

### 9.1 Detection

Offline means any of: navigator.onLine is false, an /api call fails, or it takes over 8 s. A fetch with
redirect: "manual" that returns opaqueredirect means "session expired", not offline, and the page says "Sign in
again to refresh; showing saved data" (tested in the simulated auth proxy, offline feasibility).

### 9.2 What is on the phone

- App shell in the service worker cache (network first, cached shell on network error or status >= 500).
- Referral pack in IndexedDB: per state by default, chosen from the first GPS fix while online, including
  facilities across the border. Per (PIN, service): the decision layer's top pick, 2 backups and the call-first
  number, each with name, validated phones, coordinates, band, P_S with interval, the band's track record line, the
  two strongest quotes with field labels and source URL, and the "why first" sentence. Plus the PIN and post-office
  picker and the service lexicon with Hindi and Marathi names, and the call-script templates.
  Measured sizes with placeholder content: Bihar pack plus picker 110 KB gzip (196 KB in IndexedDB); largest state
  Uttar Pradesh 228 KB gzip; all India 1.85 MB gzip.
- Coordinators and planners get a "Keep data for: [my state] [these states...] [all India]" choice, because their
  patients are in other districts and sometimes other states.
- The coordinator's referral records and call outcomes from the last 30 days, and an outbox of unsynced records.
- "Saved <date> (N days ago)" on every offline answer: amber after 30 days, red after 90 with "phone numbers may have
  changed". navigator.storage.persist() is requested after install.

### 9.3 Location ladder offline

1. GPS satellite fix: watchPosition({enableHighAccuracy: true, maximumAge: 0, timeout: 120000}); accept the first
   fix at or under 1,000 m, save it, stop the watch. Show "Stand outside, up to 2 minutes" and a "Pick a place"
   button from the first second. Satellite fixes need no data (Chromium source), but time to first fix offline was
   not measured on a phone.
2. The app's own saved last fix (IndexedDB, not maximumAge, which the browser may evict), with its age.
3. Offline picker: PIN (19,584 PINs on the phone for all India, or the state subset), or district then post office
   (9,058 offices in the Bihar pack). Typed coordinates work offline. Village names work only if they match a post
   office name (1 of 4 in the village test).
4. Not offline: Nominatim search, map tiles, dropped pin. These buttons are hidden, not greyed out.

### 9.4 What works and what does not

| feature | offline | how |
| --- | --- | --- |
| GPS location | yes | satellite fix, high accuracy |
| service tiles and lexicon search | yes | in the shell and pack |
| free text, voice, referral-note photo | no | needs model serving; tiles shown instead |
| ranking | yes, for PINs in the pack | precomputed plan per (PIN, service); a GPS point uses its nearest PIN centroid in the pack and says so |
| quotes, confidence, track record, why-first | yes | stored per option in the pack |
| full waterfall, model card | summary only | top 3 terms per option are in the pack |
| travel time | rough range | straight km x 1.26 at 69 to 40 km/h |
| call facility, 108, 102 | yes | tel: uses the SIM |
| share plan | yes | sms: and wa.me open the phone's apps; WhatsApp sends when data returns |
| directions, ride links | open the app | Google Maps may have offline maps; ride apps need data |
| referral record | yes, queued | IndexedDB outbox, synced on next online open |
| planner area view | yes, for the cached state | same pack rows grouped by district |

### 9.5 No-internet channels

- Calls and SMS from the phone itself (tel:, sms:) work without data.
- "Download offline copy": a single HTML file with the state pack embedded (Bihar: 475 KB, 112 KB gzip), which worked
  from file:// with the network off in desktop Chromium. A coordinator can send it to a field worker as a WhatsApp
  document; the field worker opens it with no Databricks login. Opening it on Android Chrome was not tested, and
  whether redistributing the pack is allowed under the dataset terms was not checked; both must be cleared before
  this is offered outside the team.
- SMS bot: demo only this weekend. A team Android phone runs android-sms-gateway in local-server mode and a laptop
  script answers "CSEC 444801" from the pack with sms_reply.py (3 GSM-7 segments for a dialysis reply). Not tested
  end to end. A real two-way SMS service needs DLT registration through an Indian entity (days to weeks) and is
  on the roadmap, followed by a Hindi IVR. USSD is dropped.

## 10. Creative features

1. "Is the patient here?" switch: one question sets the depth (quick answer or compare) and the location source
   while keeping GPS the default.
2. Uncertainty-driven call list: the phone questions come from the option's weakest model terms, each with the
   reason it was added, and each answer re-plans live. The model tells the coordinator which call is worth making
   first ("if a call confirms N, N ranks first").
3. Referral record as a replayable snapshot: the record stores the screen as it was (options, scores, hashes,
   calls), so the decision can be justified to a supervisor months later even after the data changes.
4. Paste-anything location box: PIN, coordinates, district, village or a map link in one field, parsed offline.
5. Nearest option always shown with the exact "why not" sentence, so the family's first objection is answered on
   screen.
6. "Say it simply" line in English, Hindi and Marathi from fixed templates, with numbers filled by code, safe to read
   aloud or paste.
7. Public facility column for the 108/102 path, with the JSSK free-care trade-off stated next to private picks.
8. Offline copy as a file a field worker can open without a login, and an SMS demo bot answering from the same pack.
9. Planner standing plan per PIN group, printable and exportable, from the same ranking as the single answer.

## 11. Ideas killed, and why

| idea | why killed |
| --- | --- |
| Photo of the patient's condition for self-triage | users are intermediaries who already know the service; injury photos gave wrong detail (palm vs back of hand) and gemma overcalled severity; we must never grade a wound. Kept only: photo of a referral note, confirmed by a tap |
| App calls an auto or Uber for the patient | Uber request scope is privileged, Ola is invite-only, Chrome needs a tap; replaced by prefilled one-tap links |
| Ambulance booking through an API | no public 108/102 dispatch API found; tel:108 instead |
| LLM writes or translates the explanation | LLMs said "offers dialysis, confidence 1" for a contaminated record; direct translation broke quotes and numbers 4/4. Templates plus placeholder-protected translation only |
| Gemma-3-12b on any input path | obeyed an injected instruction (2/2), 429s on sequential calls, sent chest pain to trauma |
| Streamlit front end | 1.25 MB per visit, 44 s to first button on 2G, critical axe violations, cannot reload offline |
| Map-first results | map costs about 220 KB and is not accessible as the only channel; list first, map on demand |
| Nominatim, OSRM demo or OSM tiles on the critical path | no SLA, one shared AWS IP for all users; used only as cached extras |
| Typed location as the default for coordinators | team rule: GPS is the default; typing is "change location" |
| A link to our app in the family's message | no anonymous access to Databricks Apps; the message is self-contained instead |
| Recurring dialysis booking | no deep link creates a repeating ride; "ride later" plus a call script instead |
| Live SMS service this weekend, USSD | DLT takes days to weeks and needs an Indian entity; USSD access is negotiated with operators |
| Relying on browser maximumAge for the last fix | the spec lets the browser evict it; the app stores its own last fix |
| Storing referral-note photos or patient names | clinical data; the record uses a case code only |

## 12. Tech stack

- Databricks App, FastAPI (pre-installed) serving one static HTML page, CSS and vanilla JS, plus a service worker
  and a web app manifest linked with crossorigin=use-credentials (manifest only loads behind the cookie gate with
  it; offline feasibility). Preact or HTMX only if the compare screen outgrows plain JS.
- JSON endpoints: /api/resolve (location), /api/map-service (Llama 3.3 70B), /api/scan-note (Maverick),
  /api/recommend, /api/route (OSRM top 3-5, 3 s timeout, cached), /api/records, /api/pack/version, /api/pack/{state}.
- Data: Unity Catalog tables from the model layers (pair_scores, facility_scores, band_record, cards,
  benchmark_answers) read through the SQL warehouse; the referral pack and PIN-to-facility time table precomputed by
  the model pipeline. Creating these tables and any job is out of scope for this design task.
- Geography on the server and in the pack: India Post PIN centroids and post offices, district polygons
  (geoBoundaries ADM2, ODbL) for point-in-polygon, offline nearest-office lookup (about 2 ms).
- Browser APIs: Geolocation, Permissions, IndexedDB, Cache Storage, StorageManager.persist, Web Speech
  (recognition where present), speechSynthesis, input type=file accept=image/* capture=environment, print CSS.
- Map: Leaflet 1.9.4 from cdnjs with OSM tiles, loaded only on "Map" or "Drop a pin", OSM attribution visible.
- Links: links.py builders (stdlib only).
- Tests kept from feasibility: measure.py and offline_test.py (axe and offline states), links.py self-check,
  travel_time.py self-check, build_pack.py self-check, score.py guard for the note scanner.

## 13. Internet dependencies and fallbacks

| dependency | used for | if it fails |
| --- | --- | --- |
| Databricks App and workspace login | everything online | service worker shell plus pack; offline HTML copy |
| SQL warehouse | live ranking, records | pack ranking for PINs in the pack; records queued |
| Llama 3.3 70B endpoint | free text and voice mapping | tiles and lexicon search |
| Llama 4 Maverick endpoint | referral-note scan | tiles; demo uses cached replies |
| Web Speech (Google servers on Android) | mic input | keyboard voice typing (not tested), typing, tiles |
| OSRM demo server | live road time for top 3-5 | precomputed PIN table, then straight km x 1.26 range |
| Nominatim | village names, friendly reverse label | post office gazetteer, PIN, coordinates |
| OSM tiles | map, dropped pin | list only; coordinates typed |
| Google Maps, Uber, Ola, WhatsApp | actions | tel: and sms: always shown |
| Phone network (voice, SMS) | calls, SMS share | none; this is the last channel |

Not reachable from the App: data.gov.in and hospitals.pmjay.gov.in (net probe), so no live government lookups.

## 14. Fit to the judging criteria

- Creativity: the depth switch, the uncertainty-driven call list that re-plans live, the replayable referral record,
  the offline copy and SMS bot from one pack, and the always-present "why not the nearer one" sentence. These come
  from the intermediary's real job (arrange, verify, justify), not from adding a chatbot.
- Modeling: every card is the glass-box model's own arithmetic (points that sum to the score, calibrated interval,
  three-outcome track record, exact ranking factorisation, counterfactuals); contaminated sentences are shown as
  ignored; the app refuses to render if the ranking and the displayed numbers disagree; abstention is explicit.
- Impact: the coordinator gets from request to a confirmed, recorded, shared plan on one screen; the field worker
  gets one answer with a call button that works without data; the planner gets a standing plan and a gap list. It
  runs on 2G-class links and offline, in Hindi and Marathi, with WCAG 2.2 AA as a build gate.
- Challenge gates: WHY and HOW on every recommendation, cited facility text, uncertainty communicated, non-technical
  workflow, Databricks Free Edition, provided dataset.

## 15. Three-minute demo story

Prepared beforehand: the app opened once online on the demo phone and laptop (pack cached), demo note-scan reply
and OSRM results cached, demo phone number set to a team phone so the call can be shown.

- 0:00 to 0:20. "An NGO coordinator in Nagpur gets a call: a woman in Ashti village, Amravati district, is in labour
  with bleeding." The app opens with the coordinator's own GPS already filled (the default). She taps "Patient is
  somewhere else" and types 444801. The app echoes "Ashti BO, PIN 444801, Amravati, Maharashtra, PIN centroid,
  up to 9 km off" (gold query q19).
- 0:20 to 0:40. She photographs the referral note from the PHC (our generated slip, "LSCS advised"). "We read:
  'LSCS advised'. Looking for: emergency C-section. [Yes]". She ticks "labour with bleeding": the Call 108 and Call
  102 bar appears at the top.
- 0:40 to 1:20. The compare view: A, backup B, and the nearest N. Point at N: "NOT VERIFIED, 4 of 19 similar
  confirmed", and the sentence "N is 25 km nearer, distance favours N by 2.3x, A's evidence is 5.7x stronger". Open
  "Why A": two quotes from A's own listing with sources, one sentence ignored because it names another hospital, the
  points waterfall, "18 of 22 confirmed". (Real names and numbers come from the live run on q19; the ones in this
  document are layout values.)
- 1:20 to 1:50. Verify by phone: the list includes "Is this A in <town>?" and "Is an anaesthetist on duty now?" plus
  one added because A's PIN and map point disagree. She calls (team phone), taps "They can". The plan marks A
  "confirmed by phone 14:05".
- 1:50 to 2:15. Record and share: reason ticks prefilled, case code MH-17, save. Share in Marathi to the field
  worker by WhatsApp: self-contained message with map link, call-first number, and "ask the 108 crew for A; if not,
  public P". Show the printed A5 slip.
- 2:15 to 2:40. Offline: switch the phone to airplane mode, reload. Banner "OFFLINE, saved data from 21 Nov". GPS
  searching satellites (or "use last fix"), same plan from the pack, call buttons still live. Show the queued record
  and the offline HTML copy.
- 2:40 to 3:00. Planner and honesty: switch to Gadchiroli, NICU (q18). The app abstains: "No facility within 200 km
  has enough public evidence that it has a NICU", lists call-to-confirm options and the district hospital outside
  option. One line on the model card: calibration plot and the track record per band. Close: "Every answer shows
  its evidence, its confidence and what to check by phone."

## 16. Risks and open tests

- Nothing has run on a real Android phone or the deployed proxy: GPS accuracy and offline time to first fix,
  service worker install on *.databricksapps.com, camera and mic permissions, tel:/intent:/uber: links from the App,
  Web Speech for hi-IN and mr-IN. The probe_app in the offline feasibility folder and tap_test.html cover these and
  should be run before building on them.
- Judges must be workspace users; access must be granted ahead of the demo.
- The pack and wireframe numbers are placeholders: the prototype currently scores pairs with a fallback model, so
  rankings are not yet meaningful.
- operatorTypeId says public for only 469 of 10,088 records (8,842 private, local parquet check), so the "best public
  facility" column may often be empty or rely on the spec's district-hospital outside option, which is unverified.
- 102/108 roles vary by state; only national NHM descriptions were verified.
- Travel times are free-flow OSRM or a straight-line factor measured in rural Bihar plains; hills and the north east
  are likely worse.
- Hindi and Marathi templates and the danger-word list need a native speaker review.
- The referral record store (UC table or Lakebase) and its write path from the App are not tested.
- Redistributing the pack outside the App (offline HTML, SMS bot) needs a check of the dataset terms.
