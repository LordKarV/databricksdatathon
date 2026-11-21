"""Story 3: three real plans drawn as itineraries (points and straight connectors, no outlines).

Input: data/plans_raw.json.gz (scripts/run_plans.py), derived/v1/claims.parquet (evidence text),
derived/v1/facility_location.parquet (context dots). Output: charts/s3_itineraries.*, data/s3_itineraries.csv.
Connectors are straight lines between points, not road routes; minutes are geo.travel estimates.
"""
import gzip
import json
import math
import textwrap

import pandas as pd

from common import CHARTS, DATA, PATHWAY_LABEL, ROOT, STUB_NOTE, S, note

PICKS = [("q05", "major_trauma"), ("q22", "obstetric_emergency"), ("q20", "dialysis_start")]
PURPOSE = {"stabilise": "Stabilise", "definitive": "Definitive care", "assess": "Assessment",
           "access": "Fistula surgery", "recurring": "Dialysis sessions"}
COLOR = {"origin": S.INK, "stabilise": S.CATEGORICAL[1], "assess": S.CATEGORICAL[1], "access": S.CATEGORICAL[1],
         "definitive": S.CATEGORICAL[0], "recurring": S.CATEGORICAL[0]}


def load():
    d = json.load(gzip.open(DATA / "plans_raw.json.gz", "rt"))
    runs = {(r["origin"]["origin_id"], r["pathway"]): r for r in d["runs"]}
    claims = pd.read_parquet(ROOT / "derived/v1/claims.parquet", columns=["claim_id", "text"]).set_index("claim_id").text
    fac = pd.read_parquet(ROOT / "derived/v1/facility_location.parquet", columns=["loc_lat", "loc_lon"]).dropna()
    return runs, claims, fac


def rows_for(run, claims):
    o = run["origin"]
    b = run["result"]["plans"][0]
    out = [{"query_id": o["origin_id"], "pathway": run["pathway"], "step": 0, "role": "origin", "name": o["label"],
            "lat": o["lat"], "lon": o["lon"], "eta": 0, "eta_low": 0, "eta_high": 0, "p": None, "km": 0,
            "evidence_id": None, "evidence": None, "flags": None}]
    seen = []
    for i, s in enumerate(b["stops"], 1):
        evs = sorted((e for e in s["evidence_ids"][:4] if e in claims.index), key=lambda e: len(claims[e]))[:2]  # 2 shortest of the first 4 the planner cited
        ev = evs[0] if evs else None
        out.append({"query_id": o["origin_id"], "pathway": run["pathway"], "step": i, "role": s["purpose"],
                    "name": s["name"], "lat": s["lat"], "lon": s["lon"], "eta": s["eta_minutes"],
                    "eta_low": s["eta_low"], "eta_high": s["eta_high"], "p": s["p"], "km": s["leg"]["km"],
                    "evidence_id": " | ".join(evs) or None,
                    "evidence": " | ".join(claims[e] for e in evs) or None,
                    "flags": "; ".join(s["flags"]) or None, "same_site_as_previous": s["facility_id"] in seen,
                    "per_week": s.get("per_week")})
        seen.append(s["facility_id"])
    return out, b


