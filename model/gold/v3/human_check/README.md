# Human spot-check of the gold v3 labels (issue #103)

The gold v3 labels were made by AI agents reading public web pages. Nobody has yet checked them by hand. This
check asks three people to read the pages for 25 labels and say, on their own, whether each facility offers the
service. The result is the project's only human-checked accuracy figure for its labels.

## What you need

- Your own sheet. Open it in any spreadsheet program. When you are done, save it as **CSV UTF-8**.

  | person | sheet | rows |
  | --- | --- | --- |
  | Karthik | `sheet_karthik.csv` | 8 |
  | Aayan | `sheet_aayan.csv` | 8 |
  | Aarav | `sheet_aarav.csv` | 9 |

- About 4 minutes per row: **about 35 minutes** each (1.5 to 2 hours across all 25 rows). You can stop and come
  back; save as you go.
- **Do not open `agent_answers.csv` until you have finished every row.** It holds the agent's verdicts. The
  check only means something if you decide first. Do not compare answers with the other two before you finish.

## The 25 rows

- Drawn at random (`build_sheet.py`, seed 20261122): 15 the agent marked confirmed and 10 it marked
  contradicted. You are not told which.
- They come from both splits in proportion: 17 DEV and 8 TEST.
- Only "decided" labels are included. A "no information" verdict cannot be checked against a page.
- Split into the three sheets above, spread as evenly as possible across the agent's verdicts (each sheet has 5
  confirmed and 3 or 4 contradicted) and across services. `row` keeps the 1 to 25 numbering of the whole draw.

## Columns, left to right

| column | what it is |
| --- | --- |
| `row`, `pair_id` | row number and label id; do not edit |
| `facility`, `place` | the facility's name, and its city and state |
| `service` | the service you are checking (see "Services" below) |
| `service_means` | one line on what counts as offering it |
| `evidence_urls` | the page(s) the agent read, separated by spaces |
| `human_verdict` | **your answer:** `confirmed`, `contradicted` or `cannot_tell` |
| `url_used` | the page that decided your answer, if it is not one of `evidence_urls` |
| `note` | anything useful, e.g. "page moved", "quote is about a different branch" |
| `quote` | a short quote the agent took from a page. **Check the page first, then look at the quote.** |

## Services

From the labelling rubric (`../RUBRIC.md`), with the edge cases the agents applied:

| service | counts as offered when |
| --- | --- |
| `dialysis` | haemodialysis is offered at this facility |
| `emergency_csection` | emergency caesarean sections are done here (obstetric operating theatre) |
| `nicu` | a neonatal intensive care unit, or a special newborn care unit (SNCU) |
| `cardiac_surgery` | open-heart or cardiac surgery (bypass/CABG, valve) is done here; a cath lab alone is not enough |
| `mri` | an MRI scanner is on site. MRI listed as outsourced or sent to another centre does **not** count: the rubric asks for a scanner on site, and the agent marked such a page contradicted |
| `burn_care` | a burn unit or ward, or burns treated as a service. Hair restoration or cosmetic scar work after burns is **not** burn care |
| `trauma_care` | a trauma centre, or a 24x7 emergency that takes accident and injury cases |
| `emergency_24x7` | an emergency department open 24 hours |
| `stemi_thrombolysis` | treats heart attacks (clot-busting thrombolysis or primary angioplasty) |

## For each row

