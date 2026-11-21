# CallFirst: referral plans that know what they do not know

## One line

Type a service and a place. CallFirst returns a referral plan rather than a ranked list: Plan A, an independent Plan B, the facility's own sentences behind every claim, and the one phone call that would settle the remaining doubt. Every call a health worker logs is stored as new, dated evidence, so the next person's answer is better. The same engine, run over every PIN in India, gives planners a map of where the evidence is thin and a ranked list of the calls that would change the most answers.

## Why this concept

Most entries will do retrieval over the records, sort by distance and let an LLM write the explanation. On this data that produces confident wrong answers:

- The capability probe gave llama-3-3-70b the two known contaminated dialysis records (Aravind Eye Hospital "Hyderabad", Wockhardt Nagpur). It answered offers_dialysis=yes with confidence 1 and a verbatim quote for both. An LLM cannot be the trust layer.
- "Nearest facility that claims the service" is often not the nearest facility with good evidence. Over 19,711 PIN points (numbers script in the appendix), the nearest claim of any grade is more than 20 km closer than the nearest strong, well-located facility for 9,147 PINs for trauma, 5,887 for cardiac surgery, 5,371 for C-section and 2,874 for dialysis.
- The remaining doubt can't be cleaned away. 7,514 unattributed service sentences sit in 1,390 records that also carry text quarantined as another facility's, and 1,161 of the 4,151 strong grades are in those records. 538 records have a location the signals cannot settle.

So the product treats uncertainty as something the user can act on. It says what is known, cites it, says what is not known, and says the cheapest way to find out: a phone call with specific questions. That turns the dataset's weakness into the workflow.

## Primary users

1. A community health worker or ASHA coordinator with one patient and a basic phone or tablet browser. They need one clear answer, a fallback and a number to call, in plain words.
2. An NGO coordinator arranging a referral, such as a high-risk delivery in Maharashtra. They need to compare two or three options and see why each was chosen.
3. A district planner. They need to know where verified care is missing, which facilities are claimed but unverified, and which calls to make this week. They also need scenario answers, such as a highway trauma hotspot.

## Format

Primary format: a Databricks App written in Streamlit (Python), reading precomputed Delta tables in the `workspace` catalog through the SQL warehouse.

Secondary formats:
- a serverless Databricks notebook pipeline (Spark SQL plus pandas) that builds the tables from the shared catalog;
- one offline ai_query batch, which may only lower grades;
- an optional Genie space over the planner tables, for free-form planner questions;
- a notebook fallback that renders the same plan cards with displayHTML if the App is down.

Justification on three axes:

- Fit for the user. The health worker needs a fixed two-input form, large cards and a phone number, not a chat box that invites open questions the data cannot answer. The planner needs a map, a table and a scenario pin. An App supports both modes from one engine. A dashboard has no input-driven plan logic or write-back. Genie returns tables and SQL, not a referral plan with citations.
- Capability, with honest status.
  - Verified by the probe: the SQL warehouse; ai_query with strict JSON output; 8 chat and 3 embedding endpoints; listing Genie spaces.
  - Documented but not yet tested by us: the App runtime with Streamlit 1.38, plotly, databricks-sql-connector and databricks-sdk pre-installed (2 vCPU, 6 GB); App access to UC tables through a warehouse resource; App writes for the call ledger.
  - Known unavailable: public or anonymous App access. Judges must be workspace users granted CAN_USE.
  - The first build task on Saturday is a hello-world App that reads one table and appends one row, before anything else depends on it.
- Flexibility. The engine is a plain Python module (`plan.py`) with no UI imports. The App, the notebook fallback and the tests all call it. The ledger is a Delta table, so a later Genie space, an AI/BI dashboard or a Lakebase store can sit on the same data without a rewrite. New services need only a lexicon row and a prerequisite list in the grader.

## User workflow, health worker mode

