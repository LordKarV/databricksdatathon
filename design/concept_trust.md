# Receipts: concept (trust and evidence lens)

One line: a referral finder for health workers and planners that never states a claim it cannot show, and turns every gap in the evidence into a phone question.

Status: design proposal. Numbers come from the verified audit and cleaning outputs (cleaning/claims/out, cleaning/geo_identity) and from the prototype script in the appendix, which I ran on the local snapshot (0 warehouse queries). Anything marked "unverified" was not tested in the workspace.

## The idea in one paragraph

Most entries will sort records by distance and let an LLM write the reason. On this data that produces confident wrong answers: the capability probe asked llama-3-3-70b about Aravind Eye Hospital "Hyderabad" and Wockhardt Nagpur, and it said both offer dialysis with confidence 1, quoting text that belongs to a Delhi government hospital and a Mumbai hospital. Receipts takes the opposite stance. No model decides anything at query time. Each recommendation carries three separate receipts that are never blended into one hidden score: (1) does this place exist where the record says, (2) does it offer this service, and (3) why is it the right choice for this patient's urgency and location. Each receipt quotes the record sentence it rests on, by claim id. Where a receipt is missing or weak, the tool does not hide it; it writes the question the health worker should ask on the phone. The call result can then be logged and becomes a new, dated receipt.

## Who uses it

- Primary: a community health worker (ASHA, ANM) or NGO coordinator on a phone or shared laptop, under time pressure, possibly low literacy in English. Needs: two or three named options, how far, how sure, what to ask before sending the patient.
- Secondary: a district planner. Needs: where coverage is thin, which records are disputed, and the method, so they can defend a decision.
- Judges sit in the planner seat: they want to see WHY and HOW in under a minute.

## Format

Primary: a Databricks App in Streamlit (pre-installed at 1.38 per the Apps docs; docs_only, not deployed yet). Data pipeline as a Databricks notebook writing Delta tables in the `workspace` catalog. Secondary: a "Methods and calibration" notebook, and optionally an AI/BI dashboard for planners.

Why, on three axes:

- Fit for the user. A chat box invites free text and returns prose; our users need a fixed, repeatable screen with three cards, a map, and a checklist they can read aloud. An App gives full control over how a quote, a grade and a disputed location are drawn. Genie returns tables and SQL, which suits a planner but not an ASHA, and we cannot control how it phrases uncertainty.
- Capability (only what the probe verified). Verified: SQL warehouse, ai_query with strict JSON output, 8 chat models and 3 embedding models, Genie listing. Docs only, not tested: Apps (3 per workspace, 24 h auto-stop, 2 vCPU and 6 GB), app reading UC tables through the warehouse, app calling serving endpoints. Verified unavailable: public or anonymous app access, GPU. The design needs nothing beyond the warehouse and an App; LLM use is optional, offline and precomputed.
- Flexibility. Python end to end: the cleaning code is already pandas and DuckDB SQL written close to Spark SQL, so the same logic runs in the notebook and the App reuses it. Adding a service is one row in the prerequisite table plus a lexicon entry. A Genie space or dashboard can sit on the same Delta tables later without touching the App.

Rejected: Genie as the front end (no control over citation display); Vector Search or RAG (retrieval is not the problem here, attribution is; and Free Edition allows 1 endpoint); Agent Bricks (legacy status for Knowledge Assistant since 2026-10-12 per the probe, availability per brick not verified); Lakebase (not needed for the volume of call logs; a Delta table is enough).

## User workflow

