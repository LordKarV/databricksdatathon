# Concept: Referral Saathi, the field worker lens

Status: design concept, written 2026-11-21. Nothing here is built. Claims about what works cite the
feasibility result that tested them (folders under /Users/karthikvattem/projects/datathon/app_design/feasibility/)
or the model spec (/Users/karthikvattem/projects/datathon/model/design/MODEL_SPEC_v1.md). Anything not tested
is marked "not tested". Facility names in the wireframes are invented placeholders, not dataset rows.

Hindi strings are written here in Latin script so this file stays ASCII. The app shows them in Devanagari.

## 1. One paragraph

Referral Saathi is one Databricks App for the people who stand between a patient and a hospital. An ASHA in
Sitamarhi opens it next to the patient. GPS fills the location by itself, she taps "Dialysis" (or scans the PHC
referral note), and within one screen she gets a referral plan: the facility to try first, two backups, and the one
phone call to make before anyone moves. Every option carries its reasons: the facility's own sentences quoted with
their source, how sure we are with the track record behind that number, what evidence we threw away and why, and
one exact sentence on why a farther option beats a nearer one. She then reads a call-ahead script to the facility,
calls 102 or 108 (or opens a ride app with the destination filled in), and sends the family a referral slip by
SMS or WhatsApp that explains the choice in plain Hindi. If there is no data signal, the app still opens from its
service worker, still gets a GPS fix from satellites, and answers from a referral pack for her state that was saved
the last time she was online, with the save date on every answer. The NGO coordinator gets the same answer with a
side-by-side comparison and a decision record. The district planner gets an area view of gaps and the standing
referral plan that becomes the field workers' offline pack.

## 2. Who uses it, and how deep each one goes

The users are intermediaries. The app never diagnoses: the user already knows the service the patient needs,
usually from a doctor or a PHC note.

| user | where they are | what they need | depth in the app |
| --- | --- | --- | --- |
| ASHA / ANM (primary lens) | with the patient, village, low-end Android, patchy data, Hindi | one answer she can act on now and explain to the family | Quick (default): plan, say-this-to-the-family, call script, transport, slip |
| NGO coordinator | an office or a phone, often in another district | compare options, defend the choice, keep a record | Compare: top 5 side by side, Pareto view, full WHY and HOW cards, decision record export |
| District planner | district office, laptop | where cases from an area should go, where the gaps are | Area: district by service gap table, standing referral plan per PIN, printable wall chart |

One app, no roles or extra logins (Databricks already forces a workspace login). Depth is a toggle in the menu
("Quick / Compare / Area"), remembered in localStorage per device. Quick is the default. All three depths read the
same decision-layer rows, so a coordinator never sees a different ranking from the ASHA.

## 3. Design rules

1. GPS is the default location for every user, online and offline. Typing a place or dropping a pin sits behind
   "Change location" and is never the default. The only time the app leads with another method is when GPS cannot
   give a fix (denied, timeout, no satellite view), and then it says why.
2. One decision per screen, a big primary action, an icon and a word on every button.
3. Every number on screen comes from a stored row and can be tapped to see that row (field name and source).
   No LLM writes or rewrites any reason, score or ranking (model spec 7.4).
4. Weak evidence is never shown as fact. "Likely" appears only when the band rule passes; Unverified options say
   "Not verified: call to confirm" first, in grey with a question-mark icon, never green.
5. The plan ends in actions, and every action is a plain link the user taps (tel:, sms:, wa.me, Google Maps, Uber,
   Ola). Nothing books or dials on its own.
6. Offline is a first-class state, not an error page.

## 4. Flow for the field worker

```
open app
  -> S1 Home: location already filling from GPS, service tiles below
       -> tap a tile ............................................. (works offline)
       -> or "Scan referral note" -> S2 confirm ................... (online only)
       -> or "Describe in your words" (type or mic) -> S2 confirm . (online; offline uses the word list)
  -> S2b Danger check (6 tick boxes, skip allowed) -> any tick shows the 108 bar on every later screen
  -> S3 Plan: first choice, backup 1, backup 2, "call first" marker
       -> tap an option -> S4 Why card (plain, then "Show the numbers" -> S5 How card)
       -> "Why not the others" -> S4b
  -> S6 Call ahead (script, tick answers) -> outcome Yes / No / No answer
       -> No or No answer: backup promoted, S3 refreshes, outcome saved (queued offline)
  -> S7 Get there: 102 / 108 / ride link / directions, ordered by urgency profile
  -> S8 Referral slip: send by SMS or WhatsApp, or show on screen
```

Target: a field worker with GPS on and data available goes from opening the app to a plan in 3 taps (open, tile,
skip danger check) (target, not measured).

## 5. Location input

### 5.1 GPS by default (online)

- First run: S1 opens with "Finding where you are" pre-selected as the location and one large button "Use my
  location (GPS)" already focused. The browser permission prompt appears on that tap, because a prompt shown on page
  load without a user gesture is discouraged and often denied (web.dev/articles/user-location, read by the
  geo_routing feasibility test). This is still GPS by default: there is no other choice on screen until GPS fails.
- Every later open: the app checks navigator.permissions.query({name: "geolocation"}). If the state is "granted",
  it starts the fix on load with no prompt and no tap. If "denied", it shows "Location is blocked for this app" with
  a two-step guide to allow it, and the PIN field (5.4) underneath.
- Call: getCurrentPosition({enableHighAccuracy: true, timeout: 15000, maximumAge: 600000}). enableHighAccuracy must
  be true: in Chromium, false maps to PRIORITY_BALANCED_POWER_ACCURACY (Wi-Fi and cell, needs data), true maps to
  PRIORITY_HIGH_ACCURACY (GPS) (offline feasibility, Chromium LocationProviderGmsCore.java). No watchPosition online.
- While the fix arrives, the app shows the app's own saved last fix if it is under 6 hours old, labelled with its
  age ("Using your location from 2 hours ago, updating"), so the plan can start at once.
- The resolved place is echoed in words and with the accuracy: "Near Singwahini (PIN 843317), Sitamarhi, Bihar.
  GPS, accurate to 40 m". District comes from point-in-polygon on the district layer (87-88% right with nearest PIN
  alone, so the polygon is primary; geo_routing feasibility). Locality and PIN come from the nearest post office
  (median 1.9 km away). Nominatim reverse geocoding is an optional nicety, cached and never on the critical path.
