# Shared chart style

`viz/style.py` is the one style every chart in this project uses, so the figures read as one
system on slides, in the report and in the Bharosa app. `_demo/demo.py` is a working example.

## Environment

Python: `/Users/karthikvattem/projects/datathon/.venv-viz/bin/python` (Python 3.12, made with uv).
Installed: matplotlib 3.11.2, pandas 3.1.1, pyarrow 26.0.1, duckdb 2.0.1, numpy 2.5.5, scipy 1.18.1,
scikit-learn 1.9.1, statsmodels 0.15.0, interpret 0.7.8 (EBMs), rapidfuzz 3.14.6, geopandas 1.2.0,
shapely 2.2.0, rasterio 1.5.2, plotly 7.1.0, kaleido 1.5.2 (static plotly export checked: works).
Only the Style step installs into this venv.

## Usage

```python
import sys; sys.path.insert(0, "/Users/karthikvattem/projects/datathon/viz")
import style as S

fig, ax = S.new_figure()                        # 12 x 6.75 in (16:9); S.REPORT_SIZE for 8 x 5
p, lo, hi = S.wilson(30, 33)                    # rate with 95% Wilson interval
bars = ax.barh([0], [p * 100], color=S.CATEGORICAL[0], **S.bar_style())
S.add_interval(ax, [0], [lo * 100], [hi * 100], horizontal=True)
S.label_bars(ax, bars, labels=[S.n_label(30, 33)], horizontal=True)
S.small_n_note(ax, 33)                          # draws a note when n < 30, returns True if drawn
S.finding_title(ax, "Location scores of 0.7 or more were right 30 times in 33")
ax.set_xlabel("Confirmed (%, 95% Wilson interval)")
S.source_note(fig, "Source: model/review/stats/results.json")
S.save(fig, "/abs/path/out/location_check", alt_text="...")   # writes .png (2x), .svg, .txt
```

Multi-panel figures: `S.fig_title(fig, headline)` plus `S.panel_title(ax, "what this panel shows, n = ...")`.
Maps: `S.india_point_map(ax, lon, lat, kind="scatter" | "hexbin", values=None)` draws points or hexagons
on a plain background with a 500 km scale bar and a "no boundaries drawn" note; add a colorbar for
hexbins (`fig.colorbar(m, ax=ax, label="Records per hexagon")`). Pass `bins="log"` through to hexbin
when a few city hexes swamp the scale.

Run `python viz/style.py` for its self-check (Wilson maths, alt text required).

## Palette

All values come from the dataviz skill's validated reference palette, light surface `#fcfcfb`.
Results below are from its `scripts/validate_palette.js`, run on 2026-11-21.

| Token | Use | Validation |
|---|---|---|
| `CATEGORICAL` (8, fixed order) | identity: states, sources, services | adjacent pairs: worst CVD dE 9.1, normal 19.6 (reference). All pairs, first 3 only: CVD 9.2, normal 24.0, PASS (run here) |
| `SEQUENTIAL` (blue, 13 steps) | magnitude, hexbin counts | one hue light to dark; ordinal marks use `SEQUENTIAL_ORDINAL` (step 250 up) |
| `SEQUENTIAL_2` (orange) | a second magnitude on the same page | |
| `DIVERGING` (blue / gray / red) | signed differences, model contributions | gray midpoint means zero |
| `SEMANTIC` | evidence states | see below |
| `OTHER` | folded tail | neutral gray |

Semantic set, strongest to weakest evidence: `verified #184f95`, `likely #6da7ec`,
`not_verified #c3c2b7`, `unlikely #e34948`, plus `flagged #eda100` for data-quality flags.
`--pairs all`: CVD worst dE 13.8 (likely vs not_verified, protan), normal-vision worst 15.5
(flagged vs not_verified), both PASS. The chroma check fails for `not_verified` only, on purpose: the
"no evidence" state must read as gray. Three of the five fall below 3:1 contrast, so always label
semantic marks directly in text ink or ship a table. Use `ON_FILL[state]` for text inside a fill.

Do not reuse semantic colours for ordinary series, and do not put more than three categorical colours
on a scatter, map or small multiple (fold the rest into `OTHER`).

## Chart rules (from the project brief)

- Title states the finding as a sentence with a number ("Kerala leads at 93%"), not the chart type.
- Axes labelled with units. Bars start at zero. No dual axes.
- Show the denominator and n on the chart (`n_label`, tick labels like "Bihar (n = 260)").
- Every rate or estimate carries a 95% interval (`wilson`, `add_interval`); n below 30 gets
  `small_n_note`.
- Colour-blind-safe tokens only; direct labels over legends where possible; text in ink, never in the
  series colour.
- Every chart is saved with `save()`, which requires alt text. The alt text states the finding and the
  key numbers.
- Maps of India: never draw national or state outlines from unofficial sources (see
  `external/lgd_district_polygons/README.md`). Use `india_point_map`, district-centroid dots, ranked
  bars or tile grids. District polygons are for internal aggregation only.
- Never compute anything new on the gold TEST split (`model/gold/splits.json`); quote published
  results from `model/review/stats/results.json` and `model/MODEL_SPEC.md`.
- Every number comes from a saved script you ran; cite the input file on the chart (`source_note`).
  Write "not run" rather than guess.
- Prose on charts and in alt text: plain ASCII, no em dashes, sentence case, specific numbers.
