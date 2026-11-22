# Demo narration: the pitch (about 3 minutes 30 seconds, 500 words)

For the human narrator. Every number below is read from a committed file, named in brackets after it; re-check
them before recording, and do not round them up. Simulation results are always called a simulation. Show the
deployed Databricks App and the notebook, not local copies. Clicks and screens are in `demo/RECORDING.md`.

**0:00 the problem.** "A health worker in rural Bihar has a patient who cannot wait. Which hospital can actually
treat them, and why should they believe the answer? India's facility data is 10,000 records scraped from the web.
Before we trusted any of it, we audited it."

**0:15 we audited the data first.** Show the data stories page. "A quarter of the records, 2,489 of 9,959, carry a
sentence about a different hospital, because sources were merged. 1,171 map points sat more than 25 km from the
real hospital; we moved them. A plain search, or a chatbot, cannot see any of this." [REPORT.md,
cleaning/geo_identity/summary.json]

**0:35 why a chatbot is not enough.** "We asked Llama 3.3 70B, on our Databricks workspace, whether Wockhardt
Hospital Nagpur offers dialysis. Yes, confidence 1. But that record is stitched together from Mumbai hospitals'
sentences. Referral Saathi catches it: near Thane, it passes Wockhardt over and says why."
[audit/capabilities/aiq2_rerun_20261122.json] Show the Thane answer's Why page: the Passed over line.

**0:55 a model you can read.** Open a Likely card's Why page. "Every score is a sum of named witnesses: the
hospital's own sentence, whether that sentence is really about this hospital, its website, and official lists.
We brought in outside data for those lists: national accreditation (NABH), medical colleges (NMC), blood banks
(e-RaktKosh), LaQshya maternity certification, government trauma centres, OpenStreetMap, and NFHS-5 district
health data. Each is cited per hospital. This one scores [96] out of 100, and every row is a quote you can open."
[derived/v2/README.md, README.md]

**1:25 tested like a trial.** "We fixed our rules before fitting, froze the model, published its hash, and only
then opened a sealed test set nobody had tuned on. 25 of the 28 places it rated Likely were confirmed, 89
percent, and it ranks with AUROC 0.82. Where a hospital's own website lists the service: 21 of 21."
[model/gold/v3/test_eval/results.json] The same line is on the Why page.

**1:50 transparent beat deep learning.** "We trained three transformer readers, two on a Databricks GPU. Our
transparent model matched or beat all three, so every recommendation stays explainable."
[model/reader/out/metrics_full.json, model/reader/out_gpu/metrics_gpu_remaining.json]

**2:05 built for the golden hour.** Gaya accident (24.79, 85.0, trauma). "A score is not a referral. In a
simulation of thousands of referrals, minutes mattered most, so in an emergency the app sends the patient to the
nearest place that can plausibly treat, and plans the whole route against the 60-minute window."
[submission/sim_results.csv] Show the map and the route: "[Going straight to All India Institute of Medical
Sciences Patna takes 92 min and misses the 60-minute window; stopping first at Dr. A Barkat Multispeciality
Hospital gives first care in about 1 min.]"

**2:40 built for the field.** "A map point we doubt is flagged before anyone drives to it. One tap calls; if
nobody answers, the next number is ready. Hindi, voice, a referral slip for the family on WhatsApp, and it keeps
working offline from a saved pack. Each call's outcome feeds back into the same evidence ledger." Show the Hindi
switch, the call loop and offline.

**3:05 on Databricks.** "All of it runs on Databricks Free Edition: the notebook rebuilds every table from the
Marketplace data, Unity Catalog holds them, AI Functions and a GPU tested the alternatives, Genie answers district
planners in plain English, and the app runs as a Databricks App."

**3:20 close.** "Not the nearest. Not the unreachable best. The place most likely to treat this patient in time,
with the evidence on the card."
