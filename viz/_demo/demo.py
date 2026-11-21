"""Demo chart proving viz/style.py works end to end.

Input: data/raw/facilities.parquet (read only). Output: viz/_demo/demo.{png,svg,txt}.
Run: .venv-viz/bin/python viz/_demo/demo.py
"""
import sys
from pathlib import Path

import duckdb
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "viz"))
import style as S  # noqa: E402

SRC = ROOT / "data/raw/facilities.parquet"
df = duckdb.sql(f"""
    select address_stateOrRegion as state, latitude, longitude,
           coalesce(contains(trim(officialWebsite), '.'), false) as has_site  -- 'null', 'true', '' are not websites
    from '{SRC}'
""").df()
n_all = len(df)
top = df["state"].value_counts().head(8)
rows = []
for st, n in top.items():
    k = int(df.loc[df.state == st, "has_site"].sum())
    p, lo, hi = S.wilson(k, int(n))
    rows.append((st, k, int(n), p, lo, hi))
rows.sort(key=lambda r: r[3])

fig = S.plt.figure(figsize=S.SLIDE_SIZE, constrained_layout=True)
gs = fig.add_gridspec(1, 2, width_ratios=[1.25, 1])
ax, mx = fig.add_subplot(gs[0]), fig.add_subplot(gs[1])

y = np.arange(len(rows))
pct = np.array([r[3] for r in rows]) * 100
bars = ax.barh(y, pct, color=S.CATEGORICAL[0], height=0.62, **S.bar_style())
S.add_interval(ax, y, [r[4] * 100 for r in rows], [r[5] * 100 for r in rows], horizontal=True)
ax.set_yticks(y, [f"{r[0]}  (n = {r[2]:,})" for r in rows])
ax.set_xlim(0, 100)
ax.set_xlabel("Records with an official website (%, 95% Wilson interval)")
ax.grid(axis="y", visible=False)
for yi, r in zip(y, rows):
    ax.annotate(f"{r[3]*100:.0f}%  ({r[1]:,}/{r[2]:,})", (r[5] * 100, yi), xytext=(6, 0),
                textcoords="offset points", va="center", fontsize=11, color=S.INK)
lo_st, hi_st = rows[0], rows[-1]
S.fig_title(fig, f"Kerala leads on listed websites at {hi_st[3]*100:.0f}%; the other 7 largest states "
                 f"sit between {lo_st[3]*100:.0f}% and {rows[-2][3]*100:.0f}%")
S.panel_title(ax, f"8 states with the most records ({n_all:,} records in file). Style demo, not an analysis")

ok = df.latitude.between(6, 38) & df.longitude.between(68, 98)
hb = S.india_point_map(mx, df.longitude[ok], df.latitude[ok], kind="hexbin", gridsize=40)
fig.colorbar(hb, ax=mx, shrink=0.45, label="Records per hexagon")
S.panel_title(mx, f"Where the {int(ok.sum()):,} records with in-range coordinates sit")
S.source_note(fig, "Source: data/raw/facilities.parquet (raw, uncleaned; state names as given). "
                   "Map: hexbin counts, lat/lon frame, no boundaries.")

alt = (f"Left: horizontal bars of the share of facility records with an official website for the 8 "
       f"states with the most records, from {lo_st[0]} at {lo_st[3]*100:.0f}% ({lo_st[1]} of {lo_st[2]}) "
       f"to {hi_st[0]} at {hi_st[3]*100:.0f}% ({hi_st[1]} of {hi_st[2]}), with 95% Wilson intervals. "
       f"Right: hexbin density of {int(ok.sum())} records with in-range coordinates over India, no boundaries drawn. "
       f"Raw file, {n_all} records. This is a style demo, not an analysis.")
out = S.save(fig, ROOT / "viz/_demo/demo", alt)
for r in rows:
    print(r[0], r[1], r[2], round(r[3], 3), round(r[4], 3), round(r[5], 3))
print(out)