1. Open the App. Two inputs: "What does the patient need?" (8 tiles with plain names and synonyms: dialysis / kidney wash, caesarean delivery, newborn intensive care, trauma / accident, heart surgery, MRI scan, burns, ICU) and "Where is the patient?" (PIN, city, district or "use my location" coordinates). A service outside the 8 gets "not covered yet", never a guess.
2. Location is resolved with the existing resolver (`cleaning/geo_identity/s3_resolve.py`, 54 of 54 regression tests). A two-state name such as Aurangabad or Bilaspur asks which state. A typo such as "Hydrabad" asks the user to confirm. "Lucknw" gets a "did you mean". The resolved point and its accuracy ("PIN centre, accurate to about 2 km") are shown before any result.
3. The plan appears: at most three cards, labelled Call first, Plan A and Plan B, with a map strip. Each card shows straight-line km, three uncertainty lights, the cited sentences and the phone numbers.
4. "Why not the closer one?" sits under the cards. It names the nearest facility that claims the service but was not chosen, with the rule and the sentence that excluded it.
5. The user taps "Call script". It lists the numbers (directory and call-centre numbers already removed) and two to four questions generated from the gaps in the evidence. Example: "Your listing says 'Specialised dialysis unit' but names no nephrologist. Is a nephrologist available today?" Another: "Are you on MG Road, Kakinada (PIN 533001)?"
6. After the call, the user taps one outcome: confirmed, does not offer it, wrong number, moved, or no answer. They can add an optional note, such as "4 machines, open till 8 pm". This writes one ledger row with the role, the time and the question answered.
7. The plan refreshes. A confirmed call adds a "Field-checked by phone, 21 Nov 2026, NGO coordinator" line as a separate layer, never mixed with the web text. A denial removes the facility for that service and shows why.

## User workflow, planner mode

1. Choose a state or district and a service. The map shows each PIN point coloured by distance to the nearest strong, well-located facility, with an outline where an unverified claim is much closer.
2. Need context strip: NFHS-5 figures for the district, chosen per service and labelled "district context, not facility evidence". Dialysis shows high blood sugar and hypertension prevalence. Caesarean delivery shows the C-section rate and institutional births. Burns and trauma show none. A two-axis chart plots distance to verified care against the need indicator. There is no combined weighted score, so nothing hides a weight choice.
3. Call list: the unverified facilities whose confirmation would most shorten plans, ranked by PIN-km saved. Each row has the call script and a "log outcome" button, using the same ledger as health worker mode.
4. Scenario pin: drop a pin or type coordinates, for example a highway accident hotspot. You get trauma plans with an explicit trauma-wording requirement, a separate "stabilise only" list of 24/7 emergency claims with no trauma evidence, and the fallback cost: how much farther the patient travels if Plan A turns out to be wrong.
5. Export the district call list as CSV for a field team.

## How a plan is built (the HOW)

There is no weighted score. Each step is a rule a judge can read:

1. Candidate set. Facility x service grades from `cleaning/claims/out/grades.parquet` (v2 grader, 10,799 pairs). Only strong and moderate can be recommended. Weak and tag_only appear only as "unconfirmed leads" in the call list. counter_evidence and attributed_elsewhere are never shown as options; they feed "why not".
2. Location gate. Uses the point, radius and confidence from `facility_location.parquet` (high 7,762, medium 517, low 1,142, disputed 538 of 9,959). Disputed records are never Plan A. They can appear as Call first, and then the card shows both candidate points. Records with trust_level exclude_review (12) are dropped.
3. Evidence tier, from best to worst:
   - field-checked confirmed (from the ledger, less than 90 days old);
   - strong;
   - moderate with no risk flag;
   - moderate with a risk flag.
4. The plan is the Pareto frontier of travel against evidence tier. A facility appears only if no other facility is both closer and better evidenced. Distance is the worst case: straight-line km plus the location radius. Within one tier, two facilities less than 10 km apart in distance are ordered by richer evidence: a quantity, more distinct specific sentences, prerequisites met. This rule is the whole trade-off. CallFirst never sends a patient 140 km past an unverified local option without saying so, and it never presents the local option as fact.
5. Labels. The best-evidenced card on the frontier is Plan A. A closer, weaker card is "Call first". Plan B is the next card that is independent of Plan A: it is not in the same duplicate or soft-link group (`facility_groups.parquet`), shares no display phone, and is not on a copied geocode. A merged record or an aggregator phone therefore cannot take down both plans at once.
6. Fallback cost. The card shows the extra distance to Plan B if Plan A fails ("if they say no, the next option is 2 km farther" or "92 km farther").