- Accuracy over 1,500 m: the place line turns amber, "Approximate (about 3 km). Is this right?" with Yes and
  "Change location". Over 2,000 m: also "Turn on precise location for this app", because Android approximate
  permission forces low accuracy (offline feasibility, inferred from Chromium source, not tested).
- "Is the patient here?" sits under the place line with Yes selected. "No, the patient is somewhere else" opens
  Change location. This covers a worker who is helping a patient by phone.

### 5.2 Change location (all four input types, never the default)

One sheet with a single smart field plus a map button:

- PIN code: 6 digits, inputmode=numeric. Resolved on the phone from India Post centroids (works offline). The echo
  shows the post office and district, and warns when the PIN spans two districts.
- City, district or village: typed name. Online, Nominatim search (countrycodes=in, on submit, not per keystroke,
  cached, 1 request per second for the whole app) plus the gazetteer. An ambiguous name lists every match with
  district and state and the user picks; it never guesses ("Muhra" matched Gaya, Bihar and Damoh, MP in the
  geo_routing test). A district name sets the query point to the district headquarters town and labels results "for
  Sitamarhi district, measured from Sitamarhi town" (assumption; the planner's Area view covers the whole district).
- Coordinates: "26.8473, 85.5805" in decimal degrees, validated inside the India bounding box, echoed back as the
  nearest post office and district.
- Drop a pin: opt-in Leaflet map with OSM tiles (about 220 KB for the first view, geo_routing feasibility). Online
  only. The marker has an accessible name and the pin result is echoed in words like every other input.

The single field detects the type: 6 digits is a PIN, two numbers is coordinates, anything else is a name search.

### 5.3 Offline location ladder (the exception)

When there is no data connection (5.5 says how the app decides), the order is:

1. GPS from satellites. GPS needs no data on Android Chrome when enableHighAccuracy is true (offline feasibility,
   Chromium source and docs; time to first fix offline not tested on a device). The app uses
   watchPosition({enableHighAccuracy: true, maximumAge: 0, timeout: 120000}), accepts the first fix with accuracy
   of 1,000 m or better (a Bihar PIN averages about 107 km2), saves it, and stops the watch. The screen says "No
   internet. Getting GPS from satellites. Stand outside, this can take up to 2 minutes" with a progress ring that has
   no time limit on the user and a "Choose place instead" button always visible.
2. Last saved fix, any age, from IndexedDB, with its age and distance shown ("Last GPS fix: today 09:14, Sitamarhi").
   The app stores {lat, lon, accuracy, time} itself; the browser's maximumAge cache is per page load and can be
   evicted (W3C Geolocation spec, offline feasibility).
3. Offline picker: PIN (numeric), or district then post office from a list (9,058 Bihar post offices ship in the
   pack), or coordinates typed in. Village name search offline uses post office names only and finds far fewer
   places (1 of 4 test villages), so the picker leads with PIN and district lists.

### 5.4 GPS denied or unavailable online

Same as 5.3 steps 2 and 3, plus the online name search and the map pin. Focus moves to the PIN field and a status
message is announced: "Could not get location (permission denied). Type the PIN code." This exact behaviour passed
in the accessibility feasibility offline test.

### 5.5 How the app decides it is offline

navigator.onLine alone is not trusted. The app treats itself as offline when navigator.onLine is false, when an API
call fails, or when it takes longer than 8 s. fetch("/api/ping", {redirect: "manual"}) returning opaqueredirect means
the Databricks session expired, not offline: the app then says "Sign in again to get live results; showing saved
results meanwhile" (offline feasibility, simulated proxy).

## 6. Service input

The user knows the service. The app offers four ways to say it, all ending at the same confirmed service.

1. Tiles (default, works offline, cannot be misread). Seven tiles in a fixed order so muscle memory builds: Delivery
   by operation (emergency C-section), Newborn intensive care (NICU), Accident and injury (trauma), Burns, Dialysis,
   MRI scan, Heart operation (cardiac surgery). Each has an icon, the Hindi label in large type and the English
   label below. An eighth tile, "Other / not sure", opens "Describe in your words". The seven match the decision
   layer's service keys (MODEL_SPEC_v1.md 6.4).
2. Search with synonyms (works offline). A search field above the tiles filters them from a lexicon of English,
   Hindi, Hinglish and Marathi names: "khoon saaf karna", "kidney machine", "operation se delivery", "LSCS", "MRI",
   "badi machine wali jaanch", "jalna". It runs in the browser from the lexicon table in the pack.
3. Describe in your words (online). A text field with lang set to the UI language, so the Android keyboard's voice
   typing works (not tested in the app), and a mic button using the Web Speech API where it exists (server-side on
   Android, needs data; not tested on a phone). The text goes to databricks-meta-llama-3-3-70b-instruct at
   temperature 0 with a strict json_schema whose service field is an enum (36/36 correct across English, Hindi,
   Hinglish and Marathi in the voice_language test; Gemma is not used because it sent a heart attack to trauma).
   The answer is shown as a confirm chip that quotes the decisive phrase: "Dialysis, because you wrote 'khoon saaf
   karwana hai'". If the decisive phrase is not a substring of the input, or the service is "other", the app shows
   the tiles instead. Offline, the same field falls back to the in-browser lexicon match and the same confirm chip.
