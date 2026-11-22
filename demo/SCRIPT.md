# Demo narration (3 minutes 30 seconds, about 480 words)

For the human narrator. Values in [brackets] are read off the live app on the day, because the data can change; the
fixed numbers below come from committed files (`derived/v2/model_card.json`,
`model/gold/v3/test_eval/results.json`, `REPORT.md`, `app/README.md`, `app/voice/VOICE_CHECK.md`) and the app's own
answer for Pusa (trauma, 25.6, 85.95), and must be re-checked against them before recording. Show the deployed
Databricks App, not a local copy. Anything from the simulation is said as "in our simulation", never as a field
result.

**0:00 trust first.** Open on Miracare Hospital's why page: its quote, the source page link, the sealed test
record. "Where should she send this patient, and why trust the answer? Every card quotes the facility's own words
and links the page. A quarter of the listings carry sentences about other hospitals; we never quote those. On a
test set sealed before the model was frozen, 25 of 28 places we rate Likely were confirmed: agent-labelled, not yet
human-checked."

**0:20 voice.** "An ASHA worker near Pusa, Bihar, after a road accident. She speaks Hindi into the app." Play the
mic: "[spoken phrase]". "Speech becomes text on the Databricks App itself; the audio is never stored. It asks back,
in Hindi, 'accident or injury?', and she taps yes. Danger words like heavy bleeding put Call 108 on top."

**0:35 the answer.** "First choice and two backups, each saying in words how sure we are. First is Sub Divisional
Hospital Pusa, about 19 minutes away, marked call first. In an emergency the nearest plausible place comes first.
If Pusa says no, she calls Miracare, rated Likely, 15 minutes farther."

**0:55 the route.** "Going straight to Ganpati Hospital takes 80 minutes and misses the 60-minute window. Stopping
first at Pusa gives first care in about 19 minutes."

**1:10 why and how.** Open Pusa's why page. "Its own sentences and source page, whether its phone is shared,
whether its map point agrees with its PIN, here a warning, and how often listings like this checked out. Nothing is
hidden."

**1:30 call and report.** "She calls. The app lists what to ask. Later she logs what happened: accepted, or turned
away and why, from fixed choices. Two or more health workers' reports become one more named line in the evidence. A
'yes' on the phone counts half; 'no bed today' is a warning, not a verdict."

**1:50 the family.** "She sends the family a journey card on WhatsApp: the stops, phone numbers, 108, what to
bring, and a button that reads it aloud in Hindi. No login, no patient details, no percentages."

**2:05 offline and borders.** "No signal? The phone saved every state pack within 150 km, so a closer hospital
across the state border still shows. Near borders, 24 percent of the time the nearest facility offering the service
is in the neighbouring state."

**2:20 for planners.** "A coordinator sees the area: where care is confirmed, where it is only expected, and care
gaps like [Bahraich: no C-section within reach], so they know where a phone call or an investment matters."

**2:35 how good is it.** "We say so plainly. Out of fold on 221 labelled pairs the model ranks offers with AUROC
0.80, its chances off by about 4 points on average. On public hospitals our labels are too few to show it ranks
well, and the card says so. In our simulation, our first emergency order lost to 'nearest place, call first'. We
changed it: now it trails by 1 to 2 points, and leads only where the model is assumed right."

**3:00 Databricks.** "It runs on Databricks Free Edition: the Marketplace data, a notebook that rebuilds our
cleaned tables, Unity Catalog tables, a planner dashboard and a Genie space, and this app. We trained reader
models, two on a Databricks GPU, and dropped them: rules did better."

**3:15 close.** "Not the nearest. Not the unreachable best. The place most likely to treat this patient in time,
with the evidence on the card."