Call value for planners. For each PIN and service, take the nearest strong, well-located facility (distance d_s) and the nearest unverified candidate (distance d_c). If d_c is less than d_s, confirming the candidate saves d_s - d_c km for that PIN. A candidate's call value is the sum over the PINs where it is the nearest candidate and the saving is at least 50 km. This is PIN-km, not people. There is no population layer, and the screen says so.

What we traded off:
- Recall against precision. Moderate is recommendable only behind a Call first label, because 4 of the 8 moderate pairs that had a web verdict were contradicted.
- Straight-line km against travel time. We have no road network, so the screen says "straight-line".
- One clear answer against honesty about merged records. The answer stays short; the doubt moves into the lights and the call script.

## How WHY and HOW appear on screen for one recommendation

A real case from the cleaned tables: dialysis for PIN 533001 (Kakinada, East Godavari).

Call first card (0.4 km): Apollo Hospitals - Kakinada
- Exists here: green. "Listing coordinates agree with postcode 533001 (0.9 km from its centre)." No trust concerns. Two direct numbers.
- Offers dialysis: amber, grade moderate, rule G_mod. Cited sentences:
  - procedure d74c3a09:proc:34: "Haemodialysis and peritoneal dialysis are offered"
  - equipment d74c3a09:equi:36: "Specialised dialysis unit"
  - What is missing, in plain words: no nephrologist or nephrology department is mentioned anywhere in the record, so the claim is uncorroborated.
- Right for you: green on distance. Plan A is 142 km away.
- Call script: "Is a nephrologist on duty? How many dialysis machines are working? Do you take walk-in patients today?"

Plan A card (142.8 km): Queen's NRI Hospital, Vizianagaram (Visakhapatnam district)
- Exists here: green. "Listing coordinates agree with postcode 530013 (0.6 km from its centre)."
- Offers dialysis: green, grade strong, rule G_strong. Cited sentences:
  - 0b49b291:proc:2: "Dialysis procedures are conducted (over 1000 per month)"
  - 0b49b291:proc:10: "Performs hemodialysis procedures (over 1000 per month)"
  - Prerequisite, nephrology, 0b49b291:capa:8: "Centers of Excellence in Cardiology, Nephrology, Oncology, and Neurosciences"
- Chosen over Sai Spoorthy Hospital (141.6 km, also strong) by the tie rule. Sai Spoorthy's evidence is the one-line "Kidney dialysis" plus "Nephrology department", while Queen's NRI states a volume. The card says this in one line.

Why not the others:
- Medicover Hospital and Anu Hospitals (about 140 km) are both moderate with a location risk. Their cited location notes read: "Listing coordinates are 503 km from postcode 524002 ... coordinates are shared with a listing in another town." Medicover also carries "The listed official phone also appears on listings in 3 or more cities (likely a directory line)."
- Bhimavaram Hospitals (91.9 km) is moderate, with one sentence: "Specializes in Nephrology & Dialysis". It is closer than Plan A but dominated by Apollo Kakinada, which is closer still at the same tier, so it is not shown.

The HOW drawer is always one tap away on every card. It holds the six rules above in plain words, the grade rule that fired (G_mod or G_strong) with its definition, and the web spot-check result for that grade. Every sentence shows its claim_id and field. Tapping it opens the full record text with the sentence highlighted. Source URLs are not shown as citations, because only about 28% of them are about the facility. They sit behind a "where this record was scraped from (often not about this facility)" disclosure.

## How uncertainty is shown

- Three separate lights per card, never one blended score:
  - Exists here: location confidence and radius, duplicate group, direct contact.
  - Offers this: grade, risk flags, corroboration.
  - Right for you: distance band and fallback cost.
- Each light is a word plus a colour (green, amber, grey). Hovering or tapping shows the cited reason. Grey means "we could not check", which differs from amber, "we found a problem".
- Calibration footnote per grade, from the 36-pair web spot check. Strong: confirmed 9 of 9 pairs with a web verdict. Moderate: confirmed 4 of 8. Weak: 0 of 1. The footnote says the check was small and partly in-sample, so these are not probabilities.
- Named badges in plain words:
  - "This record mixes text from other facilities" (record carries quarantined text)
  - "Only a specialty label supports this" (corr_tags_only; 1,035 strong grades)
  - "Record cut off at 50 items, so a missing service may still exist"
  - "Location disputed: two candidate towns" (both points on the map)
  - "Number may be a helpline or directory"
