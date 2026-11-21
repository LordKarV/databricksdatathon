# Demo storyboard (3 minutes)

Built from `app_design/APP_EXPERIENCE.md` section 10.5. It shows only what the app does today; differences from
the spec are listed at the end. Shot ids match `demo/capture.py`, which records one continuous phone-size take
(360x780 at 2x) plus one still per shot into `demo/out/`. `shots.json` gives each shot's start and end in the take,
so the editor can cut to the narration in `demo/SCRIPT.md`.

The setup: the deployed Databricks App, with the browser's GPS set to Singwahini, Sitamarhi by the recording
script (the narration says so). The Bihar state pack is saved in the background during the plan shot, before
the offline shot.

| Time | Shot id | What is on screen | Must be visible (the WHY / HOW rule) |
| --- | --- | --- | --- |
| 0:00-0:15 | `open` | Start screen; GPS fills the place and accuracy by itself | The location line and its source |
| 0:15-0:35 | `plan` | Dialysis: first choice, two backups, CALL FIRST, the band on each card | The band words, the quote on each card, the travel range |
| 0:35-0:45 | `why_not` | "Why not the nearer ones?" opened (only when the query has nearer listings left out; otherwise cut) | The reason for each one left out |
| 0:45-1:10 | `why` | WHY card for option 1: quotes with claim ids, track record in words, "How we decided" with points | The points add up to the score |
| 1:10-1:20 | `call` | Call ahead: the question to ask; "Said no" is noted | The question and the reason it is asked |
| 1:20-1:35 | `slip` | Referral slip for the backup: no decimals, made time, 108 line | The made time and the "call before going" line |
| 1:35-2:00 | `route` | Accident: Suggested route, a stop for first care, then definitive care, with window checks and the comparison against going direct | Each stop's chance and evidence count; the window check |
| 2:00-2:20 | `offline` | Network off, reload: "No internet" banner; the same plan from the saved pack; call buttons still work | The banner and the pack date |
| 2:20-2:40 | `area` | Point moved to NH-19 by Mohania (q29); Area depth: honest abstention, gap split, ten calls | The gap split and the ten calls |
| 2:40-2:50 | `how` | How this works: data problem, how good it is (baselines, what did not work), limits | One evaluation table and the "did not work" list |
| 2:50-3:00 | `stories` | Two or three data stories (#53) | Each story's source line |

Close on the start screen with the line from SCRIPT.md.

## Different from the spec (10.5), on purpose or not built

- **Note scan** ("We read: 'Refer to higher centre for dialysis'"): not built, so not shown.
- **"Say this to the family" read aloud:** not built. The WHY card's text is shown instead.
- **"Said no" moves backup 1 up:** the app records the outcome on the slip; the backup is already the next card.
  The script says exactly that.
- **"DEMO LOCATION" banner:** there is no demo flag in the app. The browser's GPS is set by the recording
  script, and the narration says so on the first shot.
- **Model card calibration:** shown from the How this works page until #11 publishes the fitted model.

## Before recording

1. The lead redeploys after the PRs for the route (#56) and the data stories (#53) merge.
2. Run `.venv-app/bin/python demo/capture.py --local --headless` as a rehearsal. Every shot should print a time
   range, with none skipped.
3. Run `.venv-app/bin/python demo/capture.py` against the live app. Log in by hand in the window the first time.
4. Read the numbers for SCRIPT.md off the stills in `demo/out/shots/`, never from memory.
