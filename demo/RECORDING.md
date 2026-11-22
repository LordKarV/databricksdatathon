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

Two places. Lucknow C-section: Sensors 26.86, 80.94. Patna heart surgery: Sensors 25.59, 85.14 (or Change place
and type 800013). Checked on live v38 and dev on 2026-11-22; re-check the bracketed numbers on the day.

| Script time | Location (Sensors) | Do this | What the screen shows |
|---|---|---|---|
| 0:00 the emergency | Lucknow 26.86, 80.94 | Home screen, located | The service tiles and Call 108 / 102. |
| 0:15 data | any | Bottom bar: Data stories | The data stories (stay on them; the model stories there are from v1). Optional: How this works, the chatbot card. |
| 0:40 the rescue | Lucknow | Home, "C-section, emergency" | Card 1 BNK Hospital, Likely, [4] min, the LSCS quote, "First: it has evidence of blood transfusion...". Row 3 City Hospital, "Map point may be wrong", [1 to 227] min. Scroll to Suggested route: "first care (stabilised) within 60 min: met". |
| 1:15 where to go | Lucknow | Scroll to the map | Street map: You, pin 1 BNK, hollow pins 2 and 3; "Directions to 1. BNK Hospital". If the street map has not loaded, the drawn map shows instead. |
| 1:30 the model | Lucknow | Card 1: "Why this place?", scroll slowly | The witnesses; "Likely, evidence score [82] / 100". |
| 1:55 the sealed test | Lucknow | Top of the Why page | The dots: 25 of 28 confirmed; "Passed over: City Hospital, 0.3 km. Its listing does not mention an operating theatre; its map point may be wrong". |
| 2:20 the call | Lucknow | Back; card 1 Call; cancel the Mac dialog; switch tab and back; "No answer" | "Call next" with Fatima Hospital's number. |
| 2:40 planned care | Patna 25.59, 85.14 | Home, "Heart surgery" | Card 1 Ford Hospital And Research Center, Likely, [3] min, the CABG quote, "Why first: Its own website says so clearly, on 2 or more pages (+20.9); NABH's portal lists a related department for it (+8.6)". Its Why page: "Nothing nearer offers this care". |
| 3:00 field | Patna or Lucknow | Settings or the first-run chooser: the language list; then header "हिन्दी"; Why > "Make a referral slip" | The language list (Hindi plus eight, each marked machine translation); the Hindi answer; the slip and "Send on WhatsApp". |
| 3:20 Databricks | n/a | Workspace: the notebook; Catalog `workspace.referral_saathi`; Genie "Referral Saathi planner"; dashboard | In Genie ask "Where can a patient get dialysis near Jaipur?" |

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
