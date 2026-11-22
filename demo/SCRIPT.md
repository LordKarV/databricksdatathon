# Demo narration: the pitch (about 3 minutes 30 seconds, 520 words)

For the human narrator. One emergency runs through the whole video: a C-section near Lucknow, the brief's own
example question (phone GPS 26.86, 80.94; clicks in `demo/RECORDING.md`). Every number is read from a committed
file, named in brackets, or off the screen, in [square brackets]; re-check them before recording and do not round
them up. Simulation results are always called a simulation. Show the deployed Databricks App, not local copies.

**0:00 the emergency.** "A woman in labour near Lucknow needs an emergency C-section. The health worker with her has
minutes, not hours. Which hospital nearby can actually operate tonight, and why should they believe the answer?
That is the challenge's own question, and India's facility data to answer it is 10,000 records scraped from the
web. So before we trusted any of it, we audited it."

**0:20 we audited the data first.** Show the data stories page. "A quarter of the records, 2,489 of 9,959, carry a
sentence about a different hospital, because sources were merged. 1,171 map points sat more than 25 km from the
real hospital; we moved them. A chatbot cannot see any of this: asked whether a Nagpur hospital offers dialysis, Llama
3.3 70B on our workspace said yes, confidence 1, from sentences that belong to hospitals in Mumbai."
[REPORT.md, cleaning/geo_identity/summary.json, audit/capabilities/aiq2_rerun_20261122.json]

**0:45 the answer.** Open the app at the GPS point and tap "C-section, emergency". "The nearest listing, City
Hospital, is [300 metres] away. Bharosa does not send her there, and it says why: its listing never
mentions an operating theatre, and its map point may be wrong. Instead: BNK Hospital, [4] minutes, rated Likely.
The receipt is on the card, from its own listing: 'Performs Lower Segment Caesarean Section'. And it ranks first
because it also shows evidence of blood transfusion, which the next hospital does not."

**1:15 a model you can read.** Tap "Why this place?". "Every score is a sum of named witnesses: the hospital's own
sentence, whether that sentence is really about this hospital, its website, and official lists. We brought in
outside data for those lists: national accreditation (NABH), medical colleges (NMC), blood banks (e-RaktKosh),
LaQshya maternity certification, OpenStreetMap, and NFHS-5 district health data, each cited per hospital. BNK
scores [82] out of 100, and every row is a quote you can open." [derived/v2/README.md, README.md]

**1:45 tested like a trial.** Point at the dots at the top of the Why page. "We fixed our rules before fitting,
froze the model, published its hash, and only then opened a sealed test set nobody had tuned on. 25 of the 28
places it rated Likely were confirmed, 89 percent, and it ranks with AUROC 0.82. We also trained three transformer
readers, two on a Databricks GPU; our transparent model matched or beat all three, so every answer stays
explainable." [model/gold/v3/test_eval/results.json, model/reader/out/metrics_full.json]

**2:15 the map and the clock.** Back to the answer, scroll to the map. "Hollow pins are places whose map point we
doubt, so nobody drives to a wrong address. In a simulation of thousands of referrals, minutes mattered most, so
in an emergency the app sends the patient to the nearest place that can plausibly treat, and checks the route
against the window: first care within 60 minutes, met, in about [4]." [submission/sim_results.csv]

**2:40 built for the field.** Tap Call, come back, tap "No answer". "If BNK does not pick up, the next number,
Fatima Hospital, is already on screen. The same answer in Hindi, read aloud, as a referral slip the family gets on
WhatsApp, and offline from a saved pack. Each call's outcome feeds back into the same evidence ledger."
Show the Hindi switch and the slip.

**3:05 on Databricks.** "All of it runs on Databricks Free Edition: the notebook rebuilds every table from the
Marketplace data, Unity Catalog holds them, AI Functions and a GPU tested the alternatives, Genie answers district
planners in plain English, and the app runs as a Databricks App."

**3:20 close.** "Not the nearest. Not the unreachable best. The place most likely to treat this patient in time,
with the evidence on the card."