4. Scan the referral note (online). Camera input (input type=file accept=image/* capture=environment), resized in
   the browser to about 1,024 px, sent once to databricks-llama-4-maverick (9/9 service right on test documents,
   resisted the injection; vision feasibility) with a 15 s timeout. The deterministic guard must pass: the trigger
   phrase appears verbatim in the detected text, the keyword lexicon agrees on the service, and instruction-like
   lines are flagged. The confirm screen quotes the note: "We read: 'Refer to higher centre for dialysis'. Looking
   for: a dialysis centre. [Yes, that is right] [Change]". That quote becomes the first line of every WHY card in
   this session ("Referral note says: ..."). The photo stays in memory for one call and is never stored or logged,
   because notes carry names and clinical data. On any 400, 429, timeout or unparseable reply, the tiles appear with
   "Could not read the note. Please tap the service."

Not offered: photos of the patient's body, injuries or wounds. Section 13 explains why.

### 6.1 Danger check

After the service, one screen of six tick boxes, fixed and not model-driven (vision and voice feasibility both say
model red flags are inconsistent): heavy bleeding, breathing trouble, unconscious or fitting, labour with bleeding or
baby stuck, chest pain, burn on the face or a large area. Plus a deterministic danger-word list over any typed or
read text. Any tick shows a red "Call 108 now" bar at the top of every later screen, and the plan uses the
emergency wording ("call before you leave", backups first on screen). "Skip" is a large button: the urgency profile
already comes from the service (MODEL_SPEC_v1.md 6.4), and the ranking never changes with the ticks, only the plan
wording and the action order.

## 7. Screens (ASCII wireframes, 360 px phone width)

Legend: [ ] button, ( ) radio, [x] tick box, {..} live data, ~ amber, ! red, ? grey unverified.

### S1 Home: location and service

```
+--------------------------------------+
| Referral Saathi        [Hindi|EN] [=]|
|--------------------------------------|
| Where is the patient?                |
| (o) {Near Singwahini, PIN 843317}    |
|     {Sitamarhi, Bihar}               |
|     GPS, accurate to {40 m}          |
|     Patient is here  [Change place]  |
|--------------------------------------|
| What does the patient need?          |
| [ search: kidney, delivery, MRI... ] |
| +----------------+ +----------------+|
| | (icon) Operation| | (icon) Navjaat ||
| | se delivery    | | ICU            ||
| | Emergency      | | NICU           ||
| | C-section      | |                ||
| +----------------+ +----------------+|
| | Accident/chot  | | Jalna (burns)  ||
| +----------------+ +----------------+|
| | Dialysis       | | MRI scan       ||
| +----------------+ +----------------+|
| | Dil ka operation| | Other/not sure||
| +----------------+ +----------------+|
| [camera] Scan referral note          |
| [mic] Describe in your words         |
|--------------------------------------|
| Saved for offline: Bihar, 21 Nov     |
+--------------------------------------+
```

First run, before permission: the location block shows one full-width button "[pin] Use my location (GPS)" with
"Change place" as a small link beside it.

### S1a Locating with no internet

```
+--------------------------------------+
| ~ No internet. Using saved data      |
|   from 21 Nov 2026 (3 days ago)      |
|--------------------------------------|
| Getting GPS from satellites          |
|      ( spinner, no time limit )      |
| Stand outside, under open sky.       |
| This can take up to 2 minutes.       |
|                                      |
| Meanwhile:                           |
| Last GPS fix: today 09:14            |
| Near Singwahini, Sitamarhi  [Use it] |
|                                      |
| [Choose place instead]               |
|   PIN code   |  District -> village  |
+--------------------------------------+
```

### S1b Change location sheet

```
+--------------------------------------+
| Change place                     [x] |
| PIN, town, district or "lat, lon"    |
| [ 8433__                           ] |
|--------------------------------------|
| PIN 843317                           |
|  Singwahini BO, Sitamarhi, Bihar     |
|  ~ This PIN also covers part of      |
|    Sheohar district                  |
| [Use this place]                     |
|--------------------------------------|
| [map] Drop a pin on the map          |
|       (needs internet, about 220 KB) |
| [pin] Back to my GPS location        |
+--------------------------------------+
```

A name that matches several places shows a list: "Muhra, Gaya, Bihar / Muhra, Damoh, Madhya Pradesh", and the user
picks one.

### S2 Confirm what we understood (scan or words)

```
+--------------------------------------+
| We read on the note:                 |
| "Refer to higher centre for          |
|  dialysis"                           |
|                                      |
| Looking for: a dialysis centre       |
|                                      |
| [ Yes, that is right ]               |
| [ Change service ]                   |
|                                      |
| The photo is not saved.              |
+--------------------------------------+
```

### S2b Danger check

```
+--------------------------------------+
| Is any of this happening now?        |
| [ ] Heavy bleeding                   |
| [ ] Breathing trouble                |
| [ ] Unconscious or fitting           |
| [ ] Labour with bleeding / baby stuck|
| [ ] Chest pain                       |
| [ ] Burn on face or large area       |
|                                      |
| [ None of these, continue ]          |
+--------------------------------------+
  Any tick:
+--------------------------------------+
| ! [phone] CALL 108 NOW (free)        |
|   Then come back for the hospital    |
+--------------------------------------+
```

### S3 The plan

```
+--------------------------------------+
| Dialysis near Singwahini, Sitamarhi  |
| GPS, 40 m | live data | [Read aloud] |
|--------------------------------------|
| CALL FIRST: option 1, it is the call |
| that changes the plan most           |
|--------------------------------------|
| 1  [check] LIKELY offers dialysis    |
|    {Kidney Care Centre, Sitamarhi}   |
|    {24 km}, about {25-45 min}        |
|    How sure: {0.81} (0.70 to 0.89)   |
|    "6 haemodialysis machines in a    |
|     dedicated unit" [source]         |
|    [phone Call ahead] [Why this?]    |
|--------------------------------------|
| 2  ? NOT VERIFIED: call to confirm   |
|    {Sadar Hospital, Sitamarhi} (govt)|
|    {19 km}, about {20-35 min}        |
|    How sure: {0.46} (0.30 to 0.62)   |
|    [phone Call ahead] [Why this?]    |
|--------------------------------------|
| 3  [check] LIKELY offers dialysis    |
|    {Nephro Centre, Muzaffarpur}      |
|    {71 km}, about {1 h 10 - 2 h}     |
|    [phone Call ahead] [Why this?]    |
|--------------------------------------|
| Chance at least one works: {0.93}    |
| (assumes options fail independently) |
| [Why not the nearer ones?]           |
| [Get there]  [Send slip to family]   |
+--------------------------------------+
```

Notes: the band is shown by icon, word and colour together. The backup row in a different leakage group is chosen by
the decision layer, since copied records fail together. In an emergency profile the header turns red, the 108 bar
sits above option 1, and the call-first line reads "Call before you leave".

### S4 Why this facility (one recommendation, plain level)

```
+--------------------------------------+
| < Plan     Option 1                  |
| {Kidney Care Centre, Sitamarhi}      |
| [check] LIKELY offers dialysis       |
|--------------------------------------|
| SAY THIS TO THE FAMILY  [Read aloud] |
| "Yahan dialysis ki 6 machine hain,   |
|  aisa unki listing mein likha hai.   |
|  Yeh 24 km door hai. Hum pehle phone |
|  karke pakka kar rahe hain."         |
|--------------------------------------|
| Referral note says: "Refer to higher |
| centre for dialysis"                 |
|--------------------------------------|
| WHY WE THINK IT OFFERS DIALYSIS      |
| From its own listing:                |
| [equipment] "6 haemodialysis machines|
|  in a dedicated unit"                |
| [procedure] "Haemodialysis and       |
|  peritoneal dialysis"                |
| Source: one of 3 web pages [show]    |
|--------------------------------------|
| IS IT REAL  Own website; phone not   |
| shared with other listings           |
| WHERE  PIN, map point and town agree |
| (within 3 km)                        |
| WHAT WE IGNORED  "Dialysis at City   |
| Hospital, Patna" - names a different |
| hospital, so it does not count       |
|--------------------------------------|
| HOW SURE  0.81 (0.70 to 0.89)        |
| Of 22 places we checked with scores  |
| like this: 18 confirmed, 1 wrong,    |
| 3 no public information              |
|--------------------------------------|
| WHY THIS BEFORE OPTION 2             |
| Option 2 is 5 km nearer. Distance    |
| alone favours it 1.4x. This one's    |
| evidence is 1.8x stronger (0.81 vs   |
| 0.46). So this one ranks first.      |
|--------------------------------------|
| DISTANCE  24 km straight line x 1.26 |
| = about 30 km road, 25-45 min        |
| (rough estimate) [road route online] |
|--------------------------------------|
| [Show the numbers]  [Call ahead]     |
+--------------------------------------+
```

The numbers in this mock are illustrative. The real card fills each line from one stored row (MODEL_SPEC_v1.md 7.1).

### S4b Why not the others

```
+--------------------------------------+
| < Plan   Places we looked at and     |
|          did not put first           |
|--------------------------------------|
| {Shanti Clinic} 6 km                 |
| x Not offering: "dialysis" only      |
|   appears in a list of 40 services,  |
|   nothing else backs it  [see text]  |
|--------------------------------------|
| {Eye Hospital, Sitamarhi} 9 km       |
| x Ruled out: its dialysis sentence   |
|   names another hospital [see text]  |
|--------------------------------------|
| {Life Hospital} 11 km                |
| ? Not sure where it is: PIN says     |
|   Sitamarhi, map point says Patna    |
|   (130 km apart)                     |
|--------------------------------------|
| 14 more within 50 km have no         |
| dialysis evidence. [list]            |
+--------------------------------------+
```

Each line is one reason from the stored row: band Unlikely with its rule, rejected atoms with reason, or a location
conflict from the location head.

### S5 How we decided (one click deeper, for coordinators and judges)

```
+--------------------------------------+
| < Why   Numbers for option 1         |
| Offers dialysis: 0.81                |
| Points (20 points doubles the odds)  |
|  base, private hospital      -18     |
|  own sentences, 2 fields     +46     |
|  equipment with a count      +14     |
|  record merges 12 sources    -6      |
|  no contradicting sentence   +3      |
|  ------------------------------      |
|  total                       +39     |
|  -> 0.81 (0.70 to 0.89)              |
| Band rule:                           |
|  [x] P_S >= 0.70  [x] location >=0.7 |
|  [x] exists >= 0.7 [x] own sentence  |
| Without the 2 quoted sentences:0.34  |
| Exists 0.93 | Location 0.88          |
| Rank: 0.93 x 0.81 x 0.45 = 0.34      |
| [Model card] [Track record] [Row ID] |
+--------------------------------------+
```

Rows come from the fusion contributions table; the app recomputes the total and the rank product and refuses to
render if they disagree (MODEL_SPEC_v1.md 7.4).

### S6 Call ahead

```
+--------------------------------------+
| Call {Kidney Care Centre}            |
| {+91 62xx xxx xxx}   [phone CALL]    |
| Read this (Hindi | EN) [Read aloud]  |
|--------------------------------------|
| 1 "Namaste, main ASHA hoon. Kya yeh  |
|   Kidney Care Centre, Sitamarhi hai?"|
|   ( ) Yes  ( ) Wrong number          |
| 2 "Mere paas ek mareez hai jise      |
|   dialysis chahiye."                 |
| 3 "Kya aaj ya kal slot hai?"         |
|   ( ) Yes  ( ) No                    |
| 4 "Naye mareez lete hain? Ek session |
|   kitne ka? PM-JAY chalta hai?"      |
| 5 "Agar nahin, paas mein kaun sa     |
|   hospital kar sakta hai?"           |
|   [ type what they said ]            |
| 6 "Pahunch kar kisse milein?"        |
|   [ name ]                           |
|--------------------------------------|
| What did they say?                   |
| [Yes, they can] [No] [No answer]     |
+--------------------------------------+
```

The script comes from links.py call_script with the per-service questions (actions feasibility). Question 1 checks
the number reaches this facility, because the audit found phones shared across 3 or more cities. The call button
appears only when the number passes links.e164_india and the decision layer's phone trust; otherwise "No working
phone in our data" or "May be a directory number". "No" or "No answer" promotes backup 1 and refreshes S3 with
"Option 1 said no at 10:42". The outcome (facility, service, outcome, date, PIN; no patient data) is saved, queued
in IndexedDB when offline, and becomes a label for the turn-away rate and phone trust (proposal_feedback.md).

### S7 Get there

Emergency profile (trauma, burns, emergency C-section, NICU):

```
+--------------------------------------+
| ! [phone] Call 108 ambulance (free)  |
| [phone] Call 102: free transport for |
|   pregnant women and babies (JSSK)   |
|   If 102 does not answer, call 108   |
|--------------------------------------|
| Tell the crew: "Please take us to    |
| {Kidney Care Centre}". If they       |
| cannot, the best government place in |
| reach is {Sadar Hospital, 19 km}.    |
| Free delivery under JSSK applies in  |
| government hospitals.                |
|--------------------------------------|
| If no ambulance in 20 minutes:       |
| [car] Uber (destination filled)      |
| [car] Ola car (destination filled)   |
| [map] Directions in Google Maps      |
+--------------------------------------+
```

Non-emergency profile (dialysis, MRI, elective cardiac surgery): directions first, then Uber, Ola auto (and Ola
"ride later" for the next dialysis session), Rapido and Namma Yatri as "open app" only with a copy-address button,
since neither has documented destination parameters (actions feasibility). Auto and bike are hidden for labour and
sick newborns. When the facility's coordinates are low trust, the Maps link is built from "name, town" and the
screen says so. Every link is a tap the user makes; ride and map links were not tap-tested on a phone yet
(tap_test.html exists for that).

### S8 Referral slip

```
+--------------------------------------+
| REFERRAL SLIP   21 Nov 2026 10:45    |
| Service: Dialysis                    |
| Go to: {Kidney Care Centre}          |
|   {Station Road, Sitamarhi 843302}   |
|   Phone {+91 62xx xxx xxx}           |
|   Ask for: {name from the call}      |
|   Map: {google maps link}            |
| Why this place (in Hindi):           |
|   Their listing says 6 dialysis      |
|   machines. We phoned: they have a   |
|   slot today.                        |
| If they say no: {Sadar Hospital,     |
|   19 km, phone ...}                  |
| Emergency: 108. Pregnancy/baby: 102  |
| Carry the PHC referral note too.     |
| Sent by ASHA: ______ (optional)      |
| From Referral Saathi, data of 21 Nov |
|--------------------------------------|
| [SMS to family] [WhatsApp] [Show big]|
+--------------------------------------+
```

The slip is self-contained text, because the app has no anonymous access and a link to it would be useless to the
family. SMS works without mobile data (it uses the SIM). "Show big" fills the screen with large text for the family
to photograph. A Hindi-only slip is 1 to 3 SMS segments in Latin script; in Devanagari it needs UCS-2 at 70
characters per segment, so the SMS version uses a short Devanagari template (about 4 segments, estimate) and
WhatsApp gets the full one. No patient name is asked or stored; the worker can write it by hand on paper.

### S9 Offline answer

```
+--------------------------------------+
| ~ NO INTERNET. Saved answer from     |
|   21 Nov 2026 (3 days ago)           |
| Dialysis near PIN 843317 (GPS fix is |
| 4 km from the PIN centre)            |
|--------------------------------------|
| 1 [check] LIKELY  {Kidney Care Ctr}  |
|   24 km straight line, road about    |
|   30 km (rough)                      |
|   "6 haemodialysis machines..."      |
|   [phone Call ahead]  (works without |
|   internet)                          |
| 2 ? NOT VERIFIED {Sadar Hospital}    |
| 3 [check] LIKELY {Nephro Centre}     |
|--------------------------------------|
| Not available offline: note scan,    |
| map, live road times, new search     |
| outside Bihar.                       |
| [SMS slip to family] [Call 108]      |
+--------------------------------------+
```

After 30 days the banner is amber with "phone numbers may have changed"; after 90 days it turns red.

### S10 Compare (coordinator depth)

```
+--------------------------------------------------------------+
| High-risk delivery near Wardha (district)   [Export record]  |
|--------------------------------------------------------------|
|        | Band   | P_S (range) | Exists | Where | km  | min    |
| A Govt | Likely | 0.84 .72-.91| 0.97   | 0.95  | 18  | 20-35  |
| B Pvt  | Likely | 0.78 .64-.88| 0.91   | 0.90  | 31  | 30-55  |
| C Pvt  | Unver. | 0.52 .33-.70| 0.88   | 0.62  | 12  | 12-25  |
| D Govt | Unver. | 0.48 .30-.66| 0.99   | 0.97  | 44  | 40-70  |
|--------------------------------------------------------------|
| Trade-off: C is nearest but location is in doubt (PIN and    |
| map point 40 km apart). A ranks first: evidence 1.6x, ...   |
| [Pareto view: success chance vs distance]                    |
| [Open WHY / HOW for any row]                                 |
+--------------------------------------------------------------+
```

Export record: a plain-text and CSV decision record with the query, location echo, ranked rows, quotes, model hash,
data snapshot date and the coordinator's note, for their supervisor.

### S11 Area (planner depth)

```
+--------------------------------------------------------------+
| Trauma, Sitamarhi district            [Print wall chart]     |
|--------------------------------------------------------------|
| Expected providers in district: 0.6   P(none): 0.41          |
| ! Gap: no Likely trauma care within 25 km for 9 of 18 blocks |
|--------------------------------------------------------------|
| Standing referral plan by PIN                                |
| PIN    | first choice      | backup         | call first     |
| 843317 | Sadar Hosp, 19 km | Med College 71 | Sadar          |
| 843302 | ...                                                 |
|--------------------------------------------------------------|
| Caveat: low web presence looks like a gap. Verify on ground. |
| [Download this as the offline pack for field workers]        |
+--------------------------------------------------------------+
```

This reads the planner-mode output (MODEL_SPEC_v1.md 6.8, marked optional, cut second). If it is cut, Area shows
only the standing referral plan table, which is the offline pack in readable form.

### S12 Offline and settings

```
+--------------------------------------+
| Saved for offline use                |
| Bihar + nearby border facilities     |
| 110 KB, saved 21 Nov 2026            |
| Data version {snapshot} {model}      |
| [Update now]  (auto when online)     |
| [Add another state] [All India 1.9MB]|
| [Download offline copy (HTML file)]  |
|--------------------------------------|
| Language: (o) Hindi ( ) English      |
| Read aloud: on (Hindi voice found)   |
| Detail: (o) Quick ( ) Compare ( )Area|
| Text size: [A-] [A+]                 |
| Unsent call results: 2 (send online) |
+--------------------------------------+
```

## 8. How the reasoning for each recommendation is shown and backed by data

Three layers per option, same rows underneath:

1. Say this to the family (S4 top, and on the slip). Two or three plain Hindi sentences from a template with the
   numbers inserted by code: what the listing says, how far, what we did to check. Read aloud with speechSynthesis
   when a Hindi voice exists (getVoices); the button is hidden otherwise.
2. Why card (S4). Fixed sections, each filled from one field:
   - Referral note quote (only if scanned or typed): the decisive phrase from the user's own input.
   - Evidence quotes: verbatim claim_atoms text with its field tag (equipment, procedure, capability, description).
     Source shows the record's source URLs as "one of these pages", because there is no sentence-to-URL map
     (model spec 7.1). Quotes stay in their original language; a Hindi gloss can be added only with placeholder
     protection and the verbatim check, labelled "translation" (voice_language feasibility: direct translation
     broke spans in 4/4, placeholder mode passed 4/4).
   - Is it real (existence head), Where (location votes, and conflicts in words), What we ignored (rejected atoms
     and their stored reason).
   - How sure: P_S with its 90% interval in numbers and words, plus the band's track record as three counts
     (confirmed, wrong, no public information) with n. When the existence head is prior-only, the card says
     "existence weights are expert settings, not learned".
   - Why this before a nearer option: the exact ratio sentence from model spec 6.7.
   - Distance and time: straight-line km, the road factor, and a time range, labelled with its source. Online, the
     top 3 to 5 get one OSRM table call (3 s timeout, cached) and the line becomes "road route from OpenStreetMap,
     free-flow, real trips are slower". Offline or on OSRM failure: straight km x 1.26 at 69 to 40 km/h, "rough
     estimate". The measured rural Bihar circuity is 1.26 (95% CI 1.23-1.34) against the 1.3 the spec assumes; the
     app prints whatever factor the decision layer used, and we recommend the decision layer adopt the measured one.
   - Call first: the plan's call-first marker ("this call changes the plan most": the stored counterfactual "if a
     call confirms B, B ranks first").
3. How card (S5). Points waterfall per head, band checklist, counterfactual without the quoted sentences, ranking
   arithmetic, links to the model card, calibration plot and the reliability row behind each term.

Why not the alternatives (S4b) lists every nearer facility that was skipped, with its one stored reason. When the
decision layer abstains ("No facility within 150 km has enough public evidence that it offers emergency
C-section"), S3 says that sentence first, then lists Unverified options under "Call to confirm" in grey, and adds
the outside option: "District hospital: the public standard says this level should offer it; not verified in our
data".

Every number is a tap target that opens a small sheet: field name, value, table and row id, data snapshot date.

## 9. Offline mode in full

What works with no data connection:

| function | offline behaviour | basis |
| --- | --- | --- |
| open the app | service worker serves the cached shell, network first for navigations, cached shell on network error or any status >= 500 | offline feasibility, simulated cookie-auth proxy (passed); real *.databricksapps.com proxy not tested |
| GPS | satellite fix with enableHighAccuracy true; watchPosition up to 120 s; accept <= 1,000 m | Chromium source; time to first fix not tested on a device |
| location fallback | last saved fix (IndexedDB), then PIN, then district -> post office picker, then coordinates | offline and accessibility feasibility tests (PIN fallback passed) |
| service input | tiles, lexicon search, lexicon match of typed words | runs in the browser |
| plan | precomputed decision-layer plan per (PIN, service): first choice, 2 backups, call-first, band, P_S and interval, 2 quotes with source, phones | pack format from build_pack.py; real plan contents not built yet (placeholders today) |
| distances | straight line from the GPS fix to each facility x 1.26, time range at 69 to 40 km/h | geo_routing travel_time.py |
| reasoning | Why card text (templates in Hindi and English ship in the app; numbers from the pack) | templates, no LLM |
| call ahead | tel: opens the dialer; calls need no data | actions feasibility (tel: semantics; not tapped on a phone yet) |
| 102 / 108 / 112 | tel: links, always | same |
| referral slip | built on the phone, sent by SMS (SIM), WhatsApp queued by the app if no data | sms: and wa.me links |
| call outcomes | queued in IndexedDB, sent on next online open | design |

What does not work offline, and what the user sees instead:

| function | offline replacement |
| --- | --- |
| scan referral note (vision model) | tiles with "Note scan needs internet" |
| describe by voice (Web Speech on Android is server-side) | keyboard typing with the lexicon match |
| LLM free-text mapping | lexicon match with the same confirm chip |
| village name search (Nominatim) | PIN, district -> post office list |
| drop a pin (map tiles) | hidden; picker instead |
| live road times (OSRM) | straight line x 1.26, labelled rough |
| results outside the saved state | "Not saved for offline: {state}. Connect once to add it." |

The pack:

- Scope: the state of the first online GPS fix plus facilities across the border that serve it. Bihar with the
  offline PIN and post office picker is 110 KB gzip and 196 KB in IndexedDB; the largest state (Uttar Pradesh) is
  228 KB gzip; all India is 1.85 MB gzip (offline feasibility, measured on the placeholder pack; real contents will
  grow, still under 1 MB per state by estimate).
- Download: in the background after the first online result, never on the critical path. navigator.storage.persist()
  is requested after install. Stored only in IndexedDB.
- Versioning: snapshot date plus model hash. On every online open the app fetches /api/pack/version and, if it
  changed, downloads the new pack and swaps it in one transaction. The old pack stays until the new one is complete.
- Freshness: every offline answer shows "Saved <date> (N days ago)": amber after 30 days, red after 90 with "phone
  numbers may have changed". Staleness never blocks an answer.
- GPS fix to pack key: the nearest PIN centroid in the pack. If the fix is more than 10 km from that centroid, the
  app uses the 10 km grid cell variant instead (47 KB gzip for Bihar) and says which one it used. PIN centroids that
  fall outside their state are dropped at build time.

Backup channels with no internet:

- Download offline copy: a single HTML file with the state pack embedded (Bihar 475 KB, 112 KB gzip). It opened
  from file:// in desktop Chromium with the network off, with GPS and PIN fallback working. Opening it from Android
  Downloads was not tested. It can be shared to other workers as a WhatsApp document while anyone has data.
- SMS: this weekend only as a demo. A team Android phone runs android-sms-gateway, and a laptop answers "DIALYSIS
  843317" from the pack with sms_reply.py (2 to 3 SMS segments per reply, measured). Presented as a demo, not a
  service. A real two-way SMS line needs DLT registration through an Indian entity (days to weeks) and is roadmap.
- Voice call to a human: the plan always ends in a phone call, which works on 2G voice with no data.

## 10. Actions

Order depends on the urgency profile in model spec 6.4 and the actions feasibility recommendations:

- Emergency (trauma, burns, emergency C-section, NICU transfer): 108 first; 102 beside it for pregnancy and infants
  with "if 102 does not answer, call 108"; call-ahead to option 1 while waiting or by a second person; ride links
  only under "If no ambulance comes in 20 minutes" (the 20 is an assumption shown as such); slip to family.
  Because 108 dispatch picks the nearest centre and 102 carries to CHCs or government hospitals, the screen always
  names the best public facility in reach as the crew fallback, and states the JSSK free-care condition when the
  first choice is private.
- Recurring (dialysis): call-ahead first (slot, new patients, cost per session, PM-JAY), directions, Ola "ride
  later" for the next session, slip with the weekly plan.
- Elective (MRI, cardiac surgery): call-ahead (machine working, next slot, cost; surgeon this week, cath lab),
  directions with the transit option, slip with the evidence card.

Ride-hailing: Uber via the documented /looking?drop[0]= link with the legacy /ul/ form as backup, pickup always
my_location so location is shared only by the user's own ride app; Ola universal link with drop_lat, drop_lng,
drop_address (may drop the destination without an affiliate token; not tested). Rapido and Namma Yatri open the app
only. Automatic booking is killed (section 13).

## 11. Accessibility

Framework choice follows the accessibility test: FastAPI serving one hand-written HTML page with vanilla JS had 0
axe-core violations, 1.8 KB on the wire and showed the location button in 0.44 s on the 2G profile, against 40 to
50 s for Streamlit, Dash and Gradio.

WCAG 2.2 AA, made concrete:

- Gate: 0 axe-core violations (wcag2a, wcag2aa, wcag21a, wcag21aa, wcag22aa, best-practice) in every state: start,
  locating, GPS denied, offline, results, why, call, slip. Reuse measure.py and offline_test.py before each build.
- Targets: primary buttons at least 48 x 48 CSS px, nothing under 24 x 24 (2.5.8). Tiles are about 160 x 96 px.
- Contrast: text 4.5:1, icons and borders 3:1, in light and dark. Bands never rely on colour: icon plus word plus
  colour (1.4.1).
- Language: lang on html and on every string in another language (3.1.2), so TalkBack switches voice.
- Status: the locating, offline and plan-updated messages go to a role=status live region (4.1.3). On a failure,
  focus moves to the next input (the PIN field).
- Reflow at 320 px and 200% text (1.4.10, 1.4.4). The wireframes above are one column.
- No time limits on the user (2.2.1). The GPS wait has a "Choose place instead" button, not a countdown.
- prefers-reduced-motion respected; the only motion is the GPS spinner.
- Known gap: 3.3.8 (accessible authentication) cannot be met for the Databricks workspace sign-in, which is outside
  the app. The app keeps the session as long as Databricks allows and works offline after it expires.

Low literacy (NFHS-5: 96 districts have women's literacy under 60%, measured in the accessibility test):

- Icon plus word on every action; Western digits with units ("24 km", "25-45 min").
- Read aloud on S3, S4, S6 and the slip; typing kept to the PIN and optional notes.
- The call script is the main interface for trust: a phone call is something every worker already does well
  (Medhi et al. 2011 found live operators far more accurate than text UIs for health tasks; cited by the
  accessibility test, not user-tested by us).
- Numbers sit next to words: "How sure: 0.81, likely".

Languages: Hindi and English at launch, chosen from the phone's language with a toggle on every screen. All card
text is templates, so each new language is a strings file, not a model call. Marathi, Bengali, Tamil and Telugu
strings are roadmap; until a native speaker checks them they are not shipped (fluency not tested).

Low bandwidth (budgets from the accessibility test): critical path to the location button 50 KB gzip or less in 5
requests or fewer, no third-party hosts and no web fonts (system fonts with Noto Sans Devanagari fallback where
installed); plan response 20 KB JSON or less; repeat visit 5 KB or less via the service worker; the map is opt-in;
photos resized to about 1,024 px on the phone.

## 12. Creative features

1. Say this to the family: every recommendation comes with two or three Hindi sentences the worker can read or
   play aloud, so the reasoning travels from the model to the family without a second translation step.
2. The call is the verification: the call-ahead script starts by checking the number reaches the right facility,
   and its Yes / No / No answer outcome replans on the spot and becomes a label for the model's track record. The
   app marks which call is worth making first.
3. Evidence we ignored: the card shows the sentences we threw away (another hospital's dialysis unit) and why. This
   is the clearest proof that a listing's claim is checked, not repeated.
4. Ambulance-aware plan: "If the crew cannot take you to A, the best government place in reach is B", because 108 and
   102 do not take requests for private hospitals as a rule.
5. The referral note becomes the first link in the reasoning chain: the scanned phrase is quoted on the confirm
   screen and at the top of every WHY card.
6. The planner's standing referral plan is literally the field workers' offline pack, and prints as a wall chart for
   the PHC. One artefact serves the planner and the ASHA.
7. Offline copy as a file: one HTML file per state, shareable by WhatsApp, that answers with GPS and no internet.
8. Trust receipts: every number taps through to its table, row and snapshot date.

## 13. Ideas killed, and why

- Photo of the patient's condition for triage: the users are intermediaries who already know the service, and the
  vision test showed wrong details (back of the hand called the palm) and overcalled severity (Gemma called a
  scratch a deep laceration and routed it to burns). Kept only as "scan the referral note", which quotes text.
- "It does everything for you" from one photo: Chrome will not launch apps without a user gesture, and a wrong
  automatic step costs hours. One tap per action is the design.
- Auto-booking an auto, Uber or ambulance: Uber's request scope is privileged, Ola is invite-only, no public 108/102
  dispatch API exists (actions feasibility). Replaced by prefilled links the user taps.
- An LLM chat that answers or explains: LLMs gave confidence 1.0 to contaminated records. No LLM on the trust or
  explanation path; LLMs only map words and images to one of seven services, with confirmation.
- Runtime LLM translation of the cards: broke quotes, names or numbers in 4/4 direct runs. Templates instead.
- Gemma-3-12b anywhere in the path: obeyed an injected instruction, hit QPS limits, sent a heart attack to trauma.
- Streamlit, Dash or Gradio as the front end: 1 to 1.5 MB per visit, 40 to 50 s to first button on 2G, axe
  violations, and Streamlit cannot reload offline.
- Map-first results: 220 KB and useless offline; the list is the answer, the map is opt-in.
- Continuous location tracking (watchPosition online): battery and privacy cost for no gain.
- District-sized offline packs: 2.6 to 21 KB saves nothing and loses facilities across district lines.
- USSD and a live two-way SMS service this weekend: operator negotiation and DLT registration take days to weeks.
- Patient records, accounts or storing the note photo: personal health data with no need. The slip has a blank
  for the name on paper.
- A single 0 to 100 "trust score": hides the three separate doubts (exists, location, service). Bands plus the
  three numbers instead.
- Push notifications and reminders for dialysis sessions: an .ics recurring reminder is possible but untested on
  Android; skipped unless the demo needs it.

## 14. Tech stack

- Databricks App: FastAPI (pre-installed 0.115) on the Python 3.11 runtime, serving static HTML, CSS and vanilla JS
  plus JSON endpoints: /api/plan, /api/why/{uid}, /api/map-service (LLM text), /api/read-note (vision),
  /api/route (OSRM proxy with cache), /api/geocode (Nominatim proxy with cache), /api/pack/{state},
  /api/pack/version, /api/outcome, /api/ping.
- Data: Unity Catalog tables written by the model layers (pair scores, contributions, claim atoms, plans per PIN and
  service, band record), read through the SQL warehouse at startup into memory (the plan tables are small), so a
  plan request does not wait on the warehouse.
- Model serving: databricks-meta-llama-3-3-70b-instruct (free-text mapping), databricks-llama-4-maverick (note
  reading). Both behind timeouts and the deterministic guards.
- Browser: service worker at "/", IndexedDB for the pack, last fix and queued outcomes, manifest with
  crossorigin=use-credentials, Geolocation API, file input with capture, Web Speech where present, speechSynthesis
  where a voice exists, Leaflet 1.9.4 from cdnjs on demand.
- Geo: district polygons (geoBoundaries ADM2, ODbL) for point-in-polygon, India Post PIN centroids and post offices
  for the picker and locality names, both precomputed into the pack and the server.
- Actions: links.py builders (stdlib only), phone validator links.e164_india.
- Optional demo: android-sms-gateway (Apache-2.0) on a team phone plus sms_reply.py.

## 15. Internet dependencies and fallbacks

| dependency | used for | if it fails |
| --- | --- | --- |
| phone data connection | everything live | offline mode (section 9) |
| Databricks App and its login proxy | the app itself | cached shell and pack; "sign in again" when the session expired; offline HTML copy |
| SQL warehouse | loading tables | tables loaded into memory at startup; last loaded copy kept |
| Llama 3.3 70B endpoint | free-text mapping | lexicon match, then tiles |
| Llama 4 Maverick endpoint | reading the referral note | tiles with a message; demo uses cached replies |
| Google speech (Web Speech on Android) | mic button | keyboard voice typing, typing, tiles |
| OSRM demo server | road times for top 3-5 | straight km x 1.26, range at 69 to 40 km/h, labelled rough |
| Nominatim | village search, friendlier place names | gazetteer, PIN, post office picker |
| OSM tiles and cdnjs (Leaflet) | drop a pin, map view | hidden; picker and list |
| GPS satellites | location when offline | last saved fix, PIN, district -> post office |
| mobile voice network | calls, 102/108, SMS slip | show the slip on screen for a photo; nothing else can replace a call |
| Indian government portals (data.gov.in, PM-JAY) | not used: unreachable from the App (net probe) | n/a |

## 16. How it scores

- Creativity: the reasoning is designed to be relayed, not only read (Hindi "say this to the family", the slip,
  the call script). The call is turned into verification and labels. The planner's plan becomes the worker's
  offline pack. GPS still works with no internet, and the app says so on screen.
- Modeling: the app shows the model as it is: three calibrated heads with per-term contributions, intervals, band
  track records, rejected evidence, an exact ratio for every "why the farther one" and an abstention sentence when
  evidence is thin. The app refuses to render a page whose numbers do not add up. LLMs are confined to input
  mapping with deterministic guards, which matches the measured failure of LLMs on contaminated records.
- Impact: it fits the stated users: low-end phones (1.8 KB shell, 110 KB state pack), Hindi, low literacy, patchy
  data, and actions that end in a real phone call and real transport (102, 108). Coordinators and planners get the
  same rows at more depth, so the choice can be defended upward.
- Hard gate: every recommendation answers WHY (quotes, existence, location, why first) and HOW (contributions,
  rules, trade-off, track record), and cites facility text.

## 17. Three-minute demo story

Setup: the deployed app opened at its own URL on an Android phone mirrored to the screen (judges must be workspace
users to open it themselves). A phone in Pittsburgh would report Pittsburgh, so the demo uses a visible "Demo GPS:
Singwahini, Sitamarhi" switch that injects a fixed fix and labels every screen "DEMO LOCATION" (Chrome DevTools
sensor override as backup). Vision replies for the demo note are pre-run and cached. The Bihar pack is already saved.

- 0:00 to 0:15. "An ASHA in Sitamarhi has a patient whose PHC note says dialysis. She has a cheap phone and one bar
  of signal."
- 0:15 to 0:40. She opens the app. Location fills by GPS by itself: "Near Singwahini, PIN 843317, accurate to 40 m".
  She taps "Scan referral note"; the confirm screen quotes "Refer to higher centre for dialysis". One tap: yes.
  Danger check: none.
- 0:40 to 1:10. The plan: first choice, two backups, chance at least one works, call-first marker. "The nearest
  place with 'dialysis' in its listing is 9 km away. Why is it not here?" Tap "Why not the nearer ones": its
  dialysis sentence names another hospital, so it was ignored.
- 1:10 to 1:40. Tap option 1. "Say this to the family" plays in Hindi. Below it: the quoted sentences with source,
  0.81 with its range, "of 22 like this we checked, 18 confirmed", and the exact sentence on why it beats the nearer
  government hospital. "Show the numbers": the points waterfall adds up on screen.
- 1:40 to 2:05. Call ahead: the script on screen (a teammate plays the facility on a second phone). The answer is
  "no slot today": tap No. Backup 1 moves up at once and the outcome is saved as a label.
- 2:05 to 2:20. Get there and slip: directions and Ola ride-later for dialysis; the Hindi slip goes out by SMS.
- 2:20 to 2:40. Airplane mode on. Reload. The app opens, says "No internet, saved 21 Nov", gets the fix, and gives
  the same plan with the call button still working.
- 2:40 to 3:00. Switch depth to Area on the laptop: Sitamarhi trauma gaps and the standing referral plan, "which is
  the offline pack you just saw". Close on the model card: calibration and track record.

## 18. Risks and open checks

- Not tested on a real Android phone or the real Databricks proxy: GPS time to first fix offline, service worker
  install behind *.databricksapps.com, camera and mic permissions in the app, tel:, intent: and ride links from the
  app. Deploy the offline probe_app and run tap_test.html on a phone before building on these.
- If the service worker fails on the real proxy, offline mode falls back to the downloaded HTML copy, which is less
  automatic (the worker must have downloaded it).
- Offline GPS indoors may never fix; the picker is one tap away, and the last saved fix is shown at once.
- The pack today holds placeholder rankings (straight-line, prototype confidence); the real plans depend on the
  decision layer being built. Sizes are reliable, contents are not yet.
- Travel time: OSRM free flow (median 69 km/h) is optimistic and the spec's 40 km/h is pessimistic; times are shown
  as ranges with their source and the ranking should not separate options closer than about 20%.
- 102, 108 and 112 roles vary by state; only national NHM descriptions were read.
- Hindi strings and the read-aloud voice on Android are not checked by a native speaker or on a device.
- Redistributing a derived pack outside the app (offline HTML file, SMS bot) may conflict with the dataset's
  Marketplace terms; not checked.
- Judges need workspace accounts to open the app; the demo must not rely on them doing so live.
- Only one app of the three-app limit is needed for the product; the probe app uses a second.
