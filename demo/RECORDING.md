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

| Script time | Location (Sensors) | Do this | What the screen shows |
|---|---|---|---|
| 0:20 data | any | Bottom bar: Data stories | The data stories. Stay on them; the model stories there are from v1. |
| 0:50 the model | Gaya 24.79, 85.0 | Home, "Accident or injury", then "Why this place?" on card 1 | Dr. A Barkat Multispeciality Hospital, Likely. The Why page lists the witnesses; the rows add up to the score. |
| 1:45 the sealed test | any | Bottom bar: How this works, scroll to the v2 evaluation table | The sealed TEST numbers the narration reads (AUROC with its interval). Hold it about 5 s. |
| 2:25 the route | Gaya 24.79, 85.0 | Back to the answer, scroll to the route | "Going straight to All India Institute of Medical Sciences Patna takes [92] min and misses the 60-minute window; stopping first at Dr. A Barkat Multispeciality Hospital gives first care in about [1] min." |
| optional: location doubt | Pusa 25.6, 85.95 | Home, "Accident or injury" | Card 1 Miracare Hospital (Likely, 34 min). Card 2 Sub Divisional Hospital Pusa, 19 min, flagged: its map point is not in Pusa, so the route does not use it. |
| 2:55 the call loop | Gaya 24.79, 85.0 | Card 1: Call. Cancel the Mac's call dialog, switch to another tab and back, tap "No answer" | "Call next" with option 2's number; the Call bar no longer offers option 1. |
| 2:55 Hindi | same | Header button "हिन्दी" | The whole screen in Hindi, one language at a time. Switch back the same way. |
| 2:55 voice | same | Home, "Something else", then the microphone | Speak "dialysis chahiye"; the app asks Yes / No before it searches. |
| 2:55 family card | same | "Why this place?" > "Make a referral slip" | The slip and "Send on WhatsApp". |
| 2:55 offline | same | Get an answer online, then DevTools Network: Offline, reload, ask again | An answer from the stored radius pack, marked offline. |
| optional: planned care | type "Patna" | Change location, type Patna, then "Dialysis" | Satyavrat Hospital, Likely, 2 min, and a three-step pathway: assessment, fistula, regular sessions. |
| optional: area brief | any | Bottom bar: Area, pick a district | The district brief: NFHS-5, LaQshya and access figures. |
| 3:25 Databricks | n/a | Workspace: the notebook; Catalog `workspace.referral_saathi`; Genie "Referral Saathi planner"; dashboard "Referral Saathi: district planner" | In Genie ask "Where can a patient get dialysis near Jaipur?" |

## Field reports

The live app has no real field reports yet, so the area pulse says "No counts to show". The script's 2:55 line
says so ("No real reports exist yet, and the app says so"); the release runs without `COMMUNITY_DEMO`.

## Avoid on camera

- Typing "Pusa" lands on the Samastipur post office, not the doubt case. Use the Sensors point 25.6, 85.95.
- Gaya C-section has no place within the 60-minute window (option 1 is 98 min away). It is an honest "no good
  answer" example, not a hero shot.
- In Genie, use the Jaipur dialysis question; the Lucknow C-section answer has not been checked.
- Dehradun trauma: Himalayan Hospital ranks above AIIMS Rishikesh, because AIIMS's listing has no 24x7 evidence.
  It is honest, but it needs explaining; leave it out.
