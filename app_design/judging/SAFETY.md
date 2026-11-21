# Safety, ethics and privacy review of the three app concepts

Reviewed: Referral Saathi (field worker lens), Referral Desk (coordinator lens), Setu (planner lens), against the
six feasibility results, MODEL_SPEC_v1.md (bands 5.5, urgency 6.4, abstention 6.6) and the challenge brief.
Date: 2026-11-21. Reviewer stance: an intermediary (ASHA, NGO coordinator, district planner) acting for a patient
who is not holding the phone. The patient bears every error; the intermediary bears the blame for it.

Nothing in this review was tested on a real Android phone or the deployed App. Legal points come from secondary
summaries (law firm articles, search summaries), not from the gazette text, and are not legal advice. Each such
point is marked.

## Verdicts at a glance

| # | Feature | Verdict | Biggest harm if unguarded |
| --- | --- | --- | --- |
| 1 | Scan referral note (photo) | Keep, with guardrails | A third party's medical record leaves the phone; the on-screen "photo is not saved" line overstates what we control |
| 2 | Photo of the patient's condition | Kill (all three concepts already kill it; keep it killed) | Misclassified wound or burn routes or delays emergency care; moves the app toward a regulated medical device |
| 3 | Free text and voice "describe it" | Keep, narrowed | Symptoms get mapped to a service (chest pain to elective cardiac surgery) which is triage by a model |
| 4 | Service tiles and lexicon search | Keep | Cardiac surgery tile picked for a heart attack |
| 5 | Danger checklist and Call 108 bar | Keep, never blocking | An extra screen before 108 in an emergency |
| 6 | GPS default, last fix, change location | Keep, with guardrails | Plan computed for the coordinator's desk or a stale fix, not the patient |
| 7 | Location storage, logging, third parties | Keep, with guardrails | Patient home coordinates in server logs and on OSM servers; a movement history on a shared phone |
| 8 | Ranking, bands, confidence numbers | Keep, with wording changes | "0.81" and "chance at least one works 0.93" read as "they will treat you today" |
| 9 | Why not the others / what we ignored | Keep, with wording rules | Public, wrong "Unlikely" claims about real hospitals |
| 10 | Call-ahead script and outcome buttons | Keep, with guardrails | Call-ahead delays transport in an emergency; a receptionist's "yes" becomes "confirmed" |
| 11 | 108 / 102 transport | Keep, always first in emergencies | Crew takes patient elsewhere and the worker has no fallback |
| 12 | Ride-hailing links | Keep only as a fallback, user-triggered | A ride is chosen over 108 and loses en-route care and free JSSK transport |
| 13 | Referral slip by SMS / WhatsApp / show big | Keep, with guardrails | Health information sent to the wrong or a shared phone; confidence numbers misread by family |
| 14 | Hindi / Marathi templates, read aloud, translation | Keep templates; kill runtime LLM translation of actionable text | A mistranslated instruction or number |
| 15 | Offline pack and offline answer | Keep, with dated staleness | A closed or changed facility recommended from old data with no warning |
| 16 | Offline single-file HTML copy | Keep for own phone; kill forwarding as a feature | A forwarded, edited or years-old copy with swapped phone numbers |
| 17 | SMS demo bot | Keep as demo only | Real patient texts reaching a personal SIM |
| 18 | Referral record (coordinator) | Keep, minimal fields | Patient names typed into a free-text case field |
| 19 | Planner gap view, wall chart, ten-call list | Keep, with caveats on every surface | "Care gap" read as fact when it is missing web presence; a wall chart that never expires |
| 20 | Demo GPS switch and demo phone numbers | Keep for demo, build-flag gated | Shipping with a fake location; dialling a real hospital during judging |
| 21 | Auto-booking, auto-dial, chatbot, LLM explanations | Kill (already killed; keep killed) | Unverifiable or wrong actions taken without the user's tap |

## 1. Scan referral note

