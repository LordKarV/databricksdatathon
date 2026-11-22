# Demo script: a road accident near Gaya (2 minutes 30 seconds)

Cast: a teammate as the PATIENT, Keshav as the community health worker, Kartik for the field features, Aarav for
Databricks; one NARRATOR. In Chrome DevTools > Sensors set 24.79, 85.0 (Gaya) and hard-reload (Cmd+Shift+R)
before recording. Numbers in [square brackets] are read off the screen; the rest come from committed files.

**0:00 to 0:15 | The accident**
[ON SCREEN: the PATIENT is hit by a "car" outside a village near Gaya and goes down holding his leg. Keshav runs
over, taps "Call 108" in Bharosa, then "Accident or injury". A timer starts.]
"A village outside Gaya, Bihar. A road accident, and the clock starts: trauma care has a golden hour. Keshav, a
community health worker, has to decide where to send him, now. Bharosa answers in under a second."

**0:15 to 0:35 | The answer**
[ON SCREEN: card 1, then the route line, then the street map with Directions.]
"Call first: Dr. A Barkat Multispeciality Hospital, [1] minute away, rated Likely, with the proof from its own
listing: '24/7 trauma and emergency care'. The hospital everyone knows, AIIMS Patna, is [92] minutes away and
misses the golden hour, so Bharosa says: stabilise at Barkat first, then go on. The street map shows where he is
and where Barkat is, with one-tap directions."

**0:35 to 0:55 | The data problem, and the data we added**
[ON SCREEN: the data stories page.]
"Behind that answer is a dataset we did not trust. Of 9,959 hospital records scraped from the web, 2,489 contain
sentences about a different hospital, from merged sources; 1,232 read as if about the hospital itself, and we
quarantined them as evidence. 1,171 map points were more than 25 km off; we moved them. Then we added what the
data lacked: eight public sources, from NABH accreditation and government trauma centres to blood banks and
OpenStreetMap, plus a crawl of the hospitals' own websites. They testify on 3,798 hospital and service pairs."

**0:55 to 1:08 | Why a chatbot is not enough**
[ON SCREEN: How this works, the Wockhardt card.]
"We asked Llama 3.3 70B whether Wockhardt Hospital Nagpur offers dialysis. Yes, confidence 1, quoting sentences
that belong to hospitals in Mumbai. A language model reads the words; it cannot tell whose words they are.
Bharosa checks, and passes that record over."

**1:08 to 1:30 | The model**
[ON SCREEN: card 1, "Why this place?", the ledger.]
"Our model is a calibrated statistical scorecard, the kind of model clinical risk scores use. Each row is a
witness: the hospital's own sentence, whether that sentence is really about it, its website, and the public lists
we joined. It also checks what the care needs: trauma needs surgery or orthopaedics, so a children's clinic two
minutes away is passed over, with the reason. The rows add up; a fitted calibration turns them into a
probability; location is scored separately, so a place we cannot pin down is never called Likely. Missing
evidence counts zero, not against a hospital. Barkat: [96] out of 100."

**1:30 to 1:50 | Model validation**
[ON SCREEN: the sealed-test dots at the top of the Why page, then How this works, the evaluation table.]
"We wrote the selection rule before fitting: ship the simplest model unless a fitted one wins clearly. Out of
fold it ranked with AUROC 0.80 and was calibrated to within 4 points; three transformer readers, two trained on a
Databricks GPU, matched it at best. Then we froze it, published its hash, and opened a sealed test set: 25 of the
28 places it rated Likely were confirmed, 89 percent, AUROC 0.82."

**1:50 to 2:05 | From a score to a referral**
[ON SCREEN: back to the answer; Call, then "No answer", then "Call next".]
"A score is not a referral. In a simulation of thousands of referrals, minutes mattered most, so in an emergency
Bharosa picks the nearest place that can plausibly treat, checks the 60-minute window, and keeps the next number
ready if nobody answers."

**2:05 to 2:18 | Designed for real-world use**
[ON SCREEN: Kartik shows the language list, the Hindi answer, voice input, the WhatsApp referral slip and
offline mode.]
"Bharosa is built for the health worker: one-tap calls, Hindi and eight more Indian languages, voice input,
WhatsApp referral slips, and answers offline. Call outcomes feed back into the same evidence."

**2:18 to 2:30 | Databricks and conclusion**
[ON SCREEN: Aarav shows the notebook, Unity Catalog, AI Functions, Genie and the app.]
"All of it runs on Databricks Free Edition: the notebook, Unity Catalog, AI Functions, a GPU, Genie and a
Databricks App. Bharosa turns unreliable hospital data into referrals you can trust, in time."