1. Pick the need. Eight large buttons with icons and Hindi/Marathi labels: dialysis, emergency C-section, NICU, trauma, ICU, MRI, cardiac surgery, burns. Each button carries its time profile (see below), which the user can see but does not have to set.
2. Say where the patient is. One box: PIN, town, district or "use my location". The resolver from cleaning/geo_identity/s3_resolve.py answers ok, "which one?" (Aurangabad Bihar or Maharashtra), "did you mean" (Lucknw), or "confirm" (Hydrabad). It never silently picks a homonym. 54 of 54 regression tests pass (written by the same author, so this is a regression suite, not an accuracy figure).
3. Read the answer. A banner states the time verdict in one sentence, for example "No option with confirmed C-section evidence is within about 1 hour by road." Below it, two or three cards from the trade-off set (next section), and a map with one pin per card (two pins joined by a dashed line when the location is disputed).
4. Open a card. The card shows the three receipts, the "why not the nearer one" line, and the call-ahead checklist.
5. Call. Tap a number (directory and call-centre numbers already removed, chain helplines labelled). Tick answers on the checklist: yes, no, did not answer.
6. Send the patient. Generate a referral slip in Hindi or Marathi: facility, address, phone, what was confirmed on the call and when, the quoted evidence ids, and the time estimate. Share as an image or print.
7. Optional: the call outcome is saved and shows on that facility's card for the next user as "Phone-checked on 22 Nov 2026: dialysis Mon/Wed/Fri, 2 machines".

## How one recommendation looks on screen (WHY and HOW)

Worked example from the prototype run: emergency C-section, patient at PIN 442603 (Gadchiroli, Maharashtra), search radius 250 km road estimate. 8 graded candidates; the trade-off set has 2.

Banner: "No option with strong C-section evidence within 1 hour. The nearest plausible option is about 91 km by road (about 2 to 3 hours). Call before you leave."

Card A: Government Medical College and Hospital Chandrapur. Label: "Nearest plausible".

- Receipt 1, exists here: "Location uncertain." Quote of the location note: "Listing coordinates are 135 km from postcode 440018 (Nagpur); address city is Chandrapur. Chandrapur lies near the coordinates." Ranking point = coordinates, shown with a +-25 km ring. Source fields named: address_city, address_zipOrPostcode, latitude/longitude.
- Receipt 2, offers the service: grade "Claimed, not corroborated" (moderate, rule G_mod). Quote: "Cesarean delivery: the newborn is placed at the edge of the table and UCM is performed by a second team member..." with a note: "This sentence reads like a research protocol, not a service listing." Prerequisites: obstetrics met by claim 4616c935:proc:3; operating theatre and anaesthesia not found in the record. Risk flags in words: "the record's location fields disagree"; "the record may include text about a similarly named facility".
- Receipt 3, why this one: "Closest of the 8 candidates. Its evidence is weaker than card B." Time: about 91 km by road, estimated 2 to 3 hours.
- Calibration line under the grade: "When this tool said Claimed, not corroborated, a web check found the service wrong 4 times out of 8 (small sample). Treat as unconfirmed."
- Call-ahead checklist, generated from the missing prerequisites and flags: "Do you do emergency C-sections at night today?", "Is an anaesthetist on site now?", "Is the hospital at [address], Chandrapur?", "Is there blood available?".

Card B: Mogre Children Hospital, Nagpur. Label: "Best evidence within reach".

- Receipt 1: "Location confirmed: listing coordinates agree with postcode 440024 (0.8 km from its centre)."
- Receipt 2: "Confirmed in the record" (strong, rule G_strong). Quote: "Obstetric services including normal delivery and cesarean section are offered" (claim id shown). Prerequisites: obstetrics met by "Staff includes Dr. Surekha Nandagawali, Obstetrician and Gynecologist", operating theatre met by its own sentence.
- Receipt 3: "131 km further than card A, about 4.5 to 7.5 hours. Strong evidence; outside the golden hour."
- Calibration: "Strong grades were confirmed by a web check 9 times out of 9 (in-sample; 95% interval 0.70 to 1.00)."

HOW panel (one tap, "How we chose these"):

- Decision trace with counts for this query: 10,799 graded facility-service pairs; 448 C-section pairs; 8 within 250 km; 8 graded weak or better; 2 in the trade-off set; 6 "also considered", each with a one-line reason it lost ("further and no stronger", "same distance, location disputed").
- The rule that produced each grade (G_strong, G_mod, G_nonspec, G_scope, G_else, G_no, G_tag, G_amb), in plain words.
- What was weighed: travel time, evidence grade, location confidence, kept as three separate axes. What was traded off: for C-section, time first with a minimum evidence bar; for cardiac surgery, evidence first.
- The context strip, labelled "about the district, not the facility": NFHS-5 Gadchiroli, institutional births 97.3%, births by C-section 17.3%, households with insurance 33.3%.

