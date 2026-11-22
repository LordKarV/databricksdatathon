"""Story 5: dialysis travel burden. Weekly road km for 3 sessions a week to the nearest dialysis unit, by district.

Population: WorldPop 2025 1 km constrained grid (data/external/worldpop_r2025a), summed to 5 x 5 km blocks.
Each block centre goes to its LGD district by point-in-polygon (district polygons used only for aggregation,
never drawn). Nearest unit by great-circle distance, then geo.travel.estimate for road km (straight line x
measured road factor, hill constants for hill states). Weekly km = 3 sessions x 2 legs x road km.

Three evidence tiers for "has dialysis" (derived/v1/grades.parquet, service dialysis):
  claimed       any own claim graded strong, moderate, weak or tag_only
  graded        graded strong or moderate
  corroborated  graded strong or moderate AND the facility's own website confirms it
                (kb/web_evidence/out/web_service_summary.parquet: dialysis, web_positive_strong,
                identity_conf high or medium)
Output: charts/s5_dialysis_burden.*, charts/s5b_dialysis_tiers.*, data/s5_district_dialysis.csv,
data/s5_population_bands.csv.
"""
import os

os.environ["TRAVEL_CACHE"] = "off"

import geopandas as gpd  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import rasterio  # noqa: E402
from sklearn.neighbors import BallTree  # noqa: E402

from common import CHARTS, DATA, ROOT, S, note  # noqa: E402
from geo import travel  # noqa: E402

BLOCK = 5
SESSIONS = 3
BANDS = [0, 60, 150, 300, 600, np.inf]
BAND_LABEL = ["under 60 km", "60 to 150", "150 to 300", "300 to 600", "600 km or more"]
TIERS = ["claimed", "graded", "corroborated"]
ROAD_FACTOR_RANGE = {"p10": 1.14, "p90": 2.01}  # geo/README.md, all distances
TIER_LABEL = {"claimed": "Any claim in the record", "graded": "Claim graded strong or moderate",
              "corroborated": "Graded and confirmed on own website"}


