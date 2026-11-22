# Demo narration: the pitch (about 3 minutes 40 seconds, 560 words)

For the human narrator. The video opens with a short skit: a teammate is hurt in a road accident near Gaya, Bihar
(phone GPS 24.79, 85.0), and another teammate, playing the health worker, uses Bharosa. Then one planned case,
heart surgery near Patna (25.59, 85.14). Clicks are in `demo/RECORDING.md`. Every number is read from a committed
file, named in brackets, or off the screen, in [square brackets]; re-check them before recording and do not round
them up. Simulation results are always called a simulation. Show the deployed Databricks App, not local copies.

**0:00 the skit.** A teammate is knocked off a bike and does not get up. Another kneels, calls 108 from the red
bar, and opens Bharosa. Narrator: "A road accident near Gaya, in rural Bihar. The hospital everyone knows is AIIMS
Patna. Drive straight there, and he misses the golden hour. A health worker with the right answer gets him care
in time. Bharosa is that answer, built on data we audited first."

**0:20 we audited the data first.** Show the data stories page. "India's facility data is 10,000 records scraped
from the web. A quarter of them, 2,489 of 9,959, carry a sentence about a different hospital, because sources
were merged. 1,171 map points sat more than 25 km from the real hospital; we moved them. A chatbot cannot see
this: asked whether a Nagpur hospital offers dialysis, Llama 3.3 70B on our workspace said yes, confidence 1,
from sentences that belong to hospitals in Mumbai." [REPORT.md, cleaning/geo_identity/summary.json,
audit/capabilities/aiq2_rerun_20261122.json]

**0:45 the rescue.** Tap "Accident or injury". "Dr. A Barkat Multispeciality Hospital, [1] minute away, rated
Likely, with the receipt from its own listing: 'Provides 24/7 trauma and emergency care'. And the route says it
out loud:" read the route line: "[Going straight to All India Institute of Medical Sciences Patna takes 92 min and
misses the 60-minute window; stopping first at Dr. A Barkat Multispeciality Hospital gives first care in about 1
min.] Stabilise first, then the big hospital."

**1:15 where to go.** Scroll to the map. "Here is where he is, and where each hospital is, on a real street map.
Hollow pins are places whose map point we doubt, so nobody drives to a wrong address. One tap opens turn-by-turn
directions."

**1:30 a model you can read.** Tap "Why this place?". "Every score is a sum of named witnesses: the hospital's own
sentence, whether that sentence is really about this hospital, its website, and official lists. We brought in
outside data for those lists: national accreditation (NABH), medical colleges (NMC), blood banks (e-RaktKosh),
government trauma centres, OpenStreetMap, and NFHS-5 district health data, each cited per hospital. This one
scores [96] out of 100." [derived/v2/README.md, README.md]

**1:55 tested like a trial.** Point at the dots at the top of the Why page. "We fixed our rules before fitting,
froze the model, published its hash, and only then opened a sealed test set nobody had tuned on. 25 of the 28
places it rated Likely were confirmed, 89 percent, and it ranks with AUROC 0.82. We also trained three transformer
readers, two on a Databricks GPU; our transparent model matched or beat all three, so every answer stays
explainable." [model/gold/v3/test_eval/results.json, model/reader/out/metrics_full.json]

**2:20 the call.** Back to the answer. Tap Call, come back, tap "No answer". "If Barkat does not pick up, the
next number is already on screen. In a simulation of thousands of referrals, that is what saves the hour: in an
emergency, the nearest place that can plausibly treat, then call the next." [submission/sim_results.csv]

**2:40 planned care is different.** Change place to Patna, tap "Heart surgery". "For heart surgery there is time,
so Bharosa ranks by evidence, not distance. Ford Hospital: its own website says so on two or more pages, and the
national accreditation portal lists a related department. Pulse Emergency Hospital, just as close, is passed over:
its listing has no cath lab or heart-lung machine."

**3:00 built for the field.** "The same answer in Hindi and eight more Indian languages, read aloud, as a referral
slip the family gets on WhatsApp, and offline from a saved pack. Each call's outcome feeds back into the same
evidence ledger." Show the language menu, the Hindi answer and the slip.

**3:20 on Databricks.** "All of it runs on Databricks Free Edition: the notebook rebuilds every table from the
Marketplace data, Unity Catalog holds them, AI Functions and a GPU tested the alternatives, Genie answers district
planners in plain English, and the app runs as a Databricks App."

**3:35 close.** "Not the nearest. Not the unreachable best. The place most likely to treat this patient in time,
with the evidence on the card."