## The trade-off set

The App does not compute one score. It keeps candidates that no other candidate beats on all three axes at once (travel estimate, evidence grade, location confidence), then labels them: "Nearest plausible", "Best evidence within reach", and, when present, "Balanced". On the five prototype queries the set held 1 to 2 options out of 5 to 38 candidates, which is the right size for a phone screen. A grade of strong that is corroborated only by a specialty tag is shown and ranked as "claimed, label-backed" (the moderate tier); this applies to 1,035 of 4,151 strong grades, including 298 of 695 strong dialysis grades.

Service time profiles (team-set defaults, shown on screen, not clinical guidance):

| Service | Profile | What dominates | Default radius |
|---|---|---|---|
| Trauma | golden hour | time, but only explicit trauma wording counts; generic "24/7 emergency" is shown as "stabilise only" | 100 km |
| Emergency C-section | golden hour | time, with a minimum of moderate plus obstetrics | 150 km |
| NICU | urgent transfer | time, then evidence | 150 km |
| Burns | urgent | time, then evidence | 200 km |
| ICU | urgent | time, then evidence | 150 km |
| Dialysis | recurring, about 3 sessions a week | weekly travel burden (6 one-way trips), then evidence | 150 km |
| MRI | scheduled | evidence and quantity (field strength known for 235 facilities) | 300 km |
| Cardiac surgery | elective | evidence first | state-wide |

Travel time is a range from straight-line km x 1.4 (road proxy) at 30 to 50 km/h, always shown as "estimate". A routing engine is not used.

## How uncertainty is shown

- Grades in words, never percentages: "Confirmed in the record", "Claimed, not corroborated", "Claimed, label-backed", "Mentioned only", "Record says it refers out", "Text is about another facility", "Only a specialty label".
- Each grade carries its published hit rate with its sample size, from a hand-labelled set, and says "small sample" while n < 30 per grade.
- Location in words plus a drawn ring: exact (1 km), approximate (10 to 50 km ring), disputed (two pins with a dashed line and both source fields quoted). 538 records are disputed.
- Any risk flag forces the "Call before you travel" stamp on the card and adds a matching question to the checklist.
- An honest empty state: "No facility in the data has more than a passing mention of burn care within 200 km. Nearest mentions: ..." instead of padding the list.
- Absence is not evidence: for the 1,495 records whose claim arrays were cut at 50 items, the card says "this record was truncated; a missing service may still exist".

## Data problems: clean what has a reason, flag the rest, hide nothing silently

Fixed in the pipeline (each change has a stated reason in the output):

- 11 byte-identical duplicate rows removed (9,970 to 9,959).
- PIN gazetteer repaired (busy PINs more than 25 km off: 78 to 43 of 1,051; 127 of 134 missing PINs given a point).
- Ranking point chosen per record from coordinates, PIN, city and map link: 7,762 high, 517 medium, 1,142 low, 538 disputed.
- Directory and call-centre phones removed from display (292 records), 360 placeholder emails dropped.
- Synonym false positives removed (101 pairs: Mrityunjay as MRI, PICU as ICU, ambulance-only as trauma and others); in-record duplicate claims folded (27,528 of 469,498).
- 75 duplicate groups (152 records) shown as one card each.

Flagged, shown in plain words, never used to silently delete:

- location conflicts and disputed points; merged and near-name records; claims naming another facility (136 service sentences quarantined as "about another facility");
- scope caps (eye or dental names with tertiary claims: 439 pairs); outpatient type claiming inpatient care (771 pairs);
- "claims 6 or more of 8 services" (79 records); tags-only corroboration; truncation;
- 12 veterinary-looking records held back for one human review.

Not solvable from the data, and said so on the methods page: anonymous copied text. 1,161 of the 4,151 strong grades sit in records that also carry quarantined text, and hand reading found 0 of 20 such sentences visibly foreign. The call-ahead step is the product's answer to this.

Optional offline LLM step (specified in the cleaning work, not run): ai_query over the 242 ambiguous or other-facility service sentences, returning JSON with a quote that must be an exact substring of the claim text. It may only lower a grade, its rows are labelled "model-assessed", and it is switched on only if it beats the rules on the labelled sentences.

