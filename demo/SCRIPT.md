# Demo narration (3 minutes 30 seconds, about 480 words)

For the human narrator. Values in [brackets] are read off the live app on the day, because the data can change;
the fixed numbers below come from committed files (`derived/v2/model_card.json`, `app/README.md`,
`app/voice/VOICE_CHECK.md`) and must be re-checked against them before recording. Show the deployed Databricks
App, not a local copy. Anything from the simulation is said as "in our simulation", never as a field result.

**0:00 the point.** "Most tools send you to the nearest hospital, or to the 'best' one on paper. The nearest may
not offer the care; the best may be too far to reach in time. Referral Saathi answers a different question for a
health worker: whom to call first, and why."

**0:15 voice.** "An ASHA worker near Pusa, Bihar, after a road accident. She speaks Hindi into the app." Play the
mic: "[spoken phrase]". "Speech is turned into text on the Databricks App itself; the audio is never stored. It
asks back, in Hindi, 'trauma care?', and she taps yes. Danger words like heavy bleeding put Call 108 on top."

**0:35 the answer.** "First choice, two backups, and CALL FIRST. Each card says how sure we are, in words, and
quotes the facility's own listing. Why not the nearest? [Nearest name] is [n] minutes closer, but [reason from
why_not]."

**0:55 the route.** "Going straight to Rajeshwar Hospital takes 84 minutes and misses the 60-minute window.
Stopping first at Miracare gives first care in about 34 minutes. And the app says what would change this: a yes
from Sub Divisional Hospital Pusa on the phone."

**1:15 why and how.** Open the why page. "Every score is a sum of named pieces of evidence: what the listing
says, whether its own website agrees, whether it is on an official list, whether its location is in doubt. These
rows add up exactly to the number on the card. Nothing is hidden."

**1:35 call and report.** "She calls. The app lists what to ask. Later she logs what happened: accepted, or
turned away and why, from fixed choices. Two or more health workers' reports become one more named line in the
evidence. A 'yes' on the phone counts half; 'no bed today' is a warning, not a verdict about the hospital."

**1:55 the family.** "She sends the family a journey card on WhatsApp: the stops, phone numbers, 108, what to
bring, and a button that reads it aloud in Hindi. No login, no patient details, no percentages."

**2:10 offline and borders.** "No signal? The phone saved every state pack within 150 km, so a closer hospital
across the state border still shows. Near borders, 24 percent of the time the nearest facility offering the
service is in the neighbouring state."

**2:25 for planners.** "A coordinator sees the area: where care is confirmed, where it is only expected, and
care gaps like [Bahraich: no C-section within reach], so they know where a phone call or an investment matters."

**2:40 how good is it.** "We say so plainly. Out of fold on 221 labelled pairs the model ranks offers with AUROC
0.80 and is calibrated to within 4 points. On public hospitals our labels are too few to show it works, and the
card says so. On a sealed test set it scored [TEST headline]. In our simulation, [simulation line from #92]."

**3:00 Databricks.** "All of it runs on Databricks Free Edition: the Marketplace data, a notebook that rebuilds
our cleaned tables from it, Unity Catalog tables, a planner dashboard and a Genie space, the reader models we
trained on a Databricks GPU and rejected because rules did better, and this app."

**3:15 close.** "Not the nearest. Not the unreachable best. The place most likely to treat this patient in time,
with the evidence on the card."
