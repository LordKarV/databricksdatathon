# Recording runbook (for the demo video)

What to click, in order, to film the beats in `demo/SCRIPT.md`. The Gaya, Pusa, Patna and Gaya C-section
answers below were checked against the deployed app's API on 2026-11-22 (release 2359ed4, service worker
rs-shell-v37); the other flows are covered by the test suite but were not clicked through live. Rehearse once,
and re-check the numbers in brackets on the day; the narration reads them off the screen.

## Before you start

1. Open the app in Chrome, signed in to the Databricks workspace:
   https://referral-saathi-7474649134616784.aws.databricksapps.com
2. Open DevTools (Cmd+Opt+I), toggle the device toolbar (Cmd+Shift+M) and pick a phone about 360 x 780.
3. In DevTools open More tools > Sensors. Under Location choose "Other..." and type a latitude and longitude.
   This puts the phone in Gaya or Pusa; the app reads it as GPS.
4. On first visit pick English and Continue, and allow location.
5. If you rehearsed on an older build, do one hard reload (Cmd+Shift+R) so the v37 shell is in use.

## The beats

One emergency for the whole video: C-section near Lucknow. In Sensors set 26.86, 80.94. Checked on dev 0675784
(local, 2026-11-22); re-check the bracketed numbers on the deployed app.

| Script time | Location (Sensors) | Do this | What the screen shows |
|---|---|---|---|
| 0:00 the emergency | Lucknow 26.86, 80.94 | Home screen, located | The service tiles and "Call 108". Do not tap yet. |
| 0:20 data | any | Bottom bar: Data stories | The data stories. Stay on them; the model stories there are from v1. If #198 shipped, How this works shows the chatbot card (Wockhardt, Llama 3.3 70B). |
| 0:45 the answer | Lucknow | Home, "C-section, emergency" | Card 1 BNK Hospital, Likely, [4] min, "Performs Lower Segment Caesarean Section (LSCS)", and "First: it has evidence of blood transfusion, which Fatima Hospital does not show". |
| 1:15 the model | Lucknow | Card 1: "Why this place?", scroll slowly | The witnesses; "Likely, evidence score [82] / 100"; each row a quote. |
| 1:45 the sealed test | Lucknow | Scroll back to the top of the Why page | The dots: 25 of 28 places rated Likely were confirmed; under them "Passed over: City Hospital, 0.3 km. Its listing does not mention an operating theatre; its map point may be wrong". Hold it 5 s. |
| 2:15 map and clock | Lucknow | Back to the answer, scroll to the map, then Suggested route | Pin 1 BNK; hollow pins 2 and 3 (doubted map points); "first care (stabilised) within 60 min: met, about [4] min". |
| 2:40 the call loop | Lucknow | Card 1: Call. Cancel the Mac's call dialog, switch tab and back, tap "No answer" | "Call next" with Fatima Hospital's number. |
| 2:40 Hindi | Lucknow | Header button "हिन्दी" | The same answer in Hindi. Switch back the same way. |
| 2:40 family card | Lucknow | "Why this place?" > "Make a referral slip" | The slip and "Send on WhatsApp". |
| optional: offline | Lucknow | Get the answer online, DevTools Network: Offline, reload, ask again | The saved cards first, marked offline. |
| 3:05 Databricks | n/a | Workspace: the notebook; Catalog `workspace.referral_saathi`; Genie "Referral Saathi planner"; dashboard "Referral Saathi: district planner" | In Genie ask "Where can a patient get dialysis near Jaipur?" |

## Field reports

The live app has no real field reports yet, so the area pulse says "No counts to show". The script only says
outcomes feed the ledger and shows no report counts; the release runs without `COMMUNITY_DEMO`.

## Avoid on camera

- Typing "Pusa" lands on the Samastipur post office, not the doubt case. Use the Sensors point 25.6, 85.95.
- Gaya C-section has no place within the 60-minute window. Use Lucknow.
- On the answer, option 3 City Hospital shows a wide time range (its map point is doubted); do not dwell on it.
- In Genie, use the Jaipur dialysis question; the Lucknow C-section answer has not been checked.
- Dehradun trauma: Himalayan Hospital ranks above AIIMS Rishikesh, because AIIMS's listing has no 24x7 evidence.
  It is honest, but it needs explaining; leave it out.
