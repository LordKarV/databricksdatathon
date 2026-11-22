# Human spot-check of the gold v3 labels (issue #103)

The gold v3 labels were made by AI agents reading public web pages. Nobody has yet checked them by hand. This
check asks one person to read the cited pages for 25 labels and say whether the agent got it right. The result is
the project's only human-checked accuracy figure for its labels.

## What you need

- `sheet.csv`: 25 rows. Open it in any spreadsheet program, and save it as CSV (UTF-8) when you are done.
- About 1 to 2 minutes per row: about 45 minutes in all.

## The 25 rows

- Drawn at random (`build_sheet.py`, seed 20261122): 15 the agent marked **confirmed** and 10 it marked
  **contradicted**.
- They come from both splits in proportion: 17 DEV and 8 TEST.
- Only "decided" labels are included. A "no information" verdict cannot be checked against a page.

## For each row

1. Read `facility`, `place` and `service`. (`emergency_24x7` means a round-the-clock emergency department;
   `stemi_thrombolysis` means clot-busting treatment for a heart attack.)
2. Open the link(s) in `evidence_urls`. Look for the `quote` on the page. If a page is dead, you may search the
   facility's name once.
3. Decide on your own, **before you look at `agent_verdict`** (you can hide that column):
   - **confirmed:** the page (the facility's own site, a government list, or a page with facility-specific detail)
     says this facility offers this service.
   - **contradicted:** the page says it does not, or the facility is a different kind of place altogether (for
     example a dental or eye clinic asked about heart surgery), or it is closed, or the claim belongs to another
     facility.
   - **cannot_tell:** the pages do not settle it either way, or none of them open.
4. Write your verdict in `human_verdict`, exactly `confirmed`, `contradicted` or `cannot_tell`. Use `note` for
   anything useful, such as "page moved" or "quote is about a different branch".

Row 14 has no link. The agent confirmed it from a search-result snippet whose page did not open. Search for it
once; if you cannot find the evidence, mark it `cannot_tell`. Across all 194 decided labels, 3 have no link: this
one, and two contradictions made from the facility's name alone.

Do not add personal details about doctors or patients to `note`.

## When you are done

```
.venv-app/bin/python model/gold/v3/human_check/score.py
```

This writes `result.json`:

- agreement with the agent on the rows you could decide, with a 95% interval;
- agreement for confirmed and contradicted separately;
- the count of `cannot_tell` rows.

With 25 rows the interval will be wide (about plus or minus 15 points). That is expected: the point is a real
human check, not a precise rate. Commit the filled `sheet.csv` and `result.json` together.

`build_sheet.py` refuses to overwrite `sheet.csv`, so the draw cannot be changed once someone has started.