What it is: the worker photographs the PHC or doctor's note; Llama 4 Maverick reads it once; a deterministic guard
checks the trigger phrase; the user confirms the service.

Harms:
- The note is a medical record of a third party: name, age, sex, diagnosis, sometimes phone and address. The
  patient, not the worker, is the person whose data it is.
- The photo is sent to a Databricks pay-per-token endpoint. Databricks documents that Foundation Model API requests
  "might" be processed outside the workspace region when cross-Geo processing is on
  (https://docs.databricks.com/aws/en/machine-learning/foundation-model-apis/compliance, read 2026-11-21). A search
  summary of the Databricks model serving docs says inputs and outputs may be stored temporarily for abuse
  monitoring and that the no-training commitment is stated "for all paid accounts"
  (https://learn.microsoft.com/en-us/azure/databricks/machine-learning/model-serving/, not read in full). Whether
  Free Edition counts as a paid account is not checked. So "the photo is never stored" is true for our app only.
- Prompt injection written on the note (tested: Maverick resisted 1 pattern; Gemma obeyed 2/2).
- OCR errors in Hindi (Maverick changed 3 characters in the Devanagari test) leading to the wrong service.
- A user photographs a wound or an X-ray instead of a note, and the model "reads" a service from the image.

Verdict: keep, with guardrails.

Guardrails:
1. Opt-in, never the default path. Tiles stay the default service input.
2. Before the camera opens, one screen: "Ask the patient first. Cover the name with your thumb. Only the line with
   the reason is needed." Then a crop box in the browser (canvas, before upload) that starts on the middle band of
   the image; only the cropped part is sent. Not tested on a phone.
3. Accurate wording on S2 and the camera screen: "We do not save the photo. It is sent once to a text-reading model
   run by Databricks and may be kept by them for a short time for abuse checks." Replace "The photo is not saved".
4. Resize to about 1024 px and strip EXIF in the browser (a canvas re-encode drops it), so the GPS tag and device
   model in the photo's metadata never leave the phone.
5. The server holds the image in memory for one call, never writes it to disk, never logs it or the model's full
   reply. Log only: timestamp, outcome class (ok, timeout, guard_fail), latency.
6. The model prompt asks for transcription only. If the reply has no trigger phrase that is a verbatim substring of
   the transcribed text, or the lexicon disagrees, the app shows the tiles. A service is never inferred from image
   content (an injury photo, an X-ray): those fall to the tiles with "We could not find a referral reason".
7. Lines that look like instructions ("ignore", "system", "you must") are flagged and excluded from the lexicon
   check (already in score.py; keep it as a release test).
8. If the note names a destination hospital, the app shows that hospital first with "Named on the referral note",
   plus our evidence for it, and never silently replaces the doctor's choice. If our data says it is Unlikely, the
   card says "Our public data has little evidence for this service here. Call before you go." It does not say the
   doctor is wrong.
9. Demo uses only the generated notes in feasibility/vision/images (rendered by us, no real patient).
10. Gemma is never on this path (measured: obeyed injection, 429s).

## 2. Photo of the patient's condition

Harms: both vision models misread detail (back of hand called palm) and Gemma overcalled severity (scratch called a
deep laceration, routed to burns). A wrong "not serious" delays emergency care; a wrong "serious" sends a patient
150 km. Assessing a wound or burn from a photo is a medical purpose. CDSCO's Medical Device Software guidance
(CDSCO/MD/GD/MDSW/01/2026, circular dated 21 July 2026, per a law firm summary at
https://natlawreview.com/article/code-compliance-decoding-indias-medical-device-software-guidance) uses a
function-based test and names "image analysis as an aid in diagnosis" as a function that can make software a medical
device. The primary text was not read.

Verdict: kill. All three concepts already kill it. Keep it out of the pitch, the roadmap slide and the demo.

## 3. Free text and voice "describe it in your words"

Harms:
- The feasibility test set mapped symptoms to services: "pregnant, baby breech, pains started" to C-section,
  "chest pain, sweating, left arm numb" accepted as cardiac_surgery (inputs.py X4). That is triage, and for X4 it is
  dangerous: cardiac_surgery has the elective urgency profile (D_s 150 km, top 5 list, Pareto view, spec 6.4), so a
  heart attack would get an elective list.
- Web Speech on Android runs on Google servers (MDN compat data in feasibility/voice_language/sources): the
  patient's symptoms, possibly with a name, go to Google.
- Server-side faster-whisper fallback (Setu) is not tested in the container.

Verdict: keep, narrowed to naming a service, not choosing one.

Guardrails:
1. The danger-word list runs first on every typed or transcribed string, before the LLM. Any hit (chest pain,
   seene mein dard, unconscious, behosh, not breathing, saans nahi, heavy bleeding, khoon, fits, labour with
   bleeding) shows "Call 108 now" at the top. Chest-pain words never map to cardiac_surgery; they show 108 and the
   nearest facility that the data supports for emergency care, with "For chest pain now, call 108. Heart operation
   is a planned service."
2. The LLM output enum gets a value "symptoms_only". When the text describes symptoms but names no service or
   referral phrase, the app does not pick one. It says "We cannot decide the service. Ask the PHC or doctor which
   service is needed", shows the tiles, and shows 108 if a danger word matched.
3. Labour and newborn wording is the one allowed capability mapping, because the destination for a labour
   complication is a facility that can do an emergency C-section. The chip must read "Looking for: a hospital that
   can do emergency C-section", never "Patient needs a C-section".
4. The confirm chip quotes the decisive phrase; no confirm, no search (already designed).
5. The mic button carries "Your voice is sent to Google to turn it into text". Keyboard voice typing has the same
   property on most Android keyboards (not checked); the tiles are the private path.
6. Temperature 0, strict json_schema, Llama 3.3 70B only (36/36 measured on tester-written inputs; Wilson lower
   bound about 0.90, so 1 in 10 errors is not ruled out). Confirmation is the real guard.
7. Release test: add X4-style cases (chest pain, stroke words, snake bite, poisoning) and assert they never reach an
   elective profile.

## 4. Service tiles and lexicon search

Harms: "Dil ka operation" picked for an acute heart problem; "Other / not sure" leaves an intermediary with nothing.

Verdict: keep.

Guardrails:
1. Label the cardiac tile "Heart operation (planned)" / "Dil ka operation (pehle se tay)" and MRI "MRI scan
   (planned)". Under both: "Chest pain or stroke now? Call 108."
2. "Other / not sure" never routes by guess. It shows: 108 (if any danger), the nearest district hospital (the
   outside option, labelled "not verified in our data"), and "Ask the PHC which service is needed".
3. Tile order is fixed (no personalisation), so a worker's muscle memory is safe across updates.

## 5. Danger checklist and Call 108 bar

Harms: Referral Saathi puts the danger check on its own screen (S2b) between confirm and plan, so an emergency gets
one more screen before the plan. A false negative in the checklist or danger words hides the bar. The checklist
items are invented by the team, not taken from an official source (not checked).

Verdict: keep, never blocking.

Guardrails:
1. A Call 108 button is on every screen of an emergency-profile service (trauma, emergency C-section, burns) and
   on S1a while GPS is searching, whether or not a box is ticked. Ticks only make it larger and move it to the top.
2. The checklist is a row on the start or plan screen (as in Referral Desk), not a gate. The plan request is sent
   in parallel, so ticking never delays it.
3. Take the item wording from an official ASHA or NHM danger-sign module and cite it on the model card; until then
   the card says "checklist written by the team, not clinically reviewed".
4. The ranking never changes with ticks (spec 6.4 already says this). The card says "The 108 crew decides where to
   stabilise the patient; this plan is what to ask them for."
5. 108 is a tel: link, so it works offline and needs no data.

## 6. GPS default, last fix and change location

The team rule stands: GPS is the default for every user; typing, PIN, coordinates or a pin are under "Change
location"; offline the app uses satellite GPS, then the last fix, then the offline picker. Nothing below changes the
default. It adds checks so the default cannot silently answer for the wrong place.

Harms:
- The coordinator's or planner's GPS is their desk, not the patient. If "Is the patient here?" defaults to Yes, a
  Nagpur coordinator gets a Nagpur plan for an Ashti patient.
- Rural fixes can be cell-level (km) or Android "approximate" (about 3 km2), and a wrong-district answer looks
  normal (feasibility geo_routing).
- A last fix from yesterday's village is used offline today.
- PIN centroids can be several km off and some are placeholders (all 6 offices of PIN 805129 on one point).

Verdict: keep, with guardrails.

Guardrails:
1. Every plan header, card and slip echoes the place and its source: "Dialysis near Singwahini (GPS, 40 m, 09:14)".
   No answer is shown without the place in words.
2. "Is the patient here?" defaults to Yes in Quick depth and has no default in Compare and Area depth (the user
   must tap one). GPS still fills the field in all depths.
3. Accuracy over 1,500 m: amber "Approximate, is this right?" and one tap to confirm before the plan. Over 5,000 m:
   the plan is held until the user confirms or picks a place.
4. Last fix older than 6 h: shown with its age in the header ("GPS from yesterday 17:40"), and the plan is held
   until "Patient is here" is tapped.
5. PIN or district input always shows its precision ("PIN centre, can be up to 9 km off"; "district HQ town").
6. When two candidates differ by less than about 20% in time, the card says "about the same time", because
   location error is that size (feasibility: 16.5% MAPE on the road factor).

## 7. Location storage, logging and third parties

Harms: an ASHA's phone holds where her patients live; phones are often shared in the household. Coordinates in a
URL query string land in server access logs; coordinates proxied to OSRM and Nominatim reach third-party servers.

Verdict: keep, with guardrails.

Guardrails:
1. On the phone: keep one last fix only (overwrite, no history), plus at most 5 recent PINs (coordinator). Settings
   has "Forget my locations". No continuous watchPosition online (already killed).
2. To the server: send coordinates in a POST body, rounded to 0.01 degree (about 1.1 km). Ranking works on km
   scales (D_s >= 15 km) so this changes no ranking; the exact fix stays on the phone for the on-screen echo.
3. Server logs: run uvicorn without its access log (--no-access-log, https://www.uvicorn.org/settings/) or strip
   bodies and query strings; never print lat, lon, PIN or service together with a user id. Not checked whether
   Databricks App logs capture stdout for other workspace users to read; assume they do.
4. OSRM and Nominatim proxies send only the rounded point or the typed place name, with the app's generic
   User-Agent and no user identity, cached, at about 1 req/s (their usage policies).
5. Slips and shares never contain the patient's location; Google Maps links omit the origin (device location).
6. Planner hotspot points are crash locations, not people; no rounding needed, but do not store them with a user.

## 8. Ranking, bands and confidence numbers

Harms:
- P_S means "a public web check would confirm the listing offers it" (spec 5.6). It does not mean a bed, a doctor
  or a dialysis slot today. A worker reads 0.81 as "81% they will treat her".
- The Likely band targets dev precision >= 0.85 (spec 5.5), so about 1 in 7 Likely options may be wrong by design,
  on small dev samples (22 and 65 checked in the mocks). The current fallback prototype puts 2 of 69,713 pairs in
  Likely, so every demo number is a placeholder.
- "Chance at least one works 0.93" multiplies three uncertain numbers and assumes independence. It is the number
  most likely to be over-trusted, and it is the one with the least support.
- Two-decimal numbers look more precise than they are; intervals such as 0.31 to 0.91 mean "we do not know".
- Public facilities are thin in the data (469 public of 10,088), so the ranking leans private, with cost to poor
  families.

Verdict: keep the model and the numbers, change how Quick depth shows them.

Guardrails:
1. Quick depth shows the band word first and the number in words: "LIKELY offers dialysis (about 8 in 10 such
   listings checked out)". The decimal and interval are one tap away (Why this?). Compare and Area keep decimals.
2. Under every band, one fixed line: "This is about the listing, not about today. Call to check a slot."
3. Drop "Chance at least one works" from Quick depth and from the slip. Keep it in Compare and Area, labelled
   "chance at least one listing checks out (assumes they fail independently)".
4. Interval wider than 0.4: the card adds "We are very unsure about this one."
5. Track record shows n, and "too few checks" when n < 10 (Setu already does); "dev, not final test" until the
   sealed test runs.
6. Unverified stays grey with "NOT VERIFIED: call to confirm" first (designed). Abstention leads with the one
   sentence and always ends with 108 and the district hospital, so the user is never left with nothing.
7. Every private option shows "private: may charge"; the best public option in reach is always listed (the 108 crew
   fallback line), and the call script asks about PM-JAY.
8. The faithfulness check (refuse to render if the numbers do not reproduce the ranking) is a release test, not a
   runtime nicety. When it fails, show the list without numbers and "numbers unavailable", never a blank screen.

## 9. Why not the others and what we ignored

Harms: real, named hospitals are shown as skipped ("its dialysis sentence names another hospital", "Unlikely").
If our extraction is wrong, the app spreads a false negative claim about a real facility, and a worker may avoid a
place that could help.

Verdict: keep. It is the strongest trust feature.

Guardrails:
1. Wording describes our data, never the facility: "Our data has no public evidence of dialysis here", never "does
   not offer dialysis" (spec 5.6 already requires this).
2. Every reason links to the exact sentence and its source pages, so the user can see the evidence.
3. "Unlikely" facilities still have a Call button on the why-not list; a worker may know better locally.

## 10. Call-ahead script and outcome buttons

Harms:
- In an emergency, "call before you leave" delays departure while the worker reaches a switchboard.
- The number reaches a directory, a pharmacy or a different branch (76 refused values found, including '100').
- A receptionist's "yes" is recorded as "confirmed". Wrong button taps poison labels; outcome labels could be gamed.
- The worker may say the patient's name on a call with an unknown party.
- "No answer" demotes the nearest suitable option at night, sending the patient farther.

Verdict: keep, with guardrails.

Guardrails:
1. Emergency profile order: Call 108 first, then call ahead while waiting for the ambulance. The call screen says
   "Do not wait for this call to send the patient."
2. tel: only after links.e164_india passes and the number is not a directory number (designed). Line 1 checks the
   facility name and town (designed).
3. The script never asks for or says the patient's name; it uses "a patient", age band and the service only.
4. Outcome wording: "Said yes on the phone, 14:05" (and the role if given, "reception"), never "confirmed" or
   "verified". The slip says "we phoned at 14:05, they said yes".
5. "No answer" in an emergency keeps the option in the plan with "not reached"; it moves down only if a backup is
   reached and says yes. For scheduled services it moves to the backup as designed.
6. Outcomes are stored beside the score, never inside it, for all three concepts (Setu's rule). They feed a later
   retrain only after review. Stored fields: facility id, service, outcome, date, role (field, coordinator,
   planner); no caller number, no patient data, location no finer than district. An "Undo" button stays for 1
   minute after a tap.
7. Add "We went and they could not help" as an outcome on the slip screen; it flags the facility for the
   service in the review queue.

## 11. 108 / 102 transport

Facts used (NHM press release and Wikipedia pages in feasibility/actions/sources; state-level roles not checked):
108 is free emergency response for critical care, trauma and accidents, and the dispatcher picks the nearest
ambulance and centre; 102 is free transport for pregnant women and infants under JSSK to the nearest CHC or
government hospital; 112 integrates emergency numbers.

Harms: the crew will not go to our first choice, especially a private one, and the worker has no plan B. 102 does
not answer in some places.

Verdict: keep, and keep it first for every emergency-profile service.

Guardrails:
1. 108 first for trauma, burns, emergency C-section and any danger tick; 102 beside it for pregnancy and infants
   with "If 102 does not answer, call 108".
2. The crew fallback line is always shown: "Ask the crew to take you to A. If they cannot, the best government
   place in reach is B (19 km)." B must be named even when B is Unverified.
3. "If 108 does not connect, call 112" as a small line, sourced as secondary (Wikipedia citing 112.gov.in).
4. The model card says: 102/108 roles vary by state; checked only against national pages.

## 12. Ride-hailing links (Uber, Ola, Rapido, Namma Yatri)

Should a ride ever be suggested over 102/108? No, not for an emergency-profile service. A private car has no
trained crew, no oxygen and no stretcher, costs money that JSSK transport would not, and may not be available in a
rural district (unknown). For dialysis, MRI and planned cardiac care, a ride is the normal way to travel and is
fine.

Verdict: keep, only as a fallback for emergencies and as a normal option for scheduled and elective services.

Guardrails:
1. Emergency profile: no ride links on the first view. They appear only after the user taps "Ambulance not coming
   or refused". Replace the concept's "if no ambulance in 20 minutes" timer with this button (the 20 minutes is an
   unverified assumption and a timer is a time limit).
2. When shown in an emergency, the ride block starts with "A car has no medical crew. Keep trying 108." and offers
   cars only (no bike or auto) for labour and newborns (designed).
3. Scheduled and elective: directions and ride-later links are first-class (designed).
4. No booking APIs, no auto-open (Chrome requires a user gesture; Uber request scope privileged; Ola invite-only).
5. Where the destination cannot be prefilled (Rapido, Namma Yatri, possibly Ola), show the address with a copy
   button so the driver does not take the patient to a same-named place.

## 13. Referral slip (SMS, WhatsApp, show big, print)

Harms: the slip reveals a health condition ("dialysis", "C-section") to whoever reads the phone it lands on; the
recipient number may be wrong or shared. Family members read "0.81" as a hospital quality grade. A stale slip is
reused weeks later.

Verdict: keep, with guardrails.

Guardrails:
1. The app never asks for or stores the recipient's number: sms: and wa.me open the phone's own app.
2. One line above the send buttons: "Ask the patient before sending to family."
3. Slip content: service, facility, address, phone, whom to ask for, the backup, 108/102, "carry the PHC note",
   date and time, and the data date. No patient name (paper blank), no patient location, no confidence decimals;
   the reason is the plain sentence ("listing says 6 machines; we phoned 14:05, they said yes").
4. The slip says "Made 21 Nov 10:45. Call before going if this is more than a day old."

## 14. Languages, read aloud and translation

Harms: a wrong word in a medical instruction ("do not wait" read as "wait"), a number misread by speechSynthesis
("24" read in English or as a different unit), a danger word missing in Hindi or Marathi so the 108 bar never shows.
Direct LLM translation broke names, quotes or numbers in 4/4 runs (measured).

Verdict: keep fixed templates; kill runtime LLM translation for anything a user acts on.

Guardrails:
1. No language ships until a native speaker has reviewed the templates, the call script, the danger checklist and
   the danger-word list. Today that is none: Hindi and Marathi are unreviewed. Referral Desk's Marathi at launch
   must wait for this review; until then Marathi users get Hindi or English with "Marathi coming".
2. Runtime LLM translation (Setu's plan for other languages) is not used for the call script, slip, danger text or
   transport instructions. If used at all, it is for the WHY card's descriptive text only, with placeholder
   protection, the verbatim check, and a visible "machine translated" label; failure falls back to English.
3. Quotes from facility text stay in their original language (designed).
4. Read aloud: test each template with the Android Hindi voice on a real phone before the demo; numbers are written
   as "24 kilometre" in the Hindi string so the voice cannot pick a unit. Not tested.
5. Medical terms use the words workers use plus the English term in brackets ("operation se delivery (C-section)").

## 15. Offline pack and offline answer

Harms: the pack date is not the data date. Facility text was scraped at some earlier time, so "saved 21 Nov" hides
that the evidence may be a year old. Offline distances are straight-line from a possibly stale fix. The pack today
holds placeholder rankings (prototype fallback model).

Verdict: keep.

Guardrails:
1. Two dates on every offline answer: "Facility data from web pages collected <snapshot date>. Saved to this phone
   <date>." Amber after 30 days on the phone, red after 90 (Referral Desk rule, apply to all three).
2. Offline answers always show "Call before you go" as the first action and 108/102 at the top.
3. Straight-line distances say "straight line, road is longer" with the x1.26 range.
4. The pack carries the bands and evidence quotes, not just names, so an offline answer is never a bare nearest
   list (the accessibility test showed a dental clinic ranked second without service filtering).
5. Do not ship packs built from the fallback model as anything but labelled demo data.

## 16. Offline single-file HTML copy

Harms: a file passed between workers on WhatsApp can be edited (a phone number swapped) and forwarded; there is no
way to update or recall it; it outlives its data. Redistribution of the dataset outside the App may conflict with the
Marketplace terms (https://cms.databricks.com/sites/default/files/2023-01/marketplace-consumer-terms_0.pdf, not
read).

Verdict: keep as a download to the worker's own phone; kill "pass between workers as a WhatsApp document" from the
pitch until the terms are checked.

Guardrails:
1. The file shows its build date and data date in a fixed header and goes red after 90 days, while keeping 108/102
   and the call buttons working.
2. Each copy shows a short content hash; the App's settings page shows the current hash, so a coordinator can
   compare. This detects accidental drift, not a determined editor (the editor can change the check too); say so.
3. Read the Marketplace terms before demoing any redistribution.

## 17. SMS demo bot

Harms: once a number is shown on a slide, real people may text it with patient details. A personal SIM hits daily
SMS caps and TRAI rules on commercial messaging (feasibility offline).

Verdict: keep as a demo only.

Guardrails: the number is never shown on screen or slides; the bot replies only to the team's allowlisted numbers;
messages are not stored beyond the demo; it is described as roadmap (DLT registration needed), not as a service.

## 18. Referral record (coordinator)

Harms: a free-text "case ref" invites names; a server table of referrals is a health dataset.

Verdict: keep, minimal fields.

Guardrails:
1. Case ref accepts only up to 12 letters, digits and hyphens; anything with a space is refused with "Use your own
   code, not a name".
2. Stored: case ref, service, district, options shown with scores, chosen option, reason ticks, call outcomes with
   times, data and model hashes. No patient name, phone, photo, exact location or free-text notes about the patient.
   The "whom to ask for" field is staff, and is kept.
3. Readable only by the coordinator's workspace identity and their supervisor; delete after the hackathon unless
   the team decides otherwise in writing.
4. India's DPDP Rules 2025 were notified on 13 November 2025 with phased commencement (search summaries, e.g.
   https://www.dsci.in/files/content/knowledge-centre/2025/Insight-Brief-on-DPDP-Rules.pdf, not read). Whether
   this app is a data fiduciary for the note scan or the record is not assessed; keeping no patient-identifying
   data is the design answer.

## 19. Planner gap view, wall chart and ten-call list

Harms: "care gap" is confounded with missing web presence (government PHCs and CHCs are thin in scraped data: 469
public records of 10,088). A planner could argue for or against capacity on that basis. A printed wall chart looks
official and is never updated. Area access assumes independent failures. Prototype numbers (care gap 0.78 in
Kaimur) are from the fallback model.

Verdict: keep, with caveats on every surface.

Guardrails:
1. "Care gap" is renamed "no public evidence of care" in the headline, with the data-gap and care-gap formulas one
   tap away. The caveat line "Low web presence looks like a gap. Verify before deciding." is on the screen, the
   CSV header, the brief and the wall chart.
2. The wall chart prints its data date, "Check by phone before sending", 108/102, and "Replace by <date + 90 days>".
3. Every area number links to the facility cards that produce it, so a gap claim can be challenged line by line.
4. The ten-call list is a list of facilities to verify, not to rate; call outcomes follow the rules in 10.6.
5. No prototype number appears in a pitch claim; regenerate from the fitted model (Setu already says this).

## 20. Demo GPS switch and demo phone numbers

Harms: a build with the demo switch on sends real users' plans for Sitamarhi; a demo tel: link dials a real
hospital during judging.

Verdict: keep for the demo.

Guardrails:
1. The switch exists only when a server environment flag is set; with the flag off, the code path returns 404.
2. When on, every screen and every slip shows "DEMO LOCATION" and the slip text starts with "DEMO".
3. In demo mode every facility tel: link dials the team phone and is labelled "DEMO: dials our team phone".
4. Release checklist item: flag off, verified by loading the deployed URL in a fresh browser.

## 21. Ideas that stay killed

- Condition photo for triage (section 2).
- Auto-booking a ride or ambulance, auto-dialling: no public 108/102 dispatch API; Chrome needs a user gesture; a
  wrong automatic action costs hours.
- An LLM chatbot or LLM-written explanations: LLMs gave confidence 1.0 to a contaminated record (an eye hospital's
  borrowed dialysis sentence). Trust decisions stay deterministic.
- Gemma-3-12b anywhere: obeyed an injected instruction 2/2, sent a heart attack to trauma, hit 429s.
- Accounts, patient records, stored note photos.

## Cross-cutting failure mode: the model is wrong

The likely way someone is hurt: the app sends a patient to a facility that does not actually provide the service,
or cannot that day. Expected rate: about 15% of Likely and much more of Unverified (spec 5.5), before same-day
capacity, which the model does not know.

Defences, in order:
1. Call before going (designed), with 108 first in emergencies so the call never delays transport.
2. A named backup with a phone number on the screen and the slip, from a different leakage group (spec 6.5).
3. The 108 crew fallback to the best public place.
4. "Said yes on the phone" recorded with time and shown on the slip.
5. "We went and they could not help" outcome, reviewed and fed to the next model version.
6. Wording that never claims more than the data: "listing says", "public evidence", "not verified".
7. Model card states the band precision target, n, and that the system does not know beds, staff or slots.

## Release gates (before the demo)

- [ ] Note scan: consent screen, crop, EXIF strip, accurate retention wording, no image or reply in logs.
- [ ] Danger words run before the LLM; chest-pain cases never reach an elective profile (add to the 36-case test).
- [ ] 108 button on every emergency-profile screen, including GPS search and offline.
- [ ] Ride links behind "Ambulance not coming" for emergency profiles.
- [ ] Coordinates rounded to 0.01 degree in POST bodies; uvicorn access log off.
- [ ] "Is the patient here?" has no default in Compare and Area; place echoed on every plan and slip.
- [ ] Quick depth: band word plus words, no "chance at least one works", no decimals on the slip.
- [ ] Two dates (data snapshot, saved) on every offline answer and the offline HTML.
- [ ] Demo flag off in the shipped build; demo tel: links dial the team phone.
- [ ] Hindi strings reviewed by a native speaker, or the demo says "Hindi draft, not reviewed".

## Not tested or not checked

- Everything on a real Android phone: camera crop and EXIF strip, mic, read-aloud voices, tel:/sms:/intent: links,
  GPS accuracy and offline time to first fix.
- Databricks Free Edition retention and training terms for pay-per-token endpoints (paid-account wording only).
- Whether Databricks App logs are readable by other workspace users.
- CDSCO and DPDP applicability: secondary sources only, no legal opinion.
- Marketplace terms on redistributing derived packs.
- State-level 102/108/112 roles.
- The danger checklist against an official ASHA module.
