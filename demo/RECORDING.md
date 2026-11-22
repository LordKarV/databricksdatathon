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

Two places. Gaya road accident: Sensors 24.79, 85.0. Patna heart surgery: Sensors 25.59, 85.14. Checked on dev on
2026-11-22; re-check the bracketed numbers on the day. Film the skit (0:00) on a phone camera; everything else is
a screen recording.

| Script time | Location (Sensors) | Do this | What the screen shows |
|---|---|---|---|
| 0:00 the skit | Gaya 24.79, 85.0 | Teammate "falls"; the health worker taps the red "Call 108" bar, then opens Bharosa | The home screen, located near Gaya, Call 108 on top. |
| 0:20 data | any | Bottom bar: Data stories | The data stories (stay on them; the model stories there are from v1). Optional: How this works, the chatbot card. |
| 0:45 the rescue | Gaya | Home, "Accident or injury"; scroll to Suggested route | Card 1 Dr. A Barkat Multispeciality Hospital, Likely, [1] min, "Provides 24/7 trauma and emergency care". The route line: "Going straight to All India Institute of Medical Sciences Patna takes [92] min and misses the 60-minute window; stopping first at Dr. A Barkat Multispeciality Hospital gives first care in about [1] min." |
| 1:15 where to go | Gaya | Scroll to the map | Street map: You, pin 1 Barkat, pins 2 and 3; "Directions to 1. ...". If the street map has not loaded, the drawn map shows instead. |
| 1:30 the model | Gaya | Card 1: "Why this place?", scroll slowly | The witnesses; "Likely, evidence score [96] / 100". |
| 1:55 the sealed test | Gaya | Top of the Why page | The dots: 25 of 28 confirmed, and the Passed over line. |
| 2:20 the call | Gaya | Back; card 1 Call; cancel the Mac dialog; switch tab and back; "No answer" | "Call next" with option 2's number (Arsh Superspeciality Hospital). |
| 2:40 planned care | Patna 25.59, 85.14 | Home, "Heart surgery" | Card 1 Ford Hospital And Research Center, Likely, [3] min, the CABG quote, "Why first: Its own website says so clearly, on 2 or more pages (+20.9); NABH's portal lists a related department for it (+8.6)". Its Why page: "Nothing nearer offers this care". |
| 3:00 field | Gaya | Settings or the first-run chooser: the language list; then header "हिन्दी"; Why > "Make a referral slip" | The language list (Hindi plus eight, each marked machine translation); the Hindi answer; the slip and "Send on WhatsApp". |
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