def population_blocks():
    with rasterio.open(ROOT / "data/external/worldpop_r2025a/ind_pop_2025_CN_1km_R2025A_UA_v1.tif") as r:
        a = r.read(1)
        tf = r.transform
    a = np.where(a < 0, 0, a)
    h, w = (a.shape[0] // BLOCK) * BLOCK, (a.shape[1] // BLOCK) * BLOCK
    b = a[:h, :w].reshape(h // BLOCK, BLOCK, w // BLOCK, BLOCK).sum(axis=(1, 3))
    rows, cols = np.nonzero(b > 0)
    lon = tf.c + (cols * BLOCK + BLOCK / 2) * tf.a
    lat = tf.f + (rows * BLOCK + BLOCK / 2) * tf.e
    return pd.DataFrame({"lat": lat, "lon": lon, "pop": b[rows, cols]}), float(a.sum())


def assign_district(cells):
    d = gpd.read_parquet(ROOT / "data/external/lgd_district_polygons/LGD_Districts.parquet",
                         columns=["stname", "dtname", "dist_lgd", "geometry"])
    pts = gpd.GeoDataFrame(cells, geometry=gpd.points_from_xy(cells.lon, cells.lat), crs=d.crs)
    j = gpd.sjoin(pts, d, how="left", predicate="within")
    j = j[~j.index.duplicated()]
    return pd.DataFrame(j.drop(columns=["geometry", "index_right"]))


def tiers():
    g = pd.read_parquet(ROOT / "derived/v1/grades.parquet", columns=["unique_id", "service", "grade"])
    g = g[g.service == "dialysis"]
    w = pd.read_parquet(ROOT / "kb/web_evidence/out/web_service_summary.parquet",
                        columns=["unique_id", "service_id", "web_positive_strong", "identity_conf"])
    web = set(w[(w.service_id == "dialysis") & w.web_positive_strong & w.identity_conf.isin(["high", "medium"])].unique_id)
    claimed = set(g[g.grade.isin(["strong", "moderate", "weak", "tag_only"])].unique_id)
    graded = set(g[g.grade.isin(["strong", "moderate"])].unique_id)
    f = pd.read_parquet(ROOT / "derived/v1/facility_location.parquet",
                        columns=["unique_id", "loc_lat", "loc_lon", "district", "state_final"]).dropna(subset=["loc_lat"])
    return {"claimed": f[f.unique_id.isin(claimed)], "graded": f[f.unique_id.isin(graded)],
            "corroborated": f[f.unique_id.isin(graded & web)]}


def nearest_road_km(cells, fac):
    tree = BallTree(np.radians(fac[["loc_lat", "loc_lon"]].values), metric="haversine")
    _, idx = tree.query(np.radians(cells[["lat", "lon"]].values), k=1)
    idx = idx[:, 0]
    flat, flon = fac.loc_lat.values[idx], fac.loc_lon.values[idx]
    km, mins, straight = np.empty(len(cells)), np.empty(len(cells)), np.empty(len(cells))
    for i, (la, lo, st, a, b) in enumerate(zip(cells.lat.values, cells.lon.values, cells.stname.values, flat, flon)):
        r = travel.estimate((la, lo), (a, b), state=st if isinstance(st, str) else None)
        km[i], mins[i] = r["km"], r["minutes"]
        straight[i] = travel.hav_km((la, lo), (a, b))
    return km, mins, straight


def wmedian(x, w):
    o = np.argsort(x)
    c = np.cumsum(w[o])
    return float(x[o][np.searchsorted(c, c[-1] / 2)])


def build():
    cells, total_pop = population_blocks()
    cells = assign_district(cells)
    tf = tiers()
    for t in TIERS:
        km, mins, straight = nearest_road_km(cells, tf[t])
        cells[f"weekly_km_{t}"] = km * 2 * SESSIONS
        cells[f"weekly_straight_km_{t}"] = straight * 2 * SESSIONS
        cells[f"weekly_hours_{t}"] = mins * 2 * SESSIONS / 60
    cells.to_parquet(DATA / "s5_cells.parquet", index=False)
    in_d = cells.dropna(subset=["dist_lgd"])
    rows = []
    for (st, dt, code), g in in_d.groupby(["stname", "dtname", "dist_lgd"]):
        w = g["pop"].values
        r = {"state": st, "district": dt, "dist_lgd": int(code), "population": w.sum(),
             "lat": np.average(g.lat, weights=w), "lon": np.average(g.lon, weights=w)}
        for t in TIERS:
            r[f"median_weekly_km_{t}"] = wmedian(g[f"weekly_km_{t}"].values, w)
            r[f"median_weekly_hours_{t}"] = wmedian(g[f"weekly_hours_{t}"].values, w)
        rows.append(r)
    dist = pd.DataFrame(rows)
    # islands have no road to the mainland units; the road estimate is meaningless there
    dist["road_estimate_valid"] = ~dist.state.isin(["ANDAMAN & NICOBAR", "LAKSHADWEEP"])
    bands = []
    for t in TIERS:
        b = pd.cut(cells[f"weekly_km_{t}"], BANDS, labels=BAND_LABEL, right=False)
        s = cells.groupby(b, observed=False)["pop"].sum()
        bands += [{"tier": t, "band": k, "population": v, "share": v / cells["pop"].sum()} for k, v in s.items()]
        # sensitivity: one road factor for every trip, at geo/README.md's 10th and 90th percentile (1.14, 2.01)
        for name, fct in ROAD_FACTOR_RANGE.items():
            wk = cells[f"weekly_straight_km_{t}"] * fct
            for thr in (300, 600):
                bands.append({"tier": t, "band": f"{thr}+ at factor {name}", "population": cells.loc[wk >= thr, "pop"].sum(),
                              "share": cells.loc[wk >= thr, "pop"].sum() / cells["pop"].sum()})
    meta = {"total_pop_raster": total_pop, "pop_in_blocks": float(cells["pop"].sum()),
            "pop_in_districts": float(in_d["pop"].sum()), "n_blocks": len(cells),
            "units": {t: len(tf[t]) for t in TIERS},
            "unit_districts": {t: int(tf[t].district.nunique()) for t in TIERS}}
    return dist, pd.DataFrame(bands), meta, cells


def chart_map(dist, cells, meta):
    t = "corroborated"
    fig = S.plt.figure(figsize=(14, 8.6), constrained_layout=True)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.15, 1])
    ax, bx = fig.add_subplot(gs[0]), fig.add_subplot(gs[1])
    from matplotlib.colors import BoundaryNorm, ListedColormap
    cmap = ListedColormap(S.SEQUENTIAL_2[1:])
    norm = BoundaryNorm([0, 60, 150, 300, 600, 5000], cmap.N)
    md = dist[dist.road_estimate_valid]  # island districts have no road estimate, so they are left off the map
    v = md[f"median_weekly_km_{t}"].values
    sizes = 8 + 120 * np.sqrt(md.population / md.population.max())
    m = S.india_point_map(ax, md.lon, md.lat, values=v, s=sizes, alpha=0.95, cmap=cmap, norm=norm)
    cb = fig.colorbar(m, ax=ax, shrink=0.5, ticks=[0, 60, 150, 300, 600], location="left", pad=0.01)
    cb.set_label("Weekly road km, population-weighted median")
    cb.ax.tick_params(labelsize=10)
    S.panel_title(ax, f"{len(md)} mainland districts, one dot each at its population centre; dot area = population")
    # right: most burdened districts with at least 1 million people
    big = dist[dist.population >= 1e6].sort_values(f"median_weekly_km_{t}", ascending=False).head(20)
    y = np.arange(len(big))
    bars = bx.barh(y, big[f"median_weekly_km_{t}"], color=S.SEQUENTIAL_2[4], height=0.7, **S.bar_style())
    S.label_bars(bx, bars, labels=[f"{k:,.0f} km ({h:.0f} h)" for k, h in
                                   zip(big[f"median_weekly_km_{t}"], big[f"median_weekly_hours_{t}"])],
                 horizontal=True, fontsize=9.5)
    bx.set_yticks(y, [f"{d.title()}, {s.title()} ({p / 1e6:.1f} M)" for d, s, p in
                      zip(big.district, big.state, big.population)], fontsize=9.5)
    bx.invert_yaxis()
    bx.set_xlim(0, big[f"median_weekly_km_{t}"].max() * 1.35)
    bx.set_xlabel("Weekly road km to the nearest corroborated unit\n(population-weighted median; 3 return trips)")
    bx.xaxis.set_major_formatter(S.matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))
    bx.grid(axis="y", visible=False)
    S.panel_title(bx, "Top 20 districts of 1 million people or more")
    allw = cells["pop"].values
    med = wmedian(cells[f"weekly_km_{t}"].values, allw)
    over = cells.loc[cells[f"weekly_km_{t}"] >= 600, "pop"].sum() / allw.sum()
    S.fig_title(fig, f"Counting only dialysis units the data can corroborate, half of India's population lives where three "
                     f"sessions a week would mean {med:,.0f}+ road km ({over*100:.0f}% 600+ km): a map of missing evidence as "
                     f"much as missing machines")
    note(fig, f"Corroborated = dialysis claim graded strong or moderate (derived/v1/grades.parquet) and confirmed on the "
              f"facility's own website (kb/web_evidence/out/web_service_summary.parquet): {meta['units'][t]} units in "
              f"{meta['unit_districts'][t]} districts. Population: WorldPop 2025 1 km (CC BY 4.0, doi:10.5258/SOTON/WP00840) "
              f"in 5 km blocks; districts: LGD polygons used for aggregation only, not drawn. Road km: geo.travel estimate "
              f"(straight line x measured road factor, about 1.3; at the 10th to 90th percentile factor 1.14 to 2.01 each value "
              f"would be roughly 0.88 to 1.55 times as large; island districts have no road link, are left off the map and are "
              f"flagged in the CSV). "
              f"Map: points only, no boundaries. The government counts 1,994 public "
              f"centres in 751 districts (NHSRC PMNDP); most are not in the facility records "
              f"(external/pmndp_counts_and_state_lists/README.md).", width=215)
    worst = big.iloc[0]
    alt = (f"Left: dot map of {len(md)} mainland district population centres with no boundaries, coloured by the "
           f"population-weighted median weekly road km for three dialysis sessions at the nearest corroborated unit "
           f"({meta['units'][t]} units). Right: the 20 most burdened districts of at least 1 million people, led by "
           f"{worst.district.title()}, {worst.state.title()} at {worst[f'median_weekly_km_{t}']:,.0f} km a week. "
           f"Nationally the population-weighted median is {med:,.0f} km a week and {over*100:.0f}% of people face 600 km "
           f"or more. The facility records miss most of the 1,994 public dialysis centres the government counts in 751 "
           f"districts, so this measures the evidence gap, not real access.")
    S.save(fig, CHARTS / "s5_dialysis_burden", alt)
    return med, over


