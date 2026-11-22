"""Shared chart style for the datathon visualizations.

Import this in every chart script so all figures read as one system:

    import sys; sys.path.insert(0, "/Users/karthikvattem/projects/datathon/viz")
    import style as S
    fig, ax = S.new_figure()
    ...
    S.finding_title(ax, "Bihar has 260 records for 130 million people")
    S.save(fig, "/path/out/bihar_records", alt_text="...")

Palette values come from the dataviz skill's reference instance
(references/palette.md). Every set below was run through the skill's
scripts/validate_palette.js; results are recorded next to each set and in
viz/README.md. Charts are static and light-surface only (slides, report), so
only the light steps are used.
"""
from __future__ import annotations

import math
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

# ---------------------------------------------------------------- ink, surface
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
NEUTRAL = "#f0efec"

# ---------------------------------------------------------------- categorical
# Fixed order, never cycled. validate_palette.js --mode light, adjacent pairs:
# worst CVD dE 9.1, normal-vision 19.6 (reference values). Under --pairs all
# (scatter, maps, small multiples) only the first three validate (worst CVD 9.2,
# normal 24.0, run here): cap point/map charts at 3 colours, fold the rest.
CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
               "#e87ba4", "#008300", "#6250d6", "#e34948"]
CATEGORICAL_ALL_PAIRS_MAX = 3
OTHER = "#b4b3ad"  # folded tail ("Other"), neutral on purpose

# ---------------------------------------------------------------- sequential
# One hue (blue), light -> dark. For ordinal marks start at step 250.
SEQUENTIAL = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
              "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281",
              "#0d366b"]
SEQUENTIAL_ORDINAL = SEQUENTIAL[3:]
SEQUENTIAL_2 = ["#fde3d6", "#f9c4ab", "#f4a27f", "#eb6834", "#c4501f", "#9a3c14"]  # second context (orange)

# ---------------------------------------------------------------- diverging
# blue <-> red with a gray midpoint, equal arms.
DIVERGING = ["#104281", "#2a78d6", "#86b6ef", NEUTRAL, "#f2a3a2", "#e34948", "#a32a2a"]

# ---------------------------------------------------------------- semantic
# Evidence states for facility x service claims. Ordered strongest -> weakest
# (blue = confirmed, gray = no evidence either way, red = evidence against)
# plus yellow for a data-quality flag. validate_palette.js --mode light
# --pairs all: CVD worst dE 13.8 (protan, likely vs not_verified), normal-vision
# worst 15.5 (flagged vs not_verified), both PASS. Chroma floor FAILS for
# not_verified only, by design: it is the neutral "no evidence" state and must
# read as gray. Contrast: likely, not_verified and flagged sit below 3:1, so
# always label these marks directly (text in INK) or ship a table.
SEMANTIC = {
    "verified": "#184f95",
    "likely": "#6da7ec",
    "not_verified": "#c3c2b7",
    "unlikely": "#e34948",
    "flagged": "#eda100",
}
SEMANTIC_LABELS = {
    "verified": "Verified", "likely": "Likely", "not_verified": "Not verified",
    "unlikely": "Unlikely", "flagged": "Flagged",
}
# Text placed inside a filled mark: white except on the light fills.
ON_FILL = {"verified": "#ffffff", "likely": INK, "not_verified": INK,
           "unlikely": "#ffffff", "flagged": INK}

# ---------------------------------------------------------------- rcParams
SLIDE_SIZE = (12, 6.75)   # 16:9 at slide width
REPORT_SIZE = (8, 5)
SMALL_N = 30              # below this, a rate gets a small-n warning

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
    "font.size": 13,
    "axes.titlesize": 17,
    "axes.titleweight": "bold",
    "axes.titlelocation": "left",
    "axes.titlepad": 14,
    "axes.labelsize": 13,
    "axes.labelcolor": INK_2,
    "axes.edgecolor": AXIS,
    "axes.linewidth": 0.8,
    "axes.facecolor": SURFACE,
    "axes.grid": True,
    "axes.axisbelow": True,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.prop_cycle": matplotlib.cycler(color=CATEGORICAL),
    "grid.color": GRID,
    "grid.linewidth": 0.6,
    "grid.linestyle": "-",
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "xtick.labelcolor": INK_2,
    "ytick.labelcolor": INK_2,
    "xtick.labelsize": 11.5,
    "ytick.labelsize": 11.5,
    "legend.frameon": False,
    "legend.fontsize": 11.5,
    "figure.facecolor": SURFACE,
    "figure.dpi": 100,
    "savefig.facecolor": SURFACE,
    "lines.linewidth": 2,
    "lines.markersize": 8,
    "patch.linewidth": 0,
    "svg.fonttype": "none",
    "text.color": INK,
})


