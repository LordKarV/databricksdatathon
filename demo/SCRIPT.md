# Demo script: the accident, then how it works (about 3 minutes 45 seconds)

Cast: the PATIENT (a teammate) and the HEALTH WORKER (a teammate); a NARRATOR voices over the screen parts. The
story is set near Gaya, Bihar: in Chrome DevTools > Sensors set 24.79, 85.0, hard-reload the app first
(Cmd+Shift+R). Clicks are in `demo/RECORDING.md`. Numbers in [square brackets] are read off the screen on the day;
every other number is from a committed file, named in brackets. Do not round them up.

The challenge slides ask: "A patient needs a specific kind of care. Where should they go, and why should they
trust that answer?" and "What they say they offer is in the data. Whether it's true is up to you." The video
answers both, in that order.

## Part 1: the accident (0:00 to 0:50, filmed, then the phone screen)

**0:00** PATIENT crosses, a "car" clips him, he goes down holding his leg. HEALTH WORKER runs over.
HEALTH WORKER: "Don't move. I'm calling 108." Taps the red "Call 108 ambulance" bar at the top of Bharosa.

**0:10** HEALTH WORKER (to camera, phone up): "The ambulance will ask where to take him." Taps "Accident or
injury". Screen recording takes over.

**0:15** NARRATOR: "Bharosa answers in under a second. Call first: Dr. A Barkat Multispeciality Hospital, [1]
minute away, rated Likely. The proof is on the card, from its own listing: 'Provides 24/7 trauma and emergency
care'." Scroll to Suggested route. "The hospital everyone knows is AIIMS Patna. But: [Going straight to All India
Institute of Medical Sciences Patna takes 92 min and misses the 60-minute window; stopping first at Dr. A Barkat
Multispeciality Hospital gives first care in about 1 min.] Stabilise first, then the big hospital."

**0:35** Scroll to the map. NARRATOR: "Where he is, where the hospital is, on a real street map, and one tap for
directions." HEALTH WORKER taps Call on card 1. (Cut: the PATIENT on a stretcher, thumbs up.)

## Part 2: why you can trust that answer (0:50 to 3:20, screen and voice-over)

**0:50 the data says what it says.** Show the data stories page. NARRATOR: "We were given 10,000 hospital records
scraped from the web. The slides said it plainly: what they say they offer is in the data; whether it is true is
up to you. So before any model, we audited the data. A quarter of the records, 2,489 of 9,959, carry a sentence
about a different hospital, because sources were merged. 1,171 map points sat more than 25 km from the real
hospital; we moved them." [REPORT.md, cleaning/geo_identity/summary.json]

**1:15 why not just ask a chatbot.** "We asked Llama 3.3 70B, on our Databricks workspace, whether a hospital in
Nagpur offers dialysis. Yes, confidence 1, from sentences that belong to hospitals in Mumbai. A language model
reads the words. It cannot tell whose words they are." [audit/capabilities/aiq2_rerun_20261122.json]

**1:30 the model.** Back to the Gaya answer, tap "Why this place?". "Our model is a calibrated statistical
scorecard, the same kind of model doctors trust for clinical risk. Each row here is a witness: the hospital's own
sentence; whether that sentence is really about this hospital; its website; and official lists we brought in from
outside: government trauma centres, national accreditation (NABH), medical colleges (NMC), blood banks
(e-RaktKosh), OpenStreetMap, and NFHS-5 district health data. The rows add up to a score, a fitted calibration
step turns the score into a probability, and location is scored separately, so a place we cannot pin down is
never called Likely. Barkat: [96] out of 100." [derived/v2/README.md, README.md]

**2:00 how we know it works.** Scroll to the top of the Why page, the dots. "We wrote the rule before fitting:
ship the simplest model unless a fitted one wins clearly. We trained fitted models and three transformer readers,
two on a Databricks GPU. The transparent scorecard matched or beat them all: AUROC 0.80 out of fold, calibrated
to within 4 points. Then we froze it, published its hash, and only then opened a sealed test set nobody had tuned
on: 25 of the 28 places it rated Likely were confirmed, and AUROC 0.82." [derived/v2/model_card.json,
model/gold/v3/test_eval/results.json, model/reader/out/metrics_full.json]

**2:30 from a score to a decision.** Back to the answer. "A score is not a referral. Two minutes away is a
children's clinic, Baibhav Shishu Care; its listing has no surgery or orthopaedics, so Bharosa passes it over and
says why. In a simulation of thousands of referrals, minutes mattered most, so in an emergency Bharosa sends the
patient to the nearest place that can plausibly treat, checks the route against the 60-minute window, and keeps
the next number ready if nobody answers." Tap Call, come back, "No answer": "Call next" appears.
[submission/sim_results.csv]

**2:55 built for the health worker.** Show the language list, then the Hindi answer, then the referral slip.
"Bharosa is for the person standing next to the patient: Hindi and eight more Indian languages, read aloud, a
referral slip the family gets on WhatsApp, and it still answers offline from a saved pack."

## Part 3: on Databricks, and the close (3:20 to 3:45)

**3:20** Show the notebook, the catalog and Genie. "All of it runs on Databricks Free Edition: the notebook
rebuilds every table from the Marketplace data, Unity Catalog holds them, AI Functions and a GPU tested the
alternatives, Genie answers district planners in plain English, and the app runs as a Databricks App."

**3:35** Back to the PATIENT, sitting up. NARRATOR: "Where should he go, and why should you trust it? The place
most likely to treat him in time, with the evidence on the card. Bharosa."