def draw(ax, tx, rows, b, fac, pathway):
    pts = [(r["lat"], r["lon"]) for r in rows]
    lat0 = sum(p[0] for p in pts) / len(pts)
    k = 1 / math.cos(math.radians(lat0))
    la = [p[0] for p in pts]
    lo = [p[1] for p in pts]
    half = max(max(la) - min(la), (max(lo) - min(lo)) / k, 0.6) / 2 * 1.3  # square frame in km
    cy, cx = (max(la) + min(la)) / 2, (max(lo) + min(lo)) / 2
    y0, y1 = cy - half, cy + half
    x0, x1 = cx - half * k, cx + half * k
    f = fac[fac.loc_lat.between(y0, y1) & fac.loc_lon.between(x0, x1)]
    ax.scatter(f.loc_lon, f.loc_lat, s=7, color=S.AXIS, lw=0, zorder=1)
    # connectors: origin -> each distinct site in order (repeat visits drawn once)
    prev = rows[0]
    links = []  # drawn connectors, used to keep labels off the lines
    for r in rows[1:]:
        if r.get("same_site_as_previous"):
            continue
        if pathway == "dialysis_start":  # scheduled stages are separate trips from home
            prev = rows[0]
        links.append((prev, r))
        ax.annotate("", (r["lon"], r["lat"]), (prev["lon"], prev["lat"]),
                    arrowprops=dict(arrowstyle="-|>", color=S.INK_2, lw=1.6, shrinkA=7, shrinkB=7,
                                    mutation_scale=14), zorder=2)
        prev = r
    ax.scatter(rows[0]["lon"], rows[0]["lat"], marker="*", s=260, color=S.INK, edgecolor=S.SURFACE, lw=1.5, zorder=5)
    for r in rows[1:]:
        ax.scatter(r["lon"], r["lat"], s=120, color=COLOR[r["role"]], edgecolor=S.SURFACE, lw=2, zorder=5)
    labelled = set()
    for i, r in enumerate(rows):
        key = (round(r["lat"], 4), round(r["lon"], 4))
        if key in labelled:
            continue
        labelled.add(key)
        name = textwrap.shorten(r["name"].split(",")[0], 34, placeholder="...")
        txt = "Start" if i == 0 else f"{i}. {name}"
        right = i == 0 or r["lon"] > (x0 + x1) / 2 + (x1 - x0) * 0.15
        near_origin = i > 0 and abs(r["lat"] - rows[0]["lat"]) + abs(r["lon"] - rows[0]["lon"]) < 0.12
        # label sits above or below the point, on the side away from the connector it extends towards
        nb = [b if a is r else a for a, b in links if a is r or b is r]
        side = [q for q in nb if (q["lon"] < r["lon"]) == right] or nb
        up = all(q["lat"] < r["lat"] for q in side) if side else bool(i % 2)
        off = (-10, -16) if i == 0 else (9, -16) if near_origin else (-9 if right else 9, 7 if up else -16)
        right = right and not near_origin
        ax.annotate(txt, (r["lon"], r["lat"]), xytext=off,
                    textcoords="offset points", ha="right" if right else "left", fontsize=10, color=S.INK, fontweight="bold" if i == 0 else "normal", zorder=6,
                    bbox=dict(fc=S.SURFACE, ec="none", alpha=0.85, pad=0.5))
    # scale bar
    km = 25 if (y1 - y0) * 111 < 160 else 50
    deg = km / (111.32 * math.cos(math.radians(lat0)))
    sx, sy = x0 + (x1 - x0) * 0.05, y0 + (y1 - y0) * 0.05
    ax.plot([sx, sx + deg], [sy, sy], color=S.INK_2, lw=2)
    ax.text(sx + deg / 2, sy + (y1 - y0) * 0.015, f"{km} km", ha="center", va="bottom", fontsize=9.5, color=S.INK_2)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect(k)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)
    for sp in ax.spines.values():
        sp.set_color(S.GRID)
    # text block: timeline with evidence
    tx.axis("off")
    lines = []
    for i, r in enumerate(rows[1:], 1):
        rep = f", {r['per_week']}x a week" if r.get("per_week") else ""
        head = (f"{i}. {PURPOSE.get(r['role'], r['role'])}: arrive {r['eta']} min ({r['eta_low']} to {r['eta_high']}), "
                f"{r['km']:.1f} km{rep}; P = {r['p']:.2f}")
        lines.append(("h", head))
        for q, qid in zip((r["evidence"] or "").split(" | "), (r["evidence_id"] or "").split(" | ")):
            if q:
                lines.append(("q", textwrap.fill(f'"{textwrap.shorten(q, 80, placeholder="...")}" [{qid}]', 60)))
        if r["flags"]:
            lines.append(("f", textwrap.fill(r["flags"], 58)))
    t = b["totals"]
    if "p_objective" in t:
        lines.append(("s", textwrap.fill(f"Chance of first care in time {t['p_first_care']:.2f}; of care in time at both "
                                         f"steps {t['p_objective']:.2f}. {b['vs_direct']['text'] if b.get('vs_direct') else ''}", 58)))
    else:
        wk = t["travel_minutes_over_planning_weeks"] / 60 / t["planning_weeks"]
        lines.append(("s", textwrap.fill(f"{t['distinct_sites']} sites. Travel about {wk:.0f} hours a week for "
                                         f"sessions over {t['planning_weeks']} weeks; chance every stage is available "
                                         f"{t['p_all_stages']:.2f}.", 58)))
    y = 1.0
    for kind, s in lines:
        style = {"h": dict(color=S.INK, fontsize=9.8, fontweight="bold"), "q": dict(color=S.INK_2, fontsize=9.3, style="italic"),
                 "f": dict(color="#9a3c14", fontsize=9.3), "s": dict(color=S.INK, fontsize=9.6)}[kind]
        tx.text(0, y, s, transform=tx.transAxes, va="top", **style)
        y -= 0.05 * (s.count("\n") + 1) + 0.018


