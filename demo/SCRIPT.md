# Demo narration: the data story and the model (about 3 minutes 40 seconds, 520 words)

For the human narrator. Every number below is read from a committed file, named in brackets after it; re-check
them before recording. Values in [square brackets with words] are read off the live app on the day. Anything
from the simulation is said as "in our simulation", never as a field result. Show the deployed Databricks App
and the notebook, not local copies. On the data stories page, stay on the data stories; the model stories there
are from v1.

**0:00 the question.** "A health worker in rural Bihar has a patient who needs care. Where should they go, and
why should they trust that answer? We had 10,000 facility records extracted from the web, so we first asked how
far the data itself can be trusted."

**0:20 what the data hides.** Show the data stories page. "A quarter of the records, 2,489 of 9,959, contain a
sentence about a different facility, because records were merged; in 1,232 it reads as if about the record
itself. [REPORT.md] Map points follow the wrong place too: cleaning moved 1,171 of them by more than 25 km.
[cleaning/geo_identity/summary.json] And public hospitals are nearly invisible online: 18 percent have a working
website, against 51 percent of private ones. [viz/gallery.json, geography_s6_website]"

**0:50 the model.** Open a Likely card's Why page. "So the score is a sum of named pieces of evidence, which we
call witnesses: does the facility's own sentence offer the service, is that sentence about this facility or a
merged neighbour, does its website agree, is it on an official list. A witness that cannot be observed, like a
website a public hospital never had, counts zero, not against it. Each row here is a witness, and the rows add up
to the score. Location is checked separately: a place we cannot pin down is never called Likely."
[derived/v2/README.md]

**1:20 how we chose it.** "Agents read the web and labelled facility and service pairs; no person checked those
labels, and we say so. Before fitting, we fixed the rule: ship the simplest model unless a fitted one wins
clearly out of fold. The expert scorecard with one calibration step won. Out of fold on 221 pairs it ranks with
AUROC 0.80 and is calibrated to within 4 points. We set the Likely line on those pairs, so the real check comes
next." [derived/v2/model_card.json]

**1:45 the test we could not tune to.** "Then we froze the model, published its hash, and only then opened a
sealed test set. Of the pairs it called Likely and the web could decide, 25 of 28 were confirmed; the score
also ranks well within a list, AUROC 0.82. Where a facility's own website states the service, the model and the
web check read the same page: 21 of 21 confirmed. Where it does not, the score ranks above chance but weakly,
AUROC 0.70. Ninety of the 150 could not be decided from the web at all, which is why every card says call first.
On public hospitals we cannot show the score ranks them, and the card says that too."
[model/gold/v3/test_eval/results.json, model/gold/v3/test_eval/independence.json]

**2:10 what failed.** "We trained three transformer readers, two on a Databricks GPU. On 'does this sentence
offer the service', our rules beat all three, and on 'is it about this facility' none showed a gain, so the glass
box shipped." [model/reader/out/metrics_full.json, model/reader/out_gpu/metrics_gpu_remaining.json]

**2:25 a score is not a referral.** Pusa accident. "In a simulation where the truth is known, our first ranking
lost to 'nearest place, call first' for trauma: a 'no' on the phone costs five minutes, a wasted trip costs the
golden hour. So in emergencies the app now calls the nearest plausible place first. In our simulation it is now
within one to two points of nearest place plus a call, and ahead only when we assume the model is right, because
it offers only places whose own listing it can quote. In an emergency the score filters and explains; the call
decides. The multi-stop route is not part of the simulation." [submission/sim_results.csv, sim/README.md] Show the
route: "[route sentence from the screen]."

**2:55 the loop back into the data.** "Health workers log what happened, from fixed choices. Reports from at
least two different workers become one more named row in the same ledger; they can lower a score, never raise
it. A receptionist's 'yes' counts half. The reports on screen today are simulated and labelled so." [field.py]
Show the Hindi switch, voice, the family card and offline: "the same answer, for people who read Hindi, share by
WhatsApp, or lose signal."

**3:25 on Databricks.** "The notebook rebuilds our cleaned tables from the Marketplace data on Free Edition. The
app, the Unity Catalog tables and the Genie space for planners run in our Databricks workspace."

**3:35 close.** "Not the nearest. Not the unreachable best. The place most likely to treat this patient in time,
with the evidence on the card and the uncertainty said out loud."