## Known grader leaks found while prototyping

The prototype surfaced two cases the v2 grader still lets through, which the weekend plan fixes before the demo:

- Getwell Hospital Nagpur, NICU, graded strong on a department list sentence ("Departments offering clinical services in Anaesthesiology; Cancer Surgery; ...").
- GMC Chandrapur, C-section, graded moderate on a research protocol sentence (cord milking study). Both should fall to "Mentioned only" under G_nonspec.

## What is unique compared with typical entries

- Three receipts per card, kept apart: exists here, offers this, right for you. A typical entry gives one score and one paragraph.
- "Why not the nearer one": every card that is not the nearest names the nearer candidates it beat and the one-line reason, with their quotes.
- A per-query decision trace with counts, so the HOW is specific to this answer, not a generic methods slide.
- Published calibration on every grade, with sample sizes, including the bad news (moderate was wrong 4 of 8 times).
- Missing evidence becomes a phone checklist, and the call result becomes a dated receipt for the next user, so the data improves with use.
- A referral slip in Hindi or Marathi that carries the evidence ids and the call result, built from fixed, hand-translated templates (no machine translation of medical text).
- A live side-by-side of "what an LLM says" (the stored probe output for Aravind and Wockhardt) against the receipts for the same records.
- District need context from NFHS-5, always labelled as context about the district, never as facility evidence.

## Free Edition risks

- App auto-stops 24 h after start or deploy: restart with `databricks apps start` on the morning of judging; keep a recorded 3-minute video and a static HTML export of three worked queries as fallback.
- Judges' access: apps cannot be public (docs, not tested). Judges must be workspace users with CAN_USE; ask organisers early how they will view it. Inviting users on Free Edition is unverified.
- Daily quota: no LLM calls at query time; the App loads the Delta tables once at startup and holds them in memory (about 22 MB of Parquet today; claims.parquet is 14.8 MB and can be trimmed to service sentences). Warehouse auto-stops after 10 minutes, so the first load after idle is slow; cache in the App process.
- Writes from the App (call log) need a grant on a table in the `workspace` catalog; unverified. Fallback: the slip is the record, and call logs stay in the session.
- Apps bundle size limits are unverified; do not rely on shipping Parquet inside the App.

## Weekend build plan (3 to 4 people)

| Who | Saturday | Sunday |
|---|---|---|
| Data (1) | Port cleaning/geo_identity and cleaning/claims to one Databricks notebook, write Delta tables; fix the two grader leaks; add tags-only display tier | Freeze tables; run the decision-trace counts for the 3 demo queries; methods notebook |
| App (1) | Streamlit skeleton: need buttons, resolver, banner, cards, map with disputed pins | "Why not nearer", HOW panel, checklist, slip export, call log; deploy |
| Evidence and calibration (1) | Hand-label a fresh, held-out set (about 20 pairs per grade tier, web checked) | Calibration table with Wilson intervals into the App; checklist question templates per prerequisite |
| Story and ops (0.5 to 1) | Hindi and Marathi slip templates with a native-speaker check; judge access request | Demo script rehearsal, video recording, static fallback, README |

## What we would cut, in order

1. Genie space and planner dashboard (nice, not needed for the rule).
2. Saving call outcomes to a table (keep the checklist and slip).
3. The offline ai_query attribution step.
4. "Balanced" label (keep nearest plausible and best evidence).
5. Marathi (keep Hindi).

Never cut: quotes with claim ids, the three receipts, the calibration line, disputed-location display, the call-ahead checklist.

## Three-minute demo script