- No percentages, no star ratings, no LLM confidence. Distances to PIN-centre points are rounded and shown with "about".

## Data handling: clean, flag or leave

Fixed in the pipeline: the existing cleaning outputs, ported to Spark SQL.
- 11 duplicate rows dropped, giving 9,959 records.
- PIN centroids repaired: busy PINs more than 25 km off went from 78 to 43 of 1,051.
- 127 of 134 missing PINs given a point.
- Directory and call-centre phones removed from display, with helplines labelled.
- 360 email placeholders dropped.
- Synonym false positives fixed: Mrityunjay as MRI, PICU as ICU, ambulance-only as trauma, and others; 101 pairs dropped.
- Duplicate claims and field echo collapsed.
- 136 service sentences that name another facility quarantined.
- Non-offer sentences turned into counter-evidence (hand check 14 of 15 correct).
- 75 duplicate groups shown as one card.

Flagged and shown, not hidden: disputed and low-confidence locations, merged-record signals, scope caps (eye or dental names with tertiary claims), tag-only corroboration, outpatient type claiming inpatient care, truncated arrays, veterinary records (12, for review), claims-everything records (79).

Model step, offline only: ai_query on the 242 ambiguous or other-facility service sentences. It returns JSON with claim_id, attribution and quote. A row survives only if the claim_id exists and the quote is an exact substring of the claim text. The model may only lower a grade, never raise one, and its rows are labelled "model-assessed". It is enabled only if it beats the rules on the 40 labelled sentences. The larger 7,514-sentence pass is cut for quota.

Left unfixed, and said so on screen: anonymous copied text that names no facility, merges where every field follows the other facility, and claims lost to the 50-item cap. The phone call and the ledger are the product's answer to these.

## What is unique compared with typical entries

1. The answer is a plan with an independent fallback and a fallback cost, not a ranked list. Plan B is chosen so that it cannot fail for the same reason as Plan A: a merged record, a shared aggregator phone or a copied geocode.
2. Every recommendation ends in an action that reduces uncertainty: a call script generated from the gaps in that record's evidence.
3. A field-verification ledger. Logged calls become dated evidence, kept apart from the web text, and they are the only thing that can raise a grade. The dataset improves through use, and the demo shows it happen.
4. Value of information for planners: "the calls that would change the most answers", measured in PIN-km of shorter plans. For dialysis, confirming Apollo Hospitals - Kakinada would shorten the plan for 107 PINs by 10,988 PIN-km, about 103 km each. Nationally, 634 PINs in 84 districts have a dialysis call worth at least 50 km, spread over only 20 facilities. For burns it is 4,111 PINs in 240 districts over 33 facilities.
5. A Pareto rule instead of a weighted score, so the trade-off can be explained in one sentence and has no hidden weights.
6. "Why not the closer one" names the rejected option and cites the sentence that rejected it.
7. Need context from NFHS-5 next to evidence gaps, never fused into one opaque number.

## Free Edition fit

- Compute: the pipeline is a serverless notebook run once. It writes about 8 small tables to `workspace.callfirst`: facility_card, service_grade, claim_evidence, pin_gazetteer, place_gazetteer, pin_service_reach, call_value, call_ledger.
- App: the App loads the read-only tables into memory at start-up, a few MB and about 6 warehouse queries. It ranks in numpy in process, so a search costs no warehouse query. Only ledger writes touch the warehouse.
- Model use: no LLM at request time. One offline ai_query batch of about 242 rows.
- Limits: 1 of 3 Apps; Vector Search, Lakebase and GPU are not needed.

## Risks and mitigations

