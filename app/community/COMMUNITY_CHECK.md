# Community features: independent check (2026-11-21)

I checked field reports, the area pulse and the family journey card end to end, assuming the earlier reports were
wrong until I saw each result myself. Data was rebuilt in deploy.sh order (planner/export_v1, facts/build, packs,
howto, stories, verify_sites). Both app servers ran locally through uvicorn with `DATABRICKS_APP_PORT` set and
`REPORTER_KEY` set to a random 32-byte hex value:

- port 8765 with `COMMUNITY_DEMO=1`;
- port 8766 with `COMMUNITY_DEMO=0`.

`outcomes._sql` was replaced by an in-memory fake warehouse that logs every statement body. Nothing was written to
Databricks and nothing was committed.

The audit scripts are outside the worktree, in
`/private/tmp/claude-501/-Users-karthikvattem-projects-datathon/9dfde72e-e6a4-41f0-9f98-3c01b187efeb/scratchpad/audit/`:

- `serve.py` (fake warehouse);
- `field_e2e.py` (item 1);
- `pulse_attack.py` (item 2);
- `ui_check.py` and `live.py` (items 3 to 5, Playwright).

## Results

| # | Check | Result |
|---|-------|--------|
| 1a | One user moves nothing | PASS |
| 1b | 2-reporter rule | PASS |
| 1c | A phone "yes" alone never reads as "confirmed" | PASS |
| 1d | Temporary reasons never lower P(offers) | PASS |
| 1e | No "Unlikely" from reports alone | PASS, with the caveat in 1g |
| 1f | Ledger still sums with the Field reports row | PASS |
| 1g | The verdict shown stays coherent after strong disagreement | FAIL (not trivial, listed below) |
| 2 | Area pulse cannot be differenced down to one report | FAIL (4 leaks, listed below) |
| 3 | Storage and logs: parameterised SQL, no identity, free text or coordinates | PASS |
| 4 | Journey card offline: content, size, languages, large print, print CSS | PASS |
| 5 | Simulated data labelled everywhere it shows | FAIL, then fixed (ledger row) |
| 6 | Full suite and a11y check | PASS |

## 1. Field reports from 1, 2 and 3+ simulated users

The reports were posted to `/api/outcome` on the live server with different `X-Forwarded-User` headers at the
point (25.6, 85.1), Patna. I waited for the 60 s cache, then read each plan back.

| Scenario | p before -> after | Band | Field reports points | What the card says |
|----------|-------------------|------|----------------------|--------------------|
| S1: 1 user, visit accepted + phone yes | 0.92 -> 0.92 | unchanged | none | "Reports from 1 health worker ... One health worker's report does not change the score" |
| S2: 2 users, visits accepted | 0.91 -> 0.92 | unchanged | +2 | "2 accepted" |
| S3: 2 users, phone yes only | 0.91 -> 0.92 | unchanged | +1 | "2 said yes on the phone" |
| S4: 3 users, no_bed / machine_down / doctor_absent | 0.90 -> 0.90 | unchanged | none | 3 availability notes ("not whether the service exists") |
| S5: 3 users, visit turned away, service_not_here, on a Likely 0.97 | 0.97 -> 0.75 | likely | -24 | "Reports disagree with the listing: call first"; call_first becomes true |
| S6: 45 users, equipment_absent, on a Likely 0.97 | 0.97 -> 0.20 (range 0.07 to 0.43) | likely | -49 | the same, plus the flag |
| S7: 2 users said "no, not offered" on the phone, then visit accepted 1 h later | 0.95 -> 0.96 | unchanged | +2 | "2 accepted": the latest report per reporter wins |

- 1a. A second "yes" from the same user within 24 h returned 429. So did the same user with different casing and
  trailing space ("ASHA1@X.IN "). S1 moved nothing.
- 1c. Over every field line and note, in English and Hindi, there are 0 matches for "confirm", "verified",
  "guarantee" or the Hindi word for confirmation (puShTi).