- 0:00 to 0:25. "This dataset lies confidently." Show the stored probe: an LLM says Aravind Eye Hospital Hyderabad offers dialysis, confidence 1. Open the record: the sentence is about a Delhi government hospital, and the PIN is in Delhi. "So we built a tool that has to show its receipts."
- 0:25 to 1:15. ASHA in Madhubani, Bihar: dialysis, PIN 847211. Two cards. Darbhanga, 37 km: "Claimed, label-backed: the only sentence is 'Dialysis facility' plus a nephrology tag." Patna, 170 km: "Confirmed in the record", quote shown. Dialysis profile: 6 trips a week, so the card says about 220 km a week against 1,020 km. The tool does not pick for her; it says call Darbhanga first, and here are the 4 questions.
- 1:15 to 2:00. Emergency C-section, Gadchiroli. Banner: no strong option within an hour. Card A Chandrapur: location low confidence (its PIN is in Nagpur, 135 km away); evidence is a research sentence, not a service listing; "Call before you travel". Card B Nagpur: strong, about 4.5 to 7.5 hours. "We tell you the trade-off instead of hiding it in a score."
- 2:00 to 2:40. HOW: open the decision trace (448 to 8 to 2), the rule ids, and the calibration table: strong 9 of 9 confirmed in a web check, moderate wrong 4 of 8, which is why moderate always means call first.
- 2:40 to 3:00. Tick two checklist answers, generate the Hindi slip with the quoted evidence ids and the call time. "Every claim on this slip can be traced to a sentence in the record or to a phone call."

## Appendix: prototype script (re-runnable)

Run: `.venv/bin/python demo_frontier.py <service> <pin> <radius_km>` from the project dir. Outputs used above: dialysis 800001 150 (38 candidates, set of 2), dialysis 847211 250 (37, 2), csection 226001 100 (11, 2), csection 442603 250 (8, 2), nicu 440001 100 (5, 2). Strong tags-only counts from grades.parquet: 1,035 of 4,151 overall, 298 of 695 dialysis.

```python
import json, sys
import numpy as np
import pandas as pd

ROOT = "/Users/karthikvattem/projects/datathon/cleaning"
GRADE_RANK = {"strong": 3, "moderate": 2, "weak": 1, "tag_only": 0,
              "attributed_elsewhere": -1, "counter_evidence": -1}
LOC_RANK = {"high": 3, "medium": 2, "low": 1, "disputed": 0}
ROAD_FACTOR = 1.4  # straight-line x 1.4 as a road proxy

def haversine(lat1, lon1, lat2, lon2):
    r = np.radians
    a = np.sin(r(lat2 - lat1) / 2) ** 2 + np.cos(r(lat1)) * np.cos(r(lat2)) * np.sin(r(lon2 - lon1) / 2) ** 2
    return 6371 * 2 * np.arcsin(np.sqrt(a))

def main(service, pin, radius):
    pins = pd.read_parquet(f"{ROOT}/geo_identity/pin_gazetteer.parquet")
    o = pins[pins.pin == pin].iloc[0]
    g = pd.read_parquet(f"{ROOT}/claims/out/grades.parquet")
    g = g[g.service == service]
    loc = pd.read_parquet(f"{ROOT}/geo_identity/facility_location.parquet")
    tr = pd.read_parquet(f"{ROOT}/geo_identity/record_trust.parquet")[["unique_id", "trust_level", "trust_flags"]]
    d = g.merge(loc, on=["unique_id", "name"]).merge(tr, on="unique_id")
    d = d.assign(km=ROAD_FACTOR * haversine(o.lat, o.lon, d.loc_lat, d.loc_lon))
    d = d[d.km <= radius].assign(gr=d.grade.map(GRADE_RANK), lr=d.loc_conf.map(LOC_RANK))
    d = d.assign(gr=np.where((d.grade == "strong") & d.corr_tags_only, 2, d.gr))
    cand = d[d.gr >= 1]
    keep = [i for i, r in cand.iterrows() if not (
        (cand.km <= r.km) & (cand.gr >= r.gr) & (cand.lr >= r.lr)
        & ((cand.km < r.km) | (cand.gr > r.gr) | (cand.lr > r.lr))).any()]
    print(len(d), "candidates;", len(keep), "in trade-off set")
    for _, r in cand.loc[keep].sort_values("km").iterrows():
        ev = json.loads(r.cite_evidence)[:1]
        print(r["name"], r.address_city, round(r.km), r.grade, r.rule, r.loc_conf, r.risks,
              ev[0]["text"][:140] if ev else "-")

if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), float(sys.argv[3]))
```