# ---------------------------------------------------------------- helpers
def new_figure(size=SLIDE_SIZE, nrows=1, ncols=1, **kw):
    """Return (fig, ax) on the shared surface. ax is an array when nrows*ncols > 1."""
    fig, ax = plt.subplots(nrows, ncols, figsize=size, constrained_layout=True, **kw)
    return fig, ax


def finding_title(ax, text, subtitle=None, wrap=70):
    """Headline title that states the finding; optional gray subtitle (n, source)."""
    text = textwrap.fill(text, wrap)
    ax.set_title(text, loc="left", color=INK, pad=30 if subtitle else 14)
    if subtitle:
        ax.text(0, 1.02, subtitle, transform=ax.transAxes, ha="left", va="bottom",
                fontsize=12, color=INK_2)


def fig_title(fig, text, wrap=95):
    """Figure-level headline for multi-panel charts (left-aligned, laid out by constrained_layout).

    Put the n / source subtitle on each panel with panel_title().
    """
    return fig.suptitle(textwrap.fill(text, wrap), x=0.01, ha="left", fontsize=17,
                        fontweight="bold", color=INK)


def panel_title(ax, text):
    """Regular-weight panel heading under a fig_title (states what the panel shows, with n)."""
    ax.set_title(text, loc="left", fontsize=13, fontweight="normal", color=INK_2)


def source_note(fig, text):
    """Bottom-left source / method line in muted ink; reserved space via supxlabel."""
    fig.supxlabel(text, x=0.01, ha="left", fontsize=9.5, color=MUTED)


def label_bars(ax, bars, labels=None, fmt="{:,.0f}", inside=False, horizontal=False,
               fontsize=11):
    """Value labels at bar ends, in text ink (never the series colour).

    Pass horizontal=True for ax.barh bars. labels overrides fmt per bar.
    """
    for i, b in enumerate(bars):
        v = b.get_width() if horizontal else b.get_height()
        s = labels[i] if labels is not None else fmt.format(v)
        ink = "#ffffff" if inside else INK
        if horizontal:
            ax.annotate(s, (b.get_x() + v, b.get_y() + b.get_height() / 2),
                        xytext=(-4 if inside else 4, 0), textcoords="offset points",
                        ha="right" if inside else "left", va="center", fontsize=fontsize, color=ink)
        else:
            ax.annotate(s, (b.get_x() + b.get_width() / 2, b.get_y() + v),
                        xytext=(0, -4 if inside else 3), textcoords="offset points",
                        ha="center", va="top" if inside else "bottom", fontsize=fontsize, color=ink)


def bar_style():
    """kwargs for thin bars with a 2px surface gap between neighbours."""
    return dict(edgecolor=SURFACE, linewidth=2)


def wilson(k, n, z=1.96):
    """Wilson 95% interval for k successes in n. Returns (p, lo, hi); nan when n == 0."""
    if n == 0:
        return (math.nan, math.nan, math.nan)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, c - h), min(1.0, c + h))


def add_interval(ax, pos, lo, hi, horizontal=False, color=INK_2, cap=4, lw=1.4):
    """Draw 95% interval whiskers at positions `pos` (arrays or scalars)."""
    pos, lo, hi = map(np.atleast_1d, (pos, lo, hi))
    mid = (lo + hi) / 2
    err = np.vstack([mid - lo, hi - mid])
    if horizontal:
        ax.errorbar(mid, pos, xerr=err, fmt="none", ecolor=color, elinewidth=lw, capsize=cap, zorder=3)
    else:
        ax.errorbar(pos, mid, yerr=err, fmt="none", ecolor=color, elinewidth=lw, capsize=cap, zorder=3)


def small_n_note(ax, n, threshold=SMALL_N, where=(0.99, 0.02), text=None):
    """Mark an axes whose estimate rests on fewer than `threshold` items. Returns True if drawn."""
    if n >= threshold:
        return False
    ax.text(*where, text or f"Small sample: n = {n} (< {threshold}); read the interval, not the point",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=10.5, color=INK_2,
            style="italic", bbox=dict(boxstyle="round,pad=0.3", fc=NEUTRAL, ec="none"))
    return True