- 1e. The floor holds at exactly 0.20 even with 45 reporters, and the band never changes.
- 1f. Total = sum of the rows on every option, which is what the faithfulness test checks. I also measured how far
  Total/10 sits from logit(p). Before field reports the gap was at most 0.44 points; after, at most 0.78 points
  (S7). Each row is rounded to whole points, so this is ordinary rounding, not a broken ledger.
- 1g (FAIL). In S6 the top option shows "Likely (0.20, range 0.07 to 0.43)". It still ranks first, ahead of an
  option at 0.91. Its `why_first_text` still says "this listing's evidence is stronger (0.97 against 0.91), so it
  ranks first". `say_to_family` still says "This hospital's listing says it offers heart surgery". Even in S5,
  "Likely 0.75, range 0.45 to 0.90" is borderline. The integration report lists this as a known issue (re-banding
  belongs to #63). It is not a trivial fix, because it needs a rule decision:
  - cap the field term at the band's lower line;
  - or move the option to "Not verified" when reports disagree;
  - and rebuild why_first_text from the post-field p.

## 2. Area pulse: re-identification attempts

I ran `pulse.aggregate` in-process with the real engine and constructed rows, and called `/api/pulse` over HTTP on
the live server.

What held:

- Hidden cells carry no number in the JSON, only `shown: false` and the HIDDEN text.
- No reporter keys, rows or coordinates are in the answer.
- Times are cut to the ISO week.
- A district+service query gives the same cells as the district query, so it reveals nothing more on its own.

What leaked:

- A (window differencing, serious). 30-day cell: 5 reports from 3 people. 90-day cell: 6 reports. The difference
  is exactly one report: a turn-away at a named facility. The facility row goes from (5, 3 accepted, 0 turned
  away) to (6, 3, 1). A hidden "asked_to_pay" reason cell appears only in the 90-day window. Together these say
  "one health worker reported that facility X turned a patient away and asked for money, 30 to 90 days ago". That
  is one person's report about a named hospital, which is the SAFETY 9 harm.
- B (total minus cells). The window total is shown while a service cell is hidden. Over HTTP: total 61, shown cells
  45 + 7 + 5 = 57, so the hidden MRI cell holds 4 reports from 2 people. In-process, a single burn_care report was
  recovered the same way (6 - 5 = 1).
- C (service minus facilities). Service cell decided 4, accepted 3. The shown facility has 0 turned away, and
  `facilities_hidden` = 1. So the one hidden facility turned away exactly 1 patient, and the hidden "no_bed"
  reason gives the cause.
- D (existence). A reason reported by one person still appears as a hidden row, for example "asked_to_pay" or
  "doctor_absent". That alone tells the reader such a report exists in that district and service.
- E (time differencing). The same query before and after one new report goes from (5, 3, 3) to (6, 3, 4), which
  reveals that report. This is inherent to any live count. The 60 s cache and the week cut do not hide it.
- With k = 3, two colluding reporters can subtract their own reports and recover the third's. NULL-key rows count
  toward MIN_REPORTS (3 keyed + 2 NULL is shown). That matches the stated rule.

Suggested fixes (not trivial, not applied):

- publish one window only, or make the windows disjoint and suppress each one on its own;
- show the total only as the sum of shown cells;
- drop hidden reason rows and `facilities_hidden`;
- consider k = 5 reporters for reason and facility cells.

## 3. Storage and logs

The live server logged 128 statements of four shapes:

- 61 MERGE;
- 63 rate-limit SELECT;
- 3 field aggregate reads;
- 1 pulse read.

Measured:

- Every value is a named STRING parameter.
- The only quoted literals are fixed: `array<string>`, `call` and `WEEK`.
- Parameter names: app_version, created_at, district, facility_id, kind, model_version, outcome, outcome_id,
  questions, reason, reporter_key, service, service_id, since, until.
- 0 statements or parameters contain a user id, an email, the header name, the secret or a coordinate.
- All 61 reporter_key values are 16 hex characters, with 48 distinct keys for 48 simulated users.
- `questions` holds the engine's own call-ahead text, not page text.
- The page's `/api/outcome` body (captured in Playwright) holds only outcome_id, facility_id, service_id, outcome,
  said_at_ms, lat 26.6, lon 85.48 (rounded to 0.01) and reason.
- The server keeps only the district.
- Both server logs (5 lines each) contain no user, email, key, coordinate or request line.

Notes, not failures:

- `created_at` is the tap time to the second. Together with a stable reporter_key, it lets anyone who can read
  the table link one worker's reports over time. Consider truncating it to the hour.
- Locally, `X-Forwarded-User` can be forged, so one person can act as many reporters. On Databricks Apps the proxy
  sets the header, but any 2 workspace accounts can still move a score.

## 4. Family journey card

I downloaded the card through the "Send to family" button (Web Share turned off) and opened it from `file://` in a
browser context with networking off.

- Size: 7,472 B (English) and 10,899 B (Hindi) for the two-stop route on option 1; 7,888 B and 7,941 B for options
  2 and 3.
- Network: 0 requests other than the file itself. The CSP is `default-src 'none'`.
- Read aloud, with speechSynthesis stubbed to capture the text: 17 utterances for option 1 and 9 for the others. The
  Hindi card speaks with `hi-IN`, the English card with `en-IN`. Phone numbers are read digit by digit.
- No patient data. There are 0 decimals or percentages in the visible text or the speech. The patient point
  (26.6, 85.48 or 26.5951, 85.4808) appears 0 times. The geo: and OSM links carry only the facility point.
- The only numbers on the card are 108, the plan's phone numbers, PIN codes in addresses, and the date the card was
  made. No field-report data reaches the card.
- `<html lang>` is "en" or "hi". Text is 18 px and becomes 28 px with "Large print" (aria-pressed toggles). 0
  visible targets are smaller than 44 px, and there is no horizontal scroll at 360 px.
- Print CSS: 12 pt (16 px), the tool buttons are hidden, and the call buttons become outlined.
- After the download, the live region announces "Family card saved to Downloads ..." in English and Hindi.
- Caveat, already listed by the integrator: a Likely option that reports disagree with still says "Listed for this
  service". "Call before you go" is always present.

## 5. Simulated data labels

All of these were labelled already:

- every field line and note on the cards, in both languages;
- the pulse banner and cell text.

The why-page ledger row was not. In demo mode, "Field reports +2" (p 0.92 -> 0.93 on dialysis option 1) carried no
label. Fixed: `field.py` now names the row "Field reports (simulated for the demo)" when the reports are simulated.
Verified in the plan from the restarted demo server.

The plan footer's "not read" note appears only when the warehouse read fails. With the fake warehouse it was
`read: true`.

## 6. Suite and accessibility

- `pytest app planner geo common -q -k "not latency"` (Python 3.11, playwright and axe installed): 314 passed, 0
  failed, before and after my two edits.
- `checks/a11y_check.py`: 55 states, 0 axe violations, no horizontal scroll. The critical path is 4 requests and
  21,619 B gzip (budget 50,000 B and 5 requests).
- The a11y run rewrote `app/checks/a11y_results.json` and the tracked screenshots again.

## Fixed here (trivial)

- `app/community/field.py`: the ledger row label says "(simulated for the demo)" when the reports are simulated.
- `app/static/pulse.js`: "1 other facilities" now reads "1 other facility". sw.js was not bumped, so a phone with
  the old cache keeps the old string until the next cache bump.

## Left open

1. 1g: after strong disagreement the verdict is incoherent. Likely stays with p 0.20, it still ranks first, and
   why_first_text cites 0.97. This needs a rule decision (#63).
2. 2A to 2D: pulse differencing leaks, with the fixes suggested above. 2A can expose a single "asked to pay" report
   about a named facility.
3. Linkability: an exact `created_at` plus a stable reporter_key in the table.
4. Two workspace accounts are enough to move a public score. A higher MIN_REPORTERS for downgrades would help.
5. Hindi strings are drafts until a native speaker reviews them (#10).
