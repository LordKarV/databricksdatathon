"""Story 2: the hospital that moved.

Charts
- s2_map: arrows from each record's own postcode centre to its listed coordinates,
  for every record whose coordinates sit more than 50 km from its postcode. Points
  only, no boundaries. Colour = the record's own text says it is located elsewhere.
- s2_distance: how far listed coordinates sit from the record's own postcode (bands),
  and the far-from-postcode rate for records whose text says "located in <elsewhere>"
  against all others (reproduces audit/merge/verify/v_missed.py: 723/1,367 vs 821/8,165).

Inputs: derived/v1/facility_location.parquet (cleaned distances, n = 9,869),
audit/merge/verify/out/rec.parquet, audit/merge/out/sentences_flagged.parquet,
audit/merge/out/sentence_decisions.parquet, data/raw/india_post_pincode_directory.parquet.
Run: .venv-viz/bin/python viz/trust/s2_moved.py
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

import trust_io as io
import style as S

LOC = re.compile(r"\b(located|situated|based in|address)\b", re.I)
FAR_KM = 50
LABELLED = {  # unique_id prefix -> short label; chosen from the largest movers with a readable story
    "b8a5401f": "Aravind Eye Hospital, 'Hyderabad'",
    "5189865c": "Gem Hospital, Bathinda",
    "7930b04c": "Prasanthi Hospital, Bhimavaram",
    "88bdcc68": "SMS Hospital, Jaipur",
}


def hav(a, b, c, d):
    a, b, c, d = map(np.radians, (a, b, c, d))
    return 6371 * 2 * np.arcsin(np.sqrt(np.sin((c - a) / 2) ** 2 + np.cos(a) * np.cos(c) * np.sin((d - b) / 2) ** 2))


def located_elsewhere():
    """Per record: does a quarantined sentence naming another state/district say 'located/situated/based in/address'?

    Same rule as audit/merge/verify/v_missed.py, recomputed here.
    """
    s = io.load("merge_sentences", ["unique_id", "field", "idx", "text", "has_other_state", "has_other_district"])
    d = io.load("merge_decisions", ["unique_id", "field", "idx", "quarantine"])
    s = s.merge(d, on=["unique_id", "field", "idx"])
    s["locelse"] = s.quarantine & (s.has_other_state | s.has_other_district) & s.text.map(lambda t: bool(LOC.search(t)))
    return s.groupby("unique_id").locelse.any()


def audit_distances(pin_dir):
    """Raw coordinates vs raw-directory PIN median, as in v_missed.py (n = 9,532 with both)."""
    rec = io.load("merge_rec", ["unique_id", "address_zipOrPostcode", "latitude", "longitude"]).set_index("unique_id")
    pc = pin_dir.groupby("pincode")[["la", "lo"]].median()
    z = pd.to_numeric(rec.address_zipOrPostcode.astype(str).str.extract(r"(\d{6})")[0], errors="coerce")
    j = pd.DataFrame({"z": z.values, "la": rec.latitude.values, "lo": rec.longitude.values}, index=rec.index)
    j = j.join(pc.add_suffix("_p"), on="z")
    j["km"] = hav(j.la, j.lo, j.la_p, j.lo_p)
    return j


def distance_chart(loc, j):
    km = loc.raw_coords_to_pin_km.dropna()
    n = len(km)
    edges = [0, 10, 25, 50, 100, 500, np.inf]
    labels = ["0-10", "10-25", "25-50", "50-100", "100-500", "500+"]
    b = pd.cut(km, edges, labels=labels, right=False).value_counts().reindex(labels)
    bands = pd.DataFrame({"band": labels, "k": b.values, "n": n})
    bands[["rate", "lo", "hi"]] = [S.wilson(int(k), n) for k in bands.k]
    far = int((km > FAR_KM).sum())

    ok = j.km.notna()
    grp = []
    for v, lab in [(True, "Own text says it is\nlocated elsewhere"), (False, "All other records")]:
        g = j[ok & (j.locelse == v)]
        k = int((g.km > FAR_KM).sum())
        grp.append(dict(group=lab.replace("\n", " "), label=lab, k=k, n=len(g), **dict(zip(["rate", "lo", "hi"], S.wilson(k, len(g))))))
    grp = pd.DataFrame(grp)

    fig = S.plt.figure(figsize=S.SLIDE_SIZE, constrained_layout=True)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.5, 1])
    a, c = fig.add_subplot(gs[0]), fig.add_subplot(gs[1])
    x = np.arange(len(bands))
    cols = [S.SEMANTIC["not_verified"]] * 3 + [S.SEMANTIC["unlikely"]] * 3
    bars = a.bar(x, bands.rate * 100, color=cols, width=0.66, **S.bar_style())
    S.add_interval(a, x, bands.lo * 100, bands.hi * 100)
    for xi, r in zip(x, bands.itertuples()):
        a.annotate(f"{r.rate * 100:.1f}%\n{int(r.k):,}", (xi, r.hi * 100), xytext=(0, 3), textcoords="offset points",
                   ha="center", va="bottom", fontsize=10.5, color=S.INK)
    a.set_xticks(x, labels)
    a.set_xlabel("Distance from listed coordinates to the centre of the record's own postcode (km)")
    a.set_ylabel(f"Share of records (%, n = {n:,})")
    a.set_ylim(0, 100)
    a.grid(axis="x", visible=False)
    a.axvline(2.5, color=S.MUTED, ls="--", lw=1)
    a.text(2.55, 60, f"{far:,} records ({far / n * 100:.1f}%)\nmore than {FAR_KM} km off", fontsize=11,
           color=S.INK, va="bottom")
    S.panel_title(a, f"All {n:,} records with coordinates and a postcode point (after postcode repairs)")

    xg = np.arange(len(grp))
    c.bar(xg, grp.rate * 100, color=[S.SEMANTIC["unlikely"], S.SEMANTIC["not_verified"]], width=0.6, **S.bar_style())
    S.add_interval(c, xg, grp.lo * 100, grp.hi * 100)
    for xi, r in zip(xg, grp.itertuples()):
        c.annotate(f"{r.rate * 100:.1f}%\n{r.k:,} of {r.n:,}", (xi, r.hi * 100), xytext=(0, 3),
                   textcoords="offset points", ha="center", va="bottom", fontsize=11, color=S.INK)
    c.set_xticks(xg, grp.label)
    c.set_ylim(0, 100)
    c.set_ylabel(f"Coordinates more than {FAR_KM} km from own postcode (%)")
    c.grid(axis="x", visible=False)
    S.panel_title(c, "Coordinates follow the contaminating facility")
    r0, r1 = grp.iloc[0], grp.iloc[1]
    S.fig_title(fig, f"1 record in {round(n / far)} has map coordinates more than {FAR_KM} km from its own postcode; "
                     f"when its text says it is located somewhere else, it is {r0.rate * 100:.0f}% "
                     f"({r0.rate / r1.rate:.1f} times the {r1.rate * 100:.0f}% rate)")
    io.note(fig, "Left: derived/v1/facility_location.parquet raw_coords_to_pin_km (cleaned postcode centres). Right: raw "
                 "coordinates against raw India Post postcode medians (audit/merge/verify/out/rec.parquet, as in "
                 "v_missed.py); 'located elsewhere' = a quarantined sentence that names another state or district and "
                 "says located / situated / based in / address (audit/merge/out/sentences_flagged.parquet). The two 1,367s "
                 "are a coincidence: one counts far records, the other records that say 'located elsewhere'.")
    io.write_csv(pd.concat([bands.assign(panel="distance_band", group=bands.band), grp.assign(panel="located_elsewhere")])
                 [["panel", "group", "k", "n", "rate", "lo", "hi"]], "s2_distance")
    alt = (f"Of {n:,} records with coordinates and a postcode point, {far:,} ({far / n * 100:.1f}%) place the map pin "
           f"more than {FAR_KM} km from the record's own postcode, and {int(bands.k.iloc[-1]):,} more than 500 km. "
           f"Records whose own text says the facility is located in another district or state are far from their "
           f"postcode {r0.rate * 100:.1f}% of the time ({r0.k} of {r0.n}), against {r1.rate * 100:.1f}% "
           f"({r1.k} of {r1.n}) for all other records: the coordinates follow the other facility.")
    S.save(fig, io.out("s2_distance"), alt)
    return dict(n=n, far=far, bands=bands, grp=grp)


def nearest_state(pin_dir, lat, lon):
    """State of the nearest India Post office to each point (equirectangular at 22N; fine for a state lookup)."""
    from scipy.spatial import cKDTree
    k = np.cos(np.radians(22))
    tree = cKDTree(np.c_[pin_dir.la.to_numpy(), pin_dir.lo.to_numpy() * k])
    _, i = tree.query(np.c_[np.asarray(lat, float), np.asarray(lon, float) * k])
    return pin_dir.statename.str.upper().str.strip().to_numpy()[i]


def map_chart(loc, le, pin_dir):
    d = loc[loc.raw_coords_to_pin_km > FAR_KM].copy()
    # postcode centre used by cleaning (repaired PIN points), from the PIN gazetteer
    gaz = io.load("pin_gaz", ["pin", "state", "lat", "lon"]).rename(
        columns={"lat": "pin_lat", "lon": "pin_lon", "state": "pin_state"})
    gaz["pin"] = pd.to_numeric(gaz.pin, errors="coerce")
    d = d.merge(gaz, on="pin", how="left")
    d = d[d.pin_lat.notna() & d.raw_lat.notna()]
    d["locelse"] = d.unique_id.map(le).fillna(False).astype(bool)
    d["pin_point_state"] = nearest_state(pin_dir, d.raw_lat, d.raw_lon)
    d["other_state"] = d.pin_point_state != d.pin_state.str.upper().str.strip()
    n_os = int(d.other_state.sum())
    fig, ax = S.new_figure(size=(10.5, 10.5))
    S.india_point_map(ax, loc.raw_lon, loc.raw_lat, color=S.AXIS, s=3, alpha=0.35)
    for v, col, lw, al, z in [(False, S.CATEGORICAL[0], 0.45, 0.3, 2), (True, S.CATEGORICAL[1], 0.55, 0.5, 3)]:
        g = d[d.locelse == v]
        for r in g.itertuples():
            ax.annotate("", xy=(r.raw_lon, r.raw_lat), xytext=(r.pin_lon, r.pin_lat), zorder=z,
                        arrowprops=dict(arrowstyle="-|>,head_length=0.25,head_width=0.12", color=col, lw=lw,
                                        alpha=al, shrinkA=0, shrinkB=0))
    hi = d[d.unique_id.str[:8].isin(LABELLED)]
    for r in hi.itertuples():
        ax.annotate("", xy=(r.raw_lon, r.raw_lat), xytext=(r.pin_lon, r.pin_lat), zorder=5,
                    arrowprops=dict(arrowstyle="-|>,head_length=0.6,head_width=0.3", color=S.INK, lw=1.6,
                                    shrinkA=0, shrinkB=0))
        ax.plot(r.pin_lon, r.pin_lat, "o", ms=5, color=S.INK, zorder=6)
        ax.annotate(f"{LABELLED[r.unique_id[:8]]}\npostcode {int(r.pin)} -> pin {r.raw_coords_to_pin_km:,.0f} km away",
                    (r.pin_lon, r.pin_lat), xytext=(8, 6), textcoords="offset points", fontsize=10, color=S.INK,
                    zorder=7, bbox=dict(boxstyle="round,pad=0.2", fc=S.SURFACE, ec="none", alpha=0.85))
    n_le = int(d.locelse.sum())
    from matplotlib.lines import Line2D
    ax.legend([Line2D([], [], color=S.CATEGORICAL[1], lw=2), Line2D([], [], color=S.CATEGORICAL[0], lw=2),
               Line2D([], [], color=S.INK, marker="o", lw=1.6)],
              [f"Own text says it is located elsewhere ({n_le:,})", f"Other far records ({len(d) - n_le:,})",
               "Labelled: dot = own postcode, arrow head = listed pin"], loc="lower right", fontsize=10.5)
    S.finding_title(ax, f"{len(d):,} records put their map pin more than {FAR_KM} km from their own postcode; "
                        f"{n_os:,} of the pins land in another state, the farthest "
                        f"{d.raw_coords_to_pin_km.max():,.0f} km away", wrap=62,
                    subtitle=f"One arrow per record, from postcode centre to listed pin (n = {len(d):,} of "
                             f"{loc.raw_coords_to_pin_km.notna().sum():,}). Grey dots: every listed pin.")
    io.note(fig, "Arrow tail: postcode centre from derived/v1/pin_gazetteer.parquet; head: raw listing coordinates; "
                 "derived/v1/facility_location.parquet. Pin state = state of the nearest India Post office. 'Located elsewhere' "
                 "as in s2_distance (726 here on cleaned distances; 723 on raw postcode medians). No boundaries drawn.",
            width=120)
    io.write_csv(d[["unique_id", "name", "address_city", "address_stateOrRegion", "pin", "pin_lat", "pin_lon", "raw_lat",
                    "raw_lon", "raw_coords_to_pin_km", "loc_conf", "locelse", "pin_state", "pin_point_state", "other_state"]],
                 "s2_map")
    alt = (f"Point map of India without boundaries. {len(d):,} arrows, one per record whose listed coordinates sit more "
           f"than {FAR_KM} km from the centre of its own postcode, drawn from postcode to pin. {n_le:,} of them belong "
           f"to records whose own text says the facility is located in another district or state, and {n_os:,} pins land "
           f"in a different state from the postcode. Most arrows stay inside one region, but some cross the country: Gem Hospital, Bathinda (postcode in Punjab) is pinned "
           f"about 2,350 km away, and the Aravind Eye Hospital record listed in Hyderabad has a Delhi postcode and a "
           f"pin in Tamil Nadu, 1,871 km apart.")
    S.save(fig, io.out("s2_map"), alt)
    return dict(n_far=len(d), n_locelse=n_le, n_other_state=n_os)


def run():
    loc = io.load("location")
    pin_dir = io.load("pincode", ["pincode", "statename", "latitude", "longitude"])
    pin_dir["la"] = pd.to_numeric(pin_dir.latitude, errors="coerce")
    pin_dir["lo"] = pd.to_numeric(pin_dir.longitude, errors="coerce")
    pin_dir = pin_dir[pin_dir.la.between(6, 38) & pin_dir.lo.between(68, 98)]
    le = located_elsewhere()
    j = audit_distances(pin_dir)
    j["locelse"] = j.index.map(le).fillna(False).astype(bool)
    res = distance_chart(loc, j)
    res.update(map_chart(loc, le, pin_dir.reset_index(drop=True)))
    print("s2", res["n"], res["far"], res["grp"][["group", "k", "n", "rate"]].to_dict("records"), res["n_far"], res["n_locelse"], res["n_other_state"])
    return res


if __name__ == "__main__":
    run()
