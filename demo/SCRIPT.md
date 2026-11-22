# Demo script: the accident, then how it works (2 minutes 30 seconds)

Cast: the PATIENT and the HEALTH WORKER (teammates); a NARRATOR voices over the screen parts. Set near Gaya,
Bihar: Chrome DevTools > Sensors 24.79, 85.0; hard-reload the app first (Cmd+Shift+R). Clicks are in
`demo/RECORDING.md`. Numbers in [square brackets] are read off the screen; the rest are from committed files,
named in brackets. About 330 spoken words: keep the pace brisk and do not add lines.

The slides ask: "Where should they go, and why should they trust that answer?" and say "What they say they offer
is in the data. Whether it's true is up to you." Part 1 answers the first question, Part 2 the second.

## Part 1: the accident (0:00 to 0:35)

**0:00** The PATIENT is clipped by a "car" and goes down. The HEALTH WORKER runs over: "Don't move. I'm calling
108." Taps the red "Call 108" bar in Bharosa, then "Accident or injury". Cut to the screen recording.

**0:10** NARRATOR: "Call first: Dr. A Barkat, [1] minute away, rated Likely, and the proof from its own listing:
'24/7 trauma and emergency care'." Scroll to the route. "The hospital everyone knows, AIIMS Patna, is [92]
minutes away and misses the golden hour. Stabilise at Barkat first." Scroll to the map: "Where he is, where it
is, and one tap for directions." HEALTH WORKER taps Call. Cut: the PATIENT on a stretcher, thumbs up.

## Part 2: why you can trust that answer (0:35 to 2:15)

**0:35 the data.** Data stories page. "We were given 10,000 hospital records scraped from the web, and whether
they are true was up to us. So we audited them: a quarter carry a sentence about a different hospital, from
merged sources, and 1,171 map points were more than 25 km off; we moved them. Then we added what the data lacked:
eight public sources, from NABH accreditation and government trauma centres to blood banks and OpenStreetMap, plus
a crawl of the hospitals' own websites. A chatbot can't do this: Llama 3.3 70B said a Nagpur hospital offers
dialysis, confidence 1, from a Mumbai hospital's sentences." [REPORT.md, cleaning/geo_identity/summary.json,
README.md source table, audit/capabilities/aiq2_rerun_20261122.json]

**1:00 the model.** Tap "Why this place?". "Our model is a calibrated statistical scorecard. Each row is a
witness: the hospital's own sentence, whether that sentence is really about it, its own website, and the public
lists we joined. The rows add up to a probability; location is scored separately. Barkat: [96] out of 100."
[derived/v2/README.md]

**1:25 the proof.** The dots at the top. "We fixed the rule before fitting, and the transparent model beat fitted
models and three transformers trained on a Databricks GPU. Then we froze it and opened a sealed test: 25 of 28
places it called Likely were confirmed, AUROC 0.82." [model/gold/v3/test_eval/results.json,
model/reader/out/metrics_full.json]

**1:45 the decision.** Back to the answer. "A score is not a referral. A children's clinic two minutes away has
no surgery in its listing, so it is passed over, with the reason. In an emergency Bharosa picks the nearest place
that can plausibly treat, checks the 60-minute window, and keeps the next number ready." Tap Call, "No answer":
"Call next" appears.

**2:05 the field.** Language list, then the Hindi answer. "In Hindi and eight more Indian languages, and offline."

## Part 3: Databricks and the close (2:15 to 2:30)

**2:15** Notebook, catalog, Genie. "All on Databricks Free Edition: notebook, Unity Catalog, AI Functions, a GPU,
Genie and a Databricks App."

**2:22** The PATIENT, sitting up. NARRATOR: "The place most likely to treat him in time, with the evidence on the
card. Bharosa."