1. Read `facility`, `place`, `service` and `service_means`.
2. Open the link(s) in `evidence_urls`. Check the page is about this facility (name **and** place).
   - **If there is no quote, read the whole page** (and its services or departments page, if it has one).
   - **If there is no link** (row 14, on Aarav's sheet), search the facility name and district (or city). **Record the URL you
     used** in `url_used`.
   - If you decide from any page that is not in `evidence_urls`, put it in `url_used`.
3. Decide, using the rules below, and write `confirmed`, `contradicted` or `cannot_tell` in `human_verdict`.
4. Only then look at `quote`. If it changes your mind, say so in `note`.

Use at most about 3 web searches per row. Do not add personal details about doctors or patients to `note`.

## Rules

The verdicts follow the rubric the agents used:

> **confirmed:** the facility's own site, a government list or scheme page, or a reputable page with
> facility-specific detail that is not a copy of a directory listing, dated within about 5 years;
> **contradicted:** credible evidence it does not offer it, an unrelated single-specialty facility (eye, dental,
> skin clinic ...), closed, the claim belongs to another facility, or an exhaustive official list omits it;
> **no_info:** neither. ... Do not guess. If you cannot decide, it is no_info with low confidence.

On this sheet `no_info` is called `cannot_tell`.

### When the page does not mention the service

Silence alone is **`cannot_tell`**. A home page, a single department page, or a news item that does not mention
the service does not show the facility lacks it.

Silence counts as **`contradicted`** only in one of two cases:

- **The facility is a different kind of place** for this service: an unrelated single-specialty or single-system
  facility. Examples: an Ayurvedic or homoeopathic college asked about trauma or emergency care; a children's
  clinic or hospital asked about heart-attack care; a women's hospital asked about burns; a hair or skin clinic
  asked about burns. This holds even if the place has a 24/7 emergency: a children's hospital's 24/7 emergency
  does not make it a heart-attack service.
- **The facility's own full list omits it**: a page that sets out all its services or all its departments (the
  rubric's "exhaustive official list"), and the service is not on it. A partial list ("some of our services",
  "highlights") is not exhaustive: that is `cannot_tell`.

### Dead, parked or spam pages

- A link that is dead, parked, for sale, or now a gambling, adult or other unrelated site is **not evidence
  either way**. It does not mean the facility closed.
- Search the facility name and district (or city) for its current own site, a government or scheme list
  (PM-JAY, state health department, NHM) or reputable news. Record what you used in `url_used`.
- Directory listings (Justdial, Practo-style) can show the facility exists, or what kind of place it is, but
  can never confirm a service.
- If nothing usable turns up, mark `cannot_tell` and write "dead link" or "spam page" in `note`.
- Mark `contradicted` for "closed" only if a page says the facility has closed or merged.

## When you are done

1. Check every row has `human_verdict` filled in.
2. Save as **CSV UTF-8**, named after yourself: `karthik.csv`, `aayan.csv` or `aarav.csv`.
3. Put it at **`model/gold/v3/human_check/filled/<name>.csv`** (for example `filled/aayan.csv`). If you are not
   working in the repo, **post the filled file on #103, or give it to the project owner**, who will put it there.

## Scoring (project owner)

```
.venv-app/bin/python model/gold/v3/human_check/score.py [filled/karthik.csv ...] [--out result.json]
    [--answers agent_answers.csv] [--partial]
```

With no paths it reads `filled/karthik.csv`, `filled/aayan.csv` and `filled/aarav.csv`, and writes `result.json`
in this folder. The person is taken from the file name. `score.py` joins `agent_answers.csv` on `pair_id`, reads
Excel's CSV UTF-8 (with a byte-order mark), skips blank rows and accepts verdicts in any case. It refuses missing
pairs unless `--partial` is given. `result.json` has:

- agreement with the agent on the rows people could decide, with a 95% interval, overall and per person;
- agreement for confirmed and contradicted separately, and by split;
- the count of `cannot_tell` rows, overall and per person.

With 25 rows the interval will be wide (about plus or minus 15 points), and per person (8 or 9 rows) wider
still. That is expected: the point is a real human check, not a precise rate. Commit the three filled files and
`result.json` together.

Across all 194 decided labels, 3 have no link: row 14 (confirmed from a search-result snippet whose page did not
open) and two contradictions made from the facility's name alone.

`build_sheet.py` refuses to overwrite the sheets. `--force` rewrites them, with the same seed, the same 25 rows
and the same split, only while no verdict, URL or note has been entered in any of them.