def n_label(n, denom=None):
    """'n = 1,234' or '1,234 of 9,959 (12.4%)'."""
    if denom is None:
        return f"n = {n:,}"
    return f"{n:,} of {denom:,} ({100 * n / denom:.1f}%)" if denom else f"{n:,} of 0"


def save(fig, path_without_ext, alt_text):
    """Write <path>.png (2x), <path>.svg and <path>.txt (alt text). Returns the PNG path."""
    if not alt_text or not alt_text.strip():
        raise ValueError("alt_text is required: describe the finding, not the chart type")
    p = Path(path_without_ext)
    p.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(p.with_suffix(".png"), dpi=200)
    fig.savefig(p.with_suffix(".svg"))
    p.with_suffix(".txt").write_text(alt_text.strip() + "\n", encoding="ascii")
    plt.close(fig)
    return p.with_suffix(".png")


# ---------------------------------------------------------------- India point map
# Rough bounding box of the data, used only to frame the axes. No boundaries of
# any kind are drawn: India's external boundary must follow Survey of India, and
# unofficial outlines are not allowed on our charts.
INDIA_EXTENT = (68.0, 97.5, 6.5, 37.5)  # lon_min, lon_max, lat_min, lat_max


def india_point_map(ax, lon, lat, values=None, kind="scatter", color=CATEGORICAL[0],
                    s=6, alpha=0.6, gridsize=45, cmap=None, label=None, scale_note=True,
                    **kw):
    """Plot points (or a hexbin) of lat/lon on a plain background, no outlines.

    kind="scatter": dots; `values` (optional) maps to the sequential ramp.
    kind="hexbin": counts per hex (or mean of `values` per hex).
    Uses an equirectangular frame with aspect corrected at ~22N so distances
    look right; adds a scale bar and a "no boundaries drawn" note.
    Returns the mappable (for a colorbar) or the scatter collection.
    """
    from matplotlib.colors import LinearSegmentedColormap
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    ok = np.isfinite(lon) & np.isfinite(lat)
    cmap = cmap or LinearSegmentedColormap.from_list("seq", SEQUENTIAL)
    if kind == "hexbin":
        m = ax.hexbin(lon[ok], lat[ok], C=None if values is None else np.asarray(values)[ok],
                      gridsize=gridsize, cmap=cmap, mincnt=1, linewidths=0.2,
                      edgecolors=SURFACE, extent=INDIA_EXTENT, **kw)
    elif values is not None:
        m = ax.scatter(lon[ok], lat[ok], c=np.asarray(values)[ok], cmap=cmap, s=s, alpha=alpha,
                       linewidths=0, label=label, **kw)
    else:
        m = ax.scatter(lon[ok], lat[ok], color=color, s=s, alpha=alpha, linewidths=0,
                       label=label, **kw)
    ax.set_xlim(INDIA_EXTENT[0], INDIA_EXTENT[1])
    ax.set_ylim(INDIA_EXTENT[2], INDIA_EXTENT[3])
    ax.set_aspect(1 / math.cos(math.radians(22)))
    ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_xticks([])
    ax.set_yticks([])
    if scale_note:
        # 500 km bar at 10N: 1 deg lon = 111.32 * cos(lat) km
        deg = 500 / (111.32 * math.cos(math.radians(10)))
        x0, y0 = 70.0, 8.0
        ax.plot([x0, x0 + deg], [y0, y0], color=INK_2, lw=2, solid_capstyle="butt")
        ax.text(x0 + deg / 2, y0 + 0.4, "500 km", ha="center", va="bottom", fontsize=10, color=INK_2)
        ax.text(0.99, 0.99, "Points only; no boundaries drawn.\nScale bar approximate.",
                transform=ax.transAxes, ha="right", va="top", fontsize=9.5, color=MUTED)
    return m


if __name__ == "__main__":
    # self-check: interval maths and save contract
    p, lo, hi = wilson(30, 33)
    assert abs(p - 0.909) < 1e-3 and 0.75 < lo < 0.77 and 0.96 < hi < 0.98, (p, lo, hi)
    assert math.isnan(wilson(0, 0)[0])
    try:
        save(plt.figure(), Path(__file__).parent / "_demo" / "never_written", "")
    except ValueError:
        pass
    else:
        raise AssertionError("save must require alt text")
    print("style.py self-check OK")
