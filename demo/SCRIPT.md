# Demo narration: the pitch (about 3 minutes 40 seconds, 560 words)

For the human narrator. The video follows one health worker and one emergency, a C-section near Lucknow (the
brief's own example question; phone GPS 26.86, 80.94), then one planned case, heart surgery near Patna (25.59,
85.14). Clicks are in `demo/RECORDING.md`. Every number is read from a committed file, named in brackets, or off
the screen, in [square brackets]; re-check them before recording and do not round them up. Simulation results
are always called a simulation. Show the deployed Databricks App, not local copies.

**0:00 the emergency.** "A woman in labour near Lucknow needs an emergency C-section, now. A health worker is with
her, phone in hand. Without help, the family goes to the nearest hospital they know of. That choice can kill her.
Bharosa is the health worker's second opinion, and it is built on data we audited first."

**0:15 we audited the data first.** Show the data stories page. "India's facility data is 10,000 records scraped
from the web. A quarter of them, 2,489 of 9,959, carry a sentence about a different hospital, because sources
were merged. 1,171 map points sat more than 25 km from the real hospital; we moved them. A chatbot cannot see
this: asked whether a Nagpur hospital offers dialysis, Llama 3.3 70B on our workspace said yes, confidence 1,
from sentences that belong to hospitals in Mumbai." [REPORT.md, cleaning/geo_identity/summary.json,
audit/capabilities/aiq2_rerun_20261122.json]

**0:40 the rescue.** Tap "C-section, emergency". "The nearest listing, City Hospital, is [300 metres] away on the
map. But its listing never mentions an operating theatre, and its address may put it in another area, up to
[227] minutes away. Go there, and she loses the hour she has. Bharosa passes it over and says why. Instead: BNK
Hospital, [4] minutes, rated Likely, with the receipt from its own listing: 'Performs Lower Segment Caesarean
Section'. It ranks first because it also shows evidence of blood transfusion, which the next hospital does not.
And the route check says it out loud: first care within 60 minutes, met, in about [4]."

**1:15 where to go.** Scroll to the map. "Here is where she is, and where each hospital is, on a real street map.
Hollow pins are places whose map point we doubt, so nobody drives to a wrong address. One tap opens turn-by-turn
directions."

**1:30 a model you can read.** Tap "Why this place?". "Every score is a sum of named witnesses: the hospital's own
sentence, whether that sentence is really about this hospital, its website, and official lists. We brought in
outside data for those lists: national accreditation (NABH), medical colleges (NMC), blood banks (e-RaktKosh),
LaQshya maternity certification, OpenStreetMap, and NFHS-5 district health data, each cited per hospital. BNK
scores [82] out of 100." [derived/v2/README.md, README.md]

**1:55 tested like a trial.** Point at the dots at the top of the Why page. "We fixed our rules before fitting,
froze the model, published its hash, and only then opened a sealed test set nobody had tuned on. 25 of the 28
places it rated Likely were confirmed, 89 percent, and it ranks with AUROC 0.82. We also trained three transformer
readers, two on a Databricks GPU; our transparent model matched or beat all three, so every answer stays
explainable." [model/gold/v3/test_eval/results.json, model/reader/out/metrics_full.json]

**2:20 the call.** Back to the answer. Tap Call, come back, tap "No answer". "If BNK does not pick up, the next
number is already on screen. In a simulation of thousands of referrals, that is what saves the hour: in an
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