def chart_tiers(bands, meta, pmndp):
    fig, ax = S.new_figure(size=(12, 5.6))
    cols = [S.SEQUENTIAL_2[i] for i in range(1, 6)]
    y = np.arange(len(TIERS))
    left = np.zeros(len(TIERS))
    for b, c in zip(BAND_LABEL, cols):
        w = np.array([bands[(bands.tier == t) & (bands.band == b)].share.iloc[0] * 100 for t in TIERS])
        ax.barh(y, w, left=left, color=c, height=0.62, label=b, **S.bar_style())
        for yi, li, wi in zip(y, left, w):
            if wi >= 5:
                ax.text(li + wi / 2, yi, f"{wi:.0f}%", ha="center", va="center", fontsize=10.5,
                        color="#ffffff" if c in cols[3:] else S.INK)
        left += w
    ax.set_yticks(y, [f"{TIER_LABEL[t]}\n{meta['units'][t]:,} units, {meta['unit_districts'][t]} districts" for t in TIERS],
                  fontsize=10.5)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("Share of India's population (%), by weekly road km to the nearest unit (3 sessions, return)")
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=5, fontsize=10.5, title="Weekly road km",
              title_fontsize=10.5)
    sh = {t: bands[(bands.tier == t) & (bands.band.isin(BAND_LABEL[3:]))].share.sum() for t in TIERS}
    rng = {t: [bands[(bands.tier == t) & (bands.band == f"300+ at factor {k}")].share.iloc[0] for k in ROAD_FACTOR_RANGE]
           for t in TIERS}
    for yi, t in zip(y, TIERS):
        ax.text(1.01, yi, f"300+ km: {sh[t]*100:.0f}%\n({rng[t][0]*100:.0f} to {rng[t][1]*100:.0f}% at\nroad factor 1.14 to 2.01)",
                transform=ax.get_yaxis_transform(), ha="left", va="center", fontsize=9.5, color=S.INK_2)
    S.fig_title(fig, f"Trusting only corroborated dialysis units moves the share of people facing 300+ km a week from "
                     f"{sh['claimed']*100:.0f}% to {sh['corroborated']*100:.0f}%; the government counts "
                     f"{pmndp['centres']:,} public centres in {pmndp['districts']} districts")
    note(fig, "Evidence tiers from derived/v1/grades.parquet and kb/web_evidence/out/web_service_summary.parquet (see "
              "STORIES.md). Population: WorldPop 2025, 5 km blocks. Road km: geo.travel estimate. Government count: NHSRC "
              "PMNDP table, https://www.nhsrcindia.org/pmndp-map-table (data/external/pmndp_counts_and_state_lists); "
              "in no state does the facility data's public dialysis count reach it "
              "(external/pmndp_counts_and_state_lists/README.md).", width=190)
    alt = ("Stacked horizontal bars of India's population by weekly road km to the nearest dialysis unit under three "
           "evidence tiers. 300 km a week or more: " + ", ".join(
               f"{TIER_LABEL[t].lower()} {sh[t]*100:.0f}% ({rng[t][0]*100:.0f} to {rng[t][1]*100:.0f}% across road factors 1.14 to 2.01)"
               for t in TIERS)
           + f" ({meta['units']['claimed']}, {meta['units']['graded']} and {meta['units']['corroborated']} units). "
             f"NHSRC counts {pmndp['centres']} public dialysis centres in {pmndp['districts']} districts.")
    S.save(fig, CHARTS / "s5b_dialysis_tiers", alt)
    return sh


def main():
    dist, bands, meta, cells = build()
    dist.to_csv(DATA / "s5_district_dialysis.csv", index=False)
    bands.to_csv(DATA / "s5_population_bands.csv", index=False)
    p = pd.read_csv(ROOT / "data/external/pmndp_counts_and_state_lists/pmndp_state_counts.csv")
    pmndp = {"centres": int(p.nhsrc_functional_centres.sum()), "districts": int(p.nhsrc_functional_districts.sum())}
    med, over = chart_map(dist, cells, meta)
    sh = chart_tiers(bands, meta, pmndp)
    print(meta, pmndp, "median weekly km", med, "share 600+", over, "share 300+", sh)
    print(bands.round(3).to_string())


if __name__ == "__main__":
    main()
