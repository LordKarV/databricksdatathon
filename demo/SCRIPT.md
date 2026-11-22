# Demo narration: the data story and the model (about 4 minutes, 600 words)

For the human narrator. Every number below is read from a committed file, named in brackets after it; re-check
them against those files before recording. Values in [square brackets with words] are read off the live app on
the day. Anything from the simulation is said as "in our simulation", never as a field result. Show the deployed
Databricks App and the notebook, not local copies.

**0:00 the question.** "A health worker in rural Bihar has a patient who needs care. Where should they go, and
why should they trust that answer? We had 10,000 Indian facility records, extracted from the web. So we started
by asking how far the data itself can be trusted."

**0:20 what the data hides.** Show the data stories page. "A quarter of the records, 2,489 of 9,959, contain a
sentence about a different facility, because records were merged. [REPORT.md] In 1,232 of them it is written as
if about the record itself, so a hospital can appear to offer a service it does not. Map points follow the wrong
facility too: cleaning moved 1,171 ranking points by more than 25 km. [cleaning/geo_identity/summary.json] And
public hospitals are nearly invisible online: a website answers for 29.8 percent of them, against two thirds of
private ones. [REPORT.md] Absence of evidence is not evidence of absence, and the model has to know that."

**0:55 the model.** Open a card's Why page. "So the model does not guess from text similarity. For every facility
and service it adds up named pieces of evidence, which we call witnesses:
- does the facility's own sentence offer the service;
- is that sentence really about this facility, or a merged neighbour;
- does its website agree;
- is it on an official list;
- is its location believable.
A witness that cannot be observed, like a website a public hospital never had, counts zero, not against it.
Each row on this page is a witness, and the rows add up exactly to the score."

**1:25 how we chose it.** "We labelled pairs, and used official accreditation lists as partial positive labels.
Before fitting, we fixed the rule: ship the simplest candidate unless a fitted one beats it by a clear margin out
of fold. The expert scorecard with one calibration step won. Out of fold on 221 labelled pairs it ranks with
AUROC 0.80, calibrated to within 4 points, and 102 of 120 pairs it calls Likely were confirmed.
[derived/v2/model_card.json]"

**1:50 the test we could not tune to.** "Then we froze the model, published its hash, and only then opened a
sealed test set. AUROC 0.82; Likely confirmed on 25 of 28. [model/gold/v3/test_eval/results.json] On public
hospitals our labels are too few to show the score ranks them, and the card says so instead of hiding it. These
labels were made by agents, not people; [human spot-check result, if done]."

**2:15 what failed.** "We also trained three transformer readers, one on a Databricks GPU. On 'does this
sentence offer the service', our rules beat all three, so the glass box shipped. [model/reader/out_gpu]"

**2:30 the decision, not just the score.** Pusa accident. "A good score is not yet a good referral. We built a
simulation where the truth is known, and found our first ranking lost to 'nearest place, call first' for trauma:
a 'no' on the phone costs five minutes, a wasted trip costs the golden hour. So in emergencies the app now calls
the nearest plausible place first." Show the route strip: "[route sentence from the screen]."

**3:00 the loop back into the data.** "Health workers log what happened: accepted, or turned away and why, from
fixed choices. Two or more reports become one more named row in the same ledger, as a Bayesian update. A
receptionist's 'yes' counts half; 'no bed today' is a warning, not a verdict. Coordinators see district counts
only when at least three workers stand behind them." Show voice in Hindi, the family card and offline packs as
"the same answer, reaching people who read Hindi, share by WhatsApp, or lose signal".

**3:35 on Databricks.** "All of it runs on Databricks Free Edition: the Marketplace data, a notebook that rebuilds
our cleaned tables from it, Unity Catalog tables, a Genie space for planners, the GPU training, and this app."

**3:50 close.** "Not the nearest. Not the unreachable best. The place most likely to treat this patient in time,
with the evidence on the card and the uncertainty said out loud."