def main():
    runs, claims, fac = load()
    fig = S.plt.figure(figsize=(16, 10.5), constrained_layout=True)
    fig.get_layout_engine().set(rect=(0, 0, 1, 0.93))  # room for the two-line headline above fixed-aspect maps
    gs = fig.add_gridspec(2, 3, height_ratios=[1.25, 1])
    all_rows = []
    titles = []
    for j, key in enumerate(PICKS):
        run = runs[key]
        rows, b = rows_for(run, claims)
        all_rows += rows
        ax, tx = fig.add_subplot(gs[0, j]), fig.add_subplot(gs[1, j])
        draw(ax, tx, rows, b, fac, key[1])
        S.panel_title(ax, f"{PATHWAY_LABEL[key[1]]} from {run['origin']['label']} ({key[0]})")
        titles.append((key, rows, b))
    tr = titles[0]
    S.fig_title(fig, f"From Muzaffarpur, the trauma plan stabilises {tr[1][1]['km']:.1f} km away in "
                     f"{tr[1][1]['eta']} min, then rides {tr[1][2]['km']:.0f} km to Patna (arrival at {tr[1][2]['eta']} min); in Yavatmal, dialysis "
                     f"means {titles[2][1][-1]['km']:.0f} km each way, three times a week")
    note(fig, "Three best plans for benchmark queries (model/gold/queries.json). Star = origin; orange = stabilising or "
              "preparatory stop; blue = definitive or recurring site; gray dots = every facility record in frame "
              "(derived/v1/facility_location.parquet). Lines are straight connectors, not roads; dialysis stages are "
              "separate trips from home. Arrival times include the 30 min dwell at a stabilising stop. Quotes: the two shortest of the "
              "first four claim ids the planner cited (derived/v1/claims.parquet), so they need not cover the weakest capability. " + STUB_NOTE, width=210)
    pd.DataFrame(all_rows).to_csv(DATA / "s3_itineraries.csv", index=False)
    parts = []
    for key, rows, b in titles:
        parts.append(f"{PATHWAY_LABEL[key[1]]} from {rows[0]['name']}: " + "; then ".join(
            f"{PURPOSE.get(r['role'], r['role']).lower()} at {r['name'].split(',')[0]} (leg {r['km']:.1f} km, arrive at {r['eta']} min, P {r['p']:.2f})"
            for r in rows[1:]))
    alt = ("Three itinerary maps on a plain background with straight connectors and no boundaries. " + ". ".join(parts)
           + ". Each stop is annotated with the record sentence that supports it and any location-confidence flag. "
             "Probabilities are the derived/v1 stub.")
    S.save(fig, CHARTS / "s3_itineraries", alt)
    print(alt)


if __name__ == "__main__":
    main()
