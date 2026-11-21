# Parchi: a referral slip you can check

Concept for the frontline lens. Written 2026-11-21. Design only; nothing was deployed.

Number sources. Counts marked [audit] or [cleaning] come from the verified audit and cleaning
outputs under /Users/karthikvattem/projects/datathon/audit/ and /cleaning/. Counts marked
[feasibility] come from probes under /app_design/feasibility/. Counts marked [this step] come from
the queries in the appendix, run on the local snapshot (cleaning/claims/out/grades.parquet,
cleaning/geo_identity/*.parquet). Nothing here was run on Databricks.

## 1. The concept in one paragraph

An ASHA in rural Madhubani does not need a ranked list or a chat. She needs to know whom to phone
first, what to ask on that call, what to do if they say no, and something to hand the family. Parchi
(Hindi for a referral slip) takes a service and a place and returns a slip, not an answer: up to
three role-labelled options ("clearest evidence", "closest, call first", "backup"), each with the
facility's own sentence quoted verbatim, three plain-language checks (does it offer this, is it
where we think, can you reach them), the questions to ask on the phone, and a share button that
sends the slip to the family on WhatsApp in Hindi, Marathi or English. After the call she taps one
of four outcomes, and that tap becomes field evidence the next user and the district planner can
see, labelled separately from what websites claim. The LLM is used only to understand the user's
words, never to judge a facility.

## 2. Why this shape (what the data forces)

- A confident ranking is not possible on this data, so the product must route the uncertainty to
  the one step that resolves it: the phone call the worker makes anyway.
  - 1,407 of 9,682 facilities sit more than 50 km from their own PIN [audit GEO-01]; 538 records
    stay "disputed" after cleaning [cleaning geo].
  - About 1,400 of 9,959 records truly name another facility in their claims [audit merge F1];
    7,514 copied service sentences in 1,390 records name no facility at all and no rule can see
    them [cleaning claims].
  - On the web-checked sample, strong grades were confirmed 9 of 9, but moderate grades were
    contradicted 4 of 8 [cleaning claims, v2, in-sample]. Moderate cannot be shown as a
    recommendation without its caveats.
- An LLM cannot be the trust layer: llama-3-3-70b rated both known contaminated records (Aravind
  Eye Hospital "Hyderabad", Wockhardt Nagpur) as offering dialysis with confidence 1 and a verbatim
  quote [capability probe].
- "Strong" itself has two kinds that a user must see apart [this step]:
  - 227 of 695 strong dialysis grades rest only on evidence sentences of 3 words or fewer
    ("Dialysis facility"); 298 of 695 are corroborated only by a specialty label.
  - For emergency C-section, 90 of 193 strong grades rest only on sentences of 3 words or fewer.
- Coverage is thin exactly where the frontline users are: 260 of 9,959 records are in Bihar and 146
  of those 260 are in Patna district [this step]. Absence from our data is not absence on the
  ground, and the product has to say so.

## 3. Users and their minute-by-minute workflow

Primary: ASHA or ANM in a village, NGO field coordinator. Low-end Android, patchy 2G/3G, Hindi or
Marathi, little time, will phone the facility, has to hand the family something.
Secondary: district planner or NGO programme lead (desktop, English, wants gaps and patterns).

ASHA workflow (target: under 2 minutes to a sent slip):

1. Open the bookmarked link (no install, no login beyond the workspace sign-in; see risks). Page
   is plain HTML, about 2 KB.
2. Choose the need. Eight large picture buttons with Hindi/Marathi/English labels: dialysis,
   delivery emergency (C-section), newborn care (NICU), ICU, accident/trauma, burns, heart
   surgery, MRI. Or type, or use the phone keyboard's own voice typing, in any language:
   "maa ko hafte mein teen baar dialysis". The app shows back "You wrote: 'dialysis' -> Dialysis.
   Correct?" with the decisive phrase quoted. One tap to confirm.
   - If the words contain danger signs (bleeding, unconscious, breathing, labour complication), a
     red bar appears first: "Call 108 now. Then use this slip." with a tap-to-call button.
3. Say where. One box that accepts a PIN, a village or post office name, a district, a city, or
   "use my location". Ambiguity is a question, never a silent guess: "Aurangabad: Bihar or
   Maharashtra?", "Did you mean Lucknow?", "Hydrabad is a village in UP. Did you mean Hyderabad?"
   (resolver statuses ok, ask_state, confirm, did_you_mean, not_found; 54 of 54 regression tests
   pass [cleaning geo]).
4. Read the slip. Up to three cards, each with a role label. Each card leads with the facility
   name, town, distance band, a tap-to-call button and the three checks.
5. Call. Below the call button: "Ask them" with 2 to 4 questions generated from what the evidence
   does not cover (for dialysis: "Is the dialysis machine working today?", "Do you take a new
   patient without a nephrologist's letter?", "What does one session cost, and do you accept the
   Ayushman card?").
6. Tap the outcome: "Yes, they can take the patient", "No / not available", "Wrong number",
   "No answer". "No" moves the backup card up.
7. Share. One button builds the family's slip: facility name, address, phone, what to carry,
   "call before you leave", 102 for free transport for pregnant women and sick infants, 108 for
   emergencies. Sent as WhatsApp text or the phone's share sheet. Text only, so it works on 2G.

Planner workflow:

1. Same app, "Planning" tab (desktop layout).
2. Pick a service and a state. A district table shows: nearest facility with clear evidence
   (straight-line km), number of options within reach, how many of them have only brief or
   label-only evidence, field calls logged and their outcomes, and NFHS-5 district context (for
   example C-section rate, institutional birth rate), labelled "district context, not evidence
   about any facility".
3. Enter coordinates (a highway accident hotspot) to get the same slip with a trauma filter that
   requires explicit trauma wording (3,586 of 9,019 trauma-like sentences are explicit; the rest
   are generic 24/7 emergency [audit claims-10]).
4. Download the table as CSV.

## 4. Format choice

Primary: one Databricks App, FastAPI serving server-rendered HTML (no client framework), reading
precomputed Delta tables into memory at start-up. Secondary: a Databricks serverless notebook (or
job) that builds those tables from the shared dataset; optional Genie space over the same tables
for planners.

Fit for the user (measured locally with throttling, not on Databricks) [feasibility accessibility]:

| Framework page | First-visit transfer | Main action visible on emulated 2G | axe violations |
|---|---|---|---|
| FastAPI HTML | 1,855 bytes | 0.44 s | 0 |
| Gradio | 1,152,266 bytes | 40.3 s | 3 |
| Streamlit | 1,342,615 bytes | 44.4 s | 3 |
| Dash | 1,523,147 bytes | 49.9 s | 3 |

A health worker on 2G waits 0.4 s for the FastAPI page and about 44 s for Streamlit. That settles
the framework for the frontline page. Genie and chat are wrong for this user: they need typing,
cannot guarantee the card layout, citations or uncertainty wording, and put an LLM in the trust
seat.

Capability (only what was verified):
- Verified: SQL warehouse; ai_query with llama-3-3-70b including strict JSON output; 8 chat and 3
  embedding endpoints; Genie list-spaces [capability probe].
- Verified offline: llama-3-3-70b mapped symptom and need text to the right service 30 of 30 on
  the main set (English, Hindi, Hinglish, Marathi) and 6 of 6 on the hard set, decisive phrase
  verbatim 36 of 36, median latency 876 ms [feasibility voice_language].
- Docs only, NOT verified: deploying an App (apps list is empty), FastAPI being preinstalled, the
  App reading UC tables through the warehouse, App calling a serving endpoint, Lakebase.
  The first build task is a hello-world App that reads one table and calls one endpoint.
- Not available: public or anonymous App access; GPU; classic clusters.

Flexibility:
- FastAPI gives one backend with two front ends (phone page, planner page) and a JSON API, so an
  IVR, WhatsApp bot or the team's referral-planner model (model/design/proposal_decision.md) can
  plug in behind the same card contract without a UI rewrite.
- All trust logic is in precomputed tables, so a better grader is a table rebuild, not an app
  change.

## 5. HOW: from 10,000 records to three cards

Offline, in the notebook (runs once, re-runnable):
1. Drop 11 byte-identical duplicate rows: 9,970 to 9,959 records [cleaning].
2. Location: one ranking point per facility with source, radius, confidence and a plain note.
   Coordinates used when they agree with the PIN (7,762 records, radius 1 km); otherwise the map
   link, then the city, then the stated state picks the point; 538 stay disputed with a second
   point kept [cleaning geo].
3. Contacts: directory and call-centre numbers removed from display (0 shown), chain helplines
   labelled, 247 records flagged no_direct_contact [cleaning geo].
4. Claims: every capability, procedure, equipment and description item is one citeable sentence
   with a claim_id (469,498 sentences). Each facility x service pair gets a grade, the rule that
   produced it, up to 3 cited sentences, counter-evidence, sentences attributed elsewhere, the
   prerequisites met (each with its sentence or tag) and named risk flags [cleaning claims].
5. Card table: for each pair, the evidence tier, the three check sentences, the ask-list and the
   "why not" sentence, all as text, so the App does no reasoning of its own.

Evidence tier (what the user sees as words, in this order):

| Tier | Plain words on screen | Rule |
|---|---|---|
| Clear | "Their own page states this clearly, with supporting detail" | strong grade, at least one cited sentence longer than 3 words, no risk flag |
| Brief | "Mentioned briefly; little detail" | strong grade whose cited sentences are all 3 words or fewer |
| Unconfirmed | "Mentioned, but not backed up or something conflicts" | moderate, or weak |
| Label only | "Only listed as a specialty; no sentence says they do it" | tag_only; shown only when nothing better is within reach |
| Not recommended | shown under "Why not these", never as a card | counter_evidence (record says it refers out or does not have it), attributed_elsewhere (the text is about another hospital), trust level exclude_review (12 records, e.g. veterinary) |

A disputed location drops the card one tier and shows both candidate towns. Corroboration by a
specialty label alone (298 of 695 strong dialysis grades) does not change the tier but is always
printed as its own line ("Also listed under: nephrology (specialty label)").

Online, per query (in memory, no warehouse query, no LLM):
1. Filter to the service; drop "not recommended" pairs into the "Why not these" list.
2. Distance from the user's point to each ranking point; road distance estimated as straight-line
   x 1.26 (median circuity over 50 OSRM routes from 5 rural Bihar origins, leave-origin-out error
   16.5% [feasibility geo_routing]). Times are shown as a range and labelled "about", because the
   router assumes free-flow roads.
3. Reach limit by service (assumed, editable, shown in the HOW panel): emergency C-section, trauma,
   burns, NICU 150 km road; dialysis, ICU 200 km; MRI, cardiac surgery 500 km.
4. Pick the cards:
   - Card A "Clearest evidence within reach": best tier, then nearest.
   - Card B "Closest, call first": the nearest option of any tier, if it is at least 25 km closer
     than A. For time-critical services (C-section, trauma, burns, NICU) B is shown first when it
     saves more than 30 minutes, because a call settles evidence faster than a drive does.
   - Card C "Backup if they say no": next best by the same rule, preferring a different town.
5. Write the trade-off sentence from the two numbers and the two quotes (template, not LLM).

The trade-off we make, stated on screen: we never let a closer facility with weaker evidence
silently beat a farther one with clear evidence, and we never hide the closer one either. Both are
shown with their roles, and the phone call decides.

## 6. WHY and HOW on screen: one real card

Query: dialysis, PIN 847211 (Madhubani, Bihar). Values below are from the snapshot [this step].

```
-------------------------------------------------------------
CLOSEST, CALL FIRST
Dr. Global Healthcare & Diabetes Centre (Dr. Naween Kumar)
Darbhanga  |  about 27 km straight line, 30-40 km by road
[ Call ]  (2 numbers; neither is a directory or call-centre number)

Does it offer dialysis?    MENTIONED BRIEFLY
  Their record says: "Dialysis facility"        (equipment, 7ada90ef:equi:1)
  Also listed under: nephrology (specialty label)
  Nothing else in the record describes the unit.
Is it where we think?      CHECKED
  Map point agrees with PIN 846004 (0.4 km from its centre).
Can you reach them?        LIKELY
  Numbers are not directory or call-centre lines.
  Website is the facility's own.

Ask them:
  1. Is the dialysis machine working, and how many sessions a week can you take?
  2. Is a nephrologist on site, or do you need a referral letter?
  3. Cost per session; Ayushman card accepted?
[ They can take her ] [ Not available ] [ Wrong number ] [ No answer ]
-------------------------------------------------------------
CLEAREST EVIDENCE WITHIN REACH
Phular Superspeciality Hospital, Muzaffarpur
about 73 km straight line, 85-100 km by road
Does it offer dialysis?    STATED CLEARLY
  "Dialysis treatment is provided"   (procedure, 2dccd2d1:proc:11)
  "Dialysis program is offered"      (capability, 2dccd2d1:capa:17)
...
WHY THIS ORDER
  Dr. Global is 47 km closer but its only line is "Dialysis facility".
  Phular states dialysis in two separate fields. For a 3-times-a-week
  treatment the closer one is worth one phone call first.
-------------------------------------------------------------
HOW WE CHOSE  (tap to open)
  9,959 records -> 1,050 say something about dialysis
  -> 1,041 after removing 9 whose text refers out or is about another hospital
  -> 39 in Bihar; 8 nearest shown below with their tier and distance
  Order: evidence tier, then distance; closer weaker option shown as
  "call first" when 25+ km closer. Reach limit for dialysis: 200 km.
  What we cannot see: whether they are open today, have a free slot,
  or whether this text was copied from another hospital without naming it.
  Our data has 260 facilities in Bihar, 146 of them in Patna.
  Government centres may be missing: ask your PHC medical officer too.
-------------------------------------------------------------
```

Every claim on the card is a quote with its field and claim_id; tapping a quote shows the full
record text around it and the source URLs, with the warning that source URLs are search hits and
only about 28% are about this facility [audit PROV-01]. The tier words, checks and trade-off
sentence are generated by templates from table columns, so the same inputs always produce the
same text.

The Hindi version translates the template text (fixed strings written and checked by a native
speaker) and keeps the quotes in their original English, marked "facility's own words". An
optional machine gloss of the quote, labelled "translation", is a stretch item.

## 7. How uncertainty is shown

- Three separate checks, never one blended score: offer (evidence tier), location (checked,
  approximate with radius, or disputed with both towns), contact (own number, helpline only, no
  direct number). A user can see that a facility is real and well placed but thinly evidenced.
- Words and quotes, no percentages. The labelled sample is 36 pairs and its intervals span 30 to
  60 points [cleaning claims], so a "87% confident" badge would be invented precision.
- Record-level warnings in plain words, from trust_reasons: "This record also contains text about
  other hospitals (N sentences)", "Claims 6 or more of the 8 acute services; records like this
  often merge several facilities", "Location is approximate".
- "What we cannot know" line on every slip: open today, bed or slot free, copied text that names
  no other hospital.
- Honest empty state: "No facility within 150 km has a clear statement of emergency C-section in
  our data." followed by the nearest unconfirmed options, 102/108 buttons and the coverage note.
- Field calls are shown as their own evidence line, with date and count, never merged into the
  website tier: "Field check: 2 calls in the last 30 days, both 'can take patient'."
- A public "How good is this?" page shows the evaluation as it is: strong 9 of 9 confirmed on the
  web sample, moderate 4 of 8 contradicted, in-sample, n=36.

## 8. Data problems: clean, flag, or say we cannot

| Problem | Decision | What the user sees |
|---|---|---|
| 11 duplicate rows; 75 duplicate groups under different ids | fix: dedupe; one card per group | one card; copies' addresses kept in details |
| Bad PIN centroids (78 busy PINs off by 25+ km), PINs missing from directory | fix: corrected gazetteer | correct distances; prefix-median PINs labelled approximate |
| Coordinates 50+ km from PIN (1,367 raw conflicts) | fix where city or map link decides (1,165 re-pointed); flag the rest | "Location approximate" or "disputed: X or Y" with both towns |
| Directory and call-centre phones; email placeholders | fix: not displayed | only numbers unique to the facility on the call button; "no direct number" otherwise |
| Synonym false positives (Mrityunjay as MRI, EmOC as C-section, PICU as ICU) | fix: 101 pairs removed | nothing |
| Duplicate claims and field echo counted as corroboration | fix: distinct claims only | each quote shown once |
| Sentences naming another facility (9,506 quarantined) | flag at sentence level | quote hidden from evidence, shown under "text about other hospitals" |
| Single-specialty name with tertiary claims (eye hospital doing dialysis) | flag: scope cap to weak | "Unconfirmed: this is an eye hospital's record" |
| Outpatient type claiming inpatient service | flag | "Listed as a clinic; ask if they admit patients" |
| Arrays cut at 50 items (4,498 pairs flagged) | cannot recover | "This record was cut short; a missing service may still exist" |
| Anonymous copied text (7,514 sentences, 1,390 records) | cannot detect | record warning plus "call first"; field-call ledger is the only fix |
| Thin rural coverage | cannot fix in data | coverage note on every slip with the state count |

## 9. What is unique compared with typical entries

1. The output is a handover object (the slip) for a family and a phone call, not a chat reply or a
   ranked list.
2. Role-labelled options ("closest, call first" vs "clearest evidence") with a written trade-off,
   instead of a hidden weighted score.
3. "Why not these": the facilities we passed over and the reason, including "this text is about
   another hospital", with the quote. Judges can audit omissions, not only inclusions.
4. Questions to ask on the call are generated from the prerequisites the evidence does not cover.
5. Every call is a fact-check: outcomes become a field-evidence ledger that improves the next
   answer and gives planners a map of verified vs claimed capability.
6. 2G-first engineering backed by a measurement: about 2 KB and 0.4 s against about 1.3 MB and 44 s.
7. The LLM only reads the user (any language, typed or keyboard-voice) and must quote the phrase it
   used; it never grades a facility. We can show judges why, with the Aravind result.
8. Uncertainty split into offer, location and contact, each in words with its source.

## 10. Free Edition risks and mitigations

- Apps are docs-only for us so far. Mitigation: deploy a hello-world App on day 1, hour 1.
- Apps cannot be public; judges must be workspace users with CAN_USE. Mitigation: ask organizers
  early how judges get access; add them; keep a recorded demo video and a static HTML export of
  6 precomputed scenarios as a fallback.
- Apps auto-stop 24 h after start. Mitigation: restart (databricks apps start) on the morning of
  judging and before the demo; note the time on the README.
- Daily fair-usage quota. Mitigation: the App loads tables once at start-up and answers from
  memory (no warehouse query per search); the only per-request model call is the optional free
  text parse; the pipeline runs once, not on every deploy.
- Call-outcome writes: Lakebase and App-to-warehouse writes are docs-only. Mitigation: try
  Lakebase first; fallback append to a Delta table via the warehouse in small batches; last resort
  an in-memory ledger clearly labelled "demo only, resets on restart".
- Serverless notebook package install (rapidfuzz) not verified. Mitigation: fuzzy matching can fall
  back to Python's difflib.
- Model availability can change and gemma-3-12b returned HTTP 429 under light load
  [feasibility vision]. Mitigation: llama-3-3-70b primary; on any failure the picture buttons
  still work.

Other risks:
- Grader v2 was tuned on the same small sample it is scored on; moderate is often wrong. The tier
  words and "call first" are designed for that.
- Hindi and Marathi strings need a native speaker's check before the demo.
- Travel-time fit comes from 50 routes in Bihar only.
- Not a triage tool: the danger-sign bar sends to 108, and the app never says "safe to wait".

## 11. Weekend build plan (4 people; 3 if P4 is merged into P2 and P3)

Friday evening (all, 2 h): hello-world App deployed reading one table and calling llama-3-3-70b;
judge-access question sent; card contract (table columns and JSON) agreed.

| Person | Saturday | Sunday morning |
|---|---|---|
| P1 data | Port cleaning to a serverless notebook (claims explode is already Spark-style SQL); write Delta tables: facility_location, record_trust, grades, claims, pin and place gazetteers | card table (tier, check sentences, ask-list, why-not); planner district table with NFHS context; re-run check against local counts |
| P2 backend | FastAPI: resolver, filter, distance, card picking, trade-off and HOW templates; golden tests for 6 scenarios plus the 54 resolver tests | call-outcome write path (Lakebase, then fallback); free-text parse endpoint with verbatim-phrase check |
| P3 front end and language | HTML and CSS for phone and planner pages; picture buttons; tap-to-call, share text, 102/108 buttons; Hindi and Marathi strings | accessibility run with the existing measure.py; 2G check; native-speaker review of strings |
| P4 evaluation and demo | "How good is this?" page from eval.json; pick and pre-check demo scenarios by hand | record demo video; static scenario export; README with run steps and restart time |

Sunday afternoon: freeze at 15:00, rehearse the script twice, restart the App.

## 12. What we cut

- Photo of a referral slip read by a vision model (works in probes, but adds a fragile step and a
  429-prone endpoint).
- Server-side speech recognition (Whisper small on Hindi had character error about 0.2 and worse
  on Bengali [feasibility voice_language]); the phone keyboard's own voice typing covers it.
- Live road routing (OSRM is external; outbound internet from Databricks is restricted). The
  circuity factor replaces it.
- Vector Search and RAG: retrieval is not the problem; attribution is.
- Embedded map tiles: a "Open in Maps" link instead saves hundreds of KB.
- Probability-based referral planner from the model team: keep the tier rules for the weekend and
  plug the planner in behind the same card contract later.
- AI/BI dashboard and Genie space: stretch only, after the App is stable.
- Machine translation of quotes.

## 13. Three-minute demo script

0:00-0:25 The trap. Show the Aravind Eye Hospital record: city Hyderabad, PIN in Delhi, map point
near Puducherry, dialysis sentence about a Delhi government hospital. Show that an LLM said "offers
dialysis, confidence 1". "A confident wrong answer costs a patient hours. So Parchi never lets a
model decide who is trustworthy."

0:25-1:30 The ASHA. Phone-sized browser, throttled to 2G; page appears in under a second. Tap
Hindi. Type "maa ko hafte mein teen baar dialysis"; confirm "Dialysis". Enter PIN 847211
(Madhubani). The slip: "Closest, call first": Dr. Global Healthcare, Darbhanga, about 27 km,
evidence "Dialysis facility", marked "mentioned briefly". "Clearest evidence": Phular
Superspeciality, Muzaffarpur, about 73 km, two quoted sentences. Read the "why this order"
sentence aloud. Show "Ask them". Tap "Not available": the backup moves up. Tap Share: the family's
WhatsApp slip in Hindi with 102 and 108.

1:30-2:10 The coordinator, high-risk delivery near Gadchiroli (20.18, 80.0). Nearest: Government
Medical College Chandrapur, 78 km, "unconfirmed": one quote is a research protocol about cord
milking during caesarean, its operating-theatre evidence is a dental sentence, and its location is
approximate. Parchi shows it as "closest, call first" because for an emergency a call is faster
than a drive, and names the backup: Ketkar Maternity, Nagpur, 144 km, "LSCS deliveries: 400-500
per year". Open "Why not these" to show a record whose C-section text refers out.

2:10-2:40 The planner. Planning tab, Bihar, dialysis: districts where the nearest clear option is
over 100 km, how many options are brief-only, field calls logged in the demo, NFHS context
labelled as context. "Every call a health worker makes turns a website claim into a field check."

2:40-3:00 How we decided and how good it is. Open "How we chose": the funnel with counts, the tier
rules, the reach limit. Open "How good is this?": strong 9 of 9 confirmed, moderate 4 of 8
contradicted on a 36-pair web sample, and that is exactly why the slip says "call first".

## Appendix: queries behind the [this step] numbers

Run with /Users/karthikvattem/projects/datathon/.venv/bin/python and duckdb from
/Users/karthikvattem/projects/datathon.

```sql
-- Bihar coverage: 260 records; Patna 146
select count(*) from 'cleaning/geo_identity/facility_location.parquet' where state_final ilike 'bihar';
select district, count(*) from 'cleaning/geo_identity/facility_location.parquet'
 where state_final ilike 'bihar' group by 1 order by 2 desc;

-- Grade counts per service (dialysis: strong 695, moderate 279, weak 64, tag_only 3,
-- attributed_elsewhere 6, counter_evidence 3; Bihar dialysis: strong 31, moderate 6, weak 2)
select service, grade, count(*) from 'cleaning/claims/out/grades.parquet' group by all;

-- Strong grades corroborated only by specialty labels (dialysis 298 of 695)
select service, count(*), count(*) filter (where corr_tags_only)
from 'cleaning/claims/out/grades.parquet' where grade = 'strong' group by 1;

-- Strong grades whose cited sentences are all 3 words or fewer (dialysis 227 of 695, csection 90 of 193)
with e as (
  select service, unique_id, max(len(string_split(trim(x.text), ' '))) mx
  from 'cleaning/claims/out/grades.parquet',
       unnest(from_json(cite_evidence, '[{"text":"VARCHAR"}]')) t(x)
  where grade = 'strong' group by all)
select service, count(*), count(*) filter (where mx <= 3) from e group by 1;

-- Demo nearest options: service, lat, lon (Madhubani PIN 847211 point 26.3447, 86.0711;
-- Gadchiroli test point 20.18, 80.0). Haversine km to loc_lat/loc_lon, joined to record_trust.
select g.name, l.district, g.grade, l.loc_conf, g.risks, g.corr_tags_only, t.trust_level,
  round(2*6371*asin(sqrt(pow(sin(radians(l.loc_lat-26.3447)/2),2)
   + cos(radians(26.3447))*cos(radians(l.loc_lat))*pow(sin(radians(l.loc_lon-86.0711)/2),2))),1) km,
  g.cite_evidence
from 'cleaning/claims/out/grades.parquet' g
join 'cleaning/geo_identity/facility_location.parquet' l using (unique_id)
join 'cleaning/geo_identity/record_trust.parquet' t using (unique_id)
where g.service = 'dialysis' and l.loc_lat is not null order by km limit 8;
```

The funnel figures in the section 6 mock-up (1,050 dialysis pairs; 1,041 after removing 9) are the
sums of the dialysis grade counts above; the "39 in Bihar" is 31 + 6 + 2.