- App behaviour is documentation-only for us. Mitigation: hello-world App with one table read and one ledger append, Saturday hour one. If the write fails, the ledger falls back to App memory for the demo, labelled "not saved".
- Apps stop 24 hours after start or deploy. Mitigation: redeploy within the 24 hours before judging and note the time. Keep a recorded walkthrough and the notebook fallback, which renders the same cards with displayHTML.
- Judges cannot open the App anonymously. Mitigation: ask organisers for judge emails to add as workspace users with CAN_USE. Otherwise present live plus the video.
- Daily fair-usage quota. Mitigation: precompute everything, keep no request-time LLM, run the warehouse only for start-up loads and ledger writes, and do no rebuilds on demo day.
- Grader v2 was tuned after reading the web verdicts, and the spot check is 36 pairs. Mitigation: the calibration footnote says so. A fresh 20-pair check on Saturday reports v2 numbers out of sample.
- Demo ledger rows are role-played. They must be marked as demo entries and reset after the demo, never shown as real verification. Never fabricate a field check.
- Straight-line distance and the lack of population weighting can mislead in hills and coastal districts. Mitigation: labelled on screen; road time is out of scope.
- Display names are sometimes whole address strings (the Queen's NRI record). Mitigation: a cosmetic name cleaner for display only, with the raw name in the receipt.

## Weekend build plan for 4 people (works with 3 by merging roles C and D)

Saturday morning:
- A: hello-world App (read plus append) and grants.
- B: port the claims explode and grade SQL to a serverless notebook and diff its row counts against local (10,799 pairs).
- C: Streamlit layout for the two-input form and cards on local parquet.
- D: fresh 20-pair web spot check and the demo cases.

Saturday afternoon:
- A: port the geo and identity outputs and write the `workspace.callfirst` tables.
- B: `plan.py` (gate, tiers, Pareto, Plan B independence, why-not, call script templates), with assert tests on the organiser examples (Aravind, Wockhardt Nagpur) and the Kakinada case.
- C: receipts, lights, the HOW drawer and claim highlighting.
- D: pin_service_reach and call_value tables, and the NFHS context strip.

Sunday morning:
- A: ledger write path and refresh.
- B: offline ai_query batch with the substring check, only if it beats the rules.
- C: planner mode (map, call list, scenario pin).
- D: notebook fallback and CSV export.

Sunday afternoon:
- Everyone: freeze data, redeploy, record the video, rehearse the 3-minute script twice, add judges as users, write the README with the rules and numbers.

## What we would cut, in order

1. Genie space for planners.
2. ai_query attribution pass (rules alone are the baseline).
3. Hindi call scripts (static templates, no LLM).
4. CSV export.
5. Scenario pin, keeping it as a coordinates input in the normal search.
6. NFHS scatter, keeping the one-line context strip.

Never cut: citations, the three lights, Plan B independence, the why-not line, the call script and the ledger.

Not building at all:
- Vector Search or RAG, because the service list is fixed and free-text retrieval adds wrong matches.
- Request-time LLM explanations.
- Road routing.
- Lakebase.
- Agent Bricks.

## 3-minute demo script

- 0:00 to 0:20. "Ten thousand facilities, but a record is a claim, not a fact. An LLM given Aravind Eye Hospital's record said 'yes, dialysis, confidence 1'. That text belongs to a Delhi government hospital. We built the opposite of a confident answer."
- 0:20 to 1:20. Health worker mode, dialysis, PIN 533001.
  - Call first: Apollo Kakinada at 0.4 km. Read its two cited sentences, then the amber light: no nephrologist anywhere in the record.
  - Plan A: Queen's NRI at 143 km, stating over 1,000 dialysis sessions a month, with the nephrology sentence. Open the HOW drawer and read the Pareto rule in one breath.
  - Why not Medicover: tap it and show its cited 503 km location conflict and its directory phone.
- 1:20 to 1:50. Tap the call script and role-play the call, labelled as a demo entry. Log "confirmed, nephrologist on duty". The card turns green and gains a field-checked layer with today's date. Plan B is now 2 km of fallback, not 142.
- 1:50 to 2:30. Planner mode, Andhra Pradesh, dialysis.
  - The reach map shows the East Godavari gap shrinking after that call.
  - Call list: "these 20 calls would shorten dialysis plans for 634 PINs in 84 districts". Switch to burns: 4,111 PINs in 240 districts, 33 calls.
  - NFHS context strip, labelled as context, not evidence.
- 2:30 to 2:50. Scenario pin on a highway, trauma. Strong trauma options with explicit trauma wording. A separate "stabilise only" list of 24/7 emergency claims. The fallback cost if Plan A is wrong.
- 2:50 to 3:00. "Every claim cited, every doubt named, and every answer ends in the call that removes the doubt. The data gets better each time someone uses it."

## Appendix: numbers and the code that produced them

Grounding script (run locally, 0 warehouse queries, about 3 s). It was written to the scratchpad, not this directory, because this step may write only this file, so the full code is copied below. It uses the cleaned outputs in `cleaning/claims/out/grades.parquet` and `cleaning/geo_identity/*.parquet`. Demand points are the 19,711 PIN gazetteer points with coordinates, unweighted.

"Strong located" means grade strong, loc_conf high or medium, and trust_level not exclude_review. A "candidate" is moderate, weak or tag_only with the same location gate. A "call" is a PIN whose nearest candidate is at least 50 km closer than its nearest strong located facility.

| service | facilities with a claim | strong located | median km to nearest strong | median km to nearest claim | PINs: nearest claim 20+ km closer than strong | PINs with a 50 km call | districts | call targets |
|---|---|---|---|---|---|---|---|---|
| dialysis | 1,041 | 665 | 38.5 | 30.3 | 2,874 | 634 | 84 | 20 |
| csection | 443 | 181 | 69.9 | 48.4 | 5,371 | 2,485 | 173 | 44 |
| nicu | 742 | 477 | 43.4 | 35.3 | 3,069 | 393 | 50 | 13 |
| trauma | 3,568 | 446 | 45.5 | 18.4 | 9,147 | 4,118 | 392 | 291 |
| cardiac_surgery | 966 | 327 | 54.8 | 35.9 | 5,887 | 1,920 | 173 | 56 |
| mri | 947 | 512 | 46.0 | 35.3 | 3,955 | 1,110 | 125 | 29 |
| burns | 262 | 96 | 91.0 | 60.0 | 7,058 | 4,111 | 240 | 33 |
| icu | 2,781 | 1,195 | 31.0 | 21.1 | 3,625 | 723 | 99 | 44 |

More figures from the same run:
- PINs farther than 100 km from strong located care: dialysis 2,232, C-section 6,606, burns 8,848 (each of 19,711).
- Top dialysis calls: Apollo Hospitals - Kakinada (107 PINs, 10,988 PIN-km); Bhimavaram Hospitals (97, 7,640); Bukkawar Heart & Critical Care Hospital, Chandrapur (80, 7,525).
- The top MRI call target is "Disha Path Lab" (moderate), a pathology lab claiming MRI. The call list also exposes doubtful claims, and one call settles them either way.
- PIN-gazetteer districts that join NFHS-5 on an exact case-folded name and state: 538 of 770. The facility-level crosswalk in facility_location.parquet joins 9,934 of 9,959 facilities. The planner view must use a district crosswalk, not the exact join.
- NFHS-5 districts with a C-section rate below 10%: 152 of 706.

Other figures are quoted from the verified audit and cleaning results: grade counts, spot-check results, location confidence counts, trust levels, 7,514 / 1,390 / 1,161 contamination figures, and the LLM probe.

```python
"""Grounding numbers for design/concept_system.md (care deserts, call value, fallback).
Reads only the local cleaned outputs. Demand points = one point per PIN from the
cleaned PIN gazetteer (unweighted: no population data, so PIN counts are a proxy)."""
import json
import duckdb
import numpy as np

ROOT = "/Users/karthikvattem/projects/datathon"
G = f"{ROOT}/cleaning/claims/out/grades.parquet"
L = f"{ROOT}/cleaning/geo_identity/facility_location.parquet"
T = f"{ROOT}/cleaning/geo_identity/record_trust.parquet"
P = f"{ROOT}/cleaning/geo_identity/pin_gazetteer.parquet"
N = f"{ROOT}/data/raw/nfhs_5_district_health_indicators.parquet"
SERVICES = ["dialysis", "csection", "nicu", "trauma", "cardiac_surgery", "mri", "burns", "icu"]
CLAIM = ("strong", "moderate", "weak", "tag_only")
c = duckdb.connect()

fac = c.sql(f"""
  select g.unique_id, g.service, g.grade, g.name, l.loc_lat lat, l.loc_lon lon, l.loc_conf,
         l.district, l.state_final, t.trust_level
  from '{G}' g join '{L}' l using (unique_id) join '{T}' t using (unique_id)
  where l.loc_lat is not null
""").df()
pins = c.sql(f"select pin, state, district, lat, lon from '{P}' where lat is not null").df()
plat, plon = np.radians(pins.lat.values), np.radians(pins.lon.values)


def nearest(sub):
    """Distance (km) and index into sub of the nearest row, for every PIN."""
    if len(sub) == 0:
        return np.full(len(pins), np.inf), np.full(len(pins), -1)
    flat, flon = np.radians(sub.lat.values), np.radians(sub.lon.values)
    best_d, best_i = np.empty(len(pins)), np.empty(len(pins), dtype=int)
    for s in range(0, len(pins), 1500):
        a, b = plat[s:s + 1500, None], plon[s:s + 1500, None]
        h = np.sin((flat - a) / 2) ** 2 + np.cos(a) * np.cos(flat) * np.sin((flon - b) / 2) ** 2
        d = 2 * 6371 * np.arcsin(np.sqrt(h))
        best_i[s:s + 1500] = d.argmin(1)
        best_d[s:s + 1500] = d.min(1)
    return best_d, best_i


out = {"n_pins": int(len(pins)), "services": {}}
for svc in SERVICES:
    f = fac[fac.service == svc]
    located = f.loc_conf.isin(["high", "medium"]) & (f.trust_level != "exclude_review")
    strong = f[(f.grade == "strong") & located].reset_index(drop=True)
    cand = f[f.grade.isin(["moderate", "weak", "tag_only"]) & located].reset_index(drop=True)
    any_claim = f[f.grade.isin(CLAIM)].reset_index(drop=True)
    d_s, _ = nearest(strong)
    d_a, _ = nearest(any_claim)
    d_c, i_c = nearest(cand)
    saving = np.where(d_c < d_s, d_s - d_c, 0.0)
    callable_pins = saving >= 50
    # Call value: PIN-km saved if the nearest unconfirmed candidate is confirmed by phone.
    cv = {}
    for idx, sv in zip(i_c[callable_pins], saving[callable_pins]):
        cv[idx] = cv.get(idx, 0.0) + sv
    top = sorted(cv.items(), key=lambda kv: -kv[1])[:3]
    out["services"][svc] = {
        "claimed_facilities": int(f[f.grade.isin(CLAIM)].unique_id.nunique()),
        "strong_located": int(strong.unique_id.nunique()),
        "strong_but_location_low_or_disputed": int(f[(f.grade == "strong") & f.loc_conf.isin(["low", "disputed"])].unique_id.nunique()),
        "pins_nearest_strong_gt_100km": int((d_s > 100).sum()),
        "median_km_nearest_strong": round(float(np.median(d_s)), 1),
        "median_km_nearest_any_claim": round(float(np.median(d_a)), 1),
        "pins_where_naive_nearest_is_not_strong_and_20km_closer": int((d_a + 20 < d_s).sum()),
        "pins_where_one_call_saves_50km": int(callable_pins.sum()),
        "districts_with_a_50km_call": int(pins[callable_pins][["state", "district"]].drop_duplicates().shape[0]),
        "distinct_call_targets": int(len(cv)),
        "top_calls": [{"name": cand.name[i], "district": cand.district[i], "grade": cand.grade[i],
                       "pins": int(((i_c == i) & callable_pins).sum()), "pin_km": round(v)} for i, v in top],
    }

nf = c.sql(f"select lower(trim(district_name)) d, lower(trim(state_ut)) s, births_delivered_by_csection_5y_pct cs, institutional_birth_5y_pct ib from '{N}'").df()
pd_ = pins.assign(d=pins.district.str.lower().str.strip(), s=pins.state.str.lower().str.strip())
dists = pd_[["d", "s"]].drop_duplicates()
out["pin_districts"] = int(len(dists))
out["pin_districts_exact_nfhs"] = int(dists.merge(nf, on=["d", "s"]).shape[0])
out["nfhs_districts_csection_lt_10pct"] = int((nf.cs < 10).sum())
out["nfhs_rows"] = int(len(nf))
print(json.dumps(out, indent=1))
```

Note: the "any claim" distance uses all claimed facilities, including low or disputed locations. That is what a naive nearest-claim system would see, so it is the right comparison for the naive baseline.
