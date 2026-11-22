"""Story 1: one record, two (or three) hospitals.

Charts
- s1_anatomy: every claim sentence of two contaminated records (Aravind Eye
  Hospital "Hyderabad", Wockhardt Hospital Nagpur) as one tile each, coloured
  by who the sentence names, with quoted sentences and the three places each
  record points to.
- s1_who: share of records with a sentence that places care at another named
  facility, by state, by facility type and by number of source URLs.

Inputs: derived/v1/claims.parquet, derived/v1/facility_location.parquet,
derived/v1/pin_gazetteer.parquet (via location table PINs), audit/scale/scale_flags.parquet,
audit/provenance/q1_records.parquet, data/raw/india_post_pincode_directory.parquet.
Run: .venv-viz/bin/python viz/trust/s1_merged.py
"""
from __future__ import annotations

import math
import textwrap

import numpy as np
import pandas as pd

import trust_io as io
import style as S

ARAVIND = "b8a5401f-42f1-422a-8cd9-686a15b4cb76"
WOCKHARDT = "3ac5ae50-9ce2-4de3-a13c-d95a4ef218ee"
ATTR = [  # attribution value, legend label, colour
    ("own_anchored", "Names this facility", S.SEMANTIC["verified"]),
    ("other_facility", "Names another facility or its town", S.SEMANTIC["unlikely"]),
    ("ambiguous", "Credential or relation (ambiguous)", S.SEMANTIC["flagged"]),
    ("unanchored", "Names no facility", S.SEMANTIC["not_verified"]),
]
COLS = 40
# Sentences quoted on the chart: (record, field, idx). Chosen by reading the full record.
QUOTES = {
    ARAVIND: [("capability", 2), ("capability", 5), ("capability", 10), ("capability", 42)],
    WOCKHARDT: [("description", 0), ("capability", 12), ("procedure", 17), ("equipment", 45)],
}


def hav_km(a, b, c, d):
    a, b, c, d = map(math.radians, (a, b, c, d))
    h = math.sin((c - a) / 2) ** 2 + math.cos(a) * math.cos(c) * math.sin((d - b) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def nearest_office(pin_dir, lat, lon):
    d = np.hypot(pin_dir.la - lat, (pin_dir.lo - lon) * math.cos(math.radians(lat)))
    r = pin_dir.loc[d.idxmin()]
    return f"{r.officename.replace(' SO', '').replace(' S.O', '').title()}, {r.district.title()}, {r.statename.title()}"


def record_places(loc, pin_dir, uid):
    r = loc.set_index("unique_id").loc[uid]
    pin = str(int(r.pin))
    pr = pin_dir[pin_dir.pincode.astype(str) == pin]
    pin_lat, pin_lon = pr.la.median(), pr.lo.median()
    pin_place = f"{pr.district.mode()[0].title()}, {pr.statename.mode()[0].title()}"
    coord_place = nearest_office(pin_dir, r.raw_lat, r.raw_lon)
    return dict(city=r.address_city, state=r.address_stateOrRegion, pin=pin, pin_place=pin_place,
                coord_place=coord_place, coords_to_pin_km=hav_km(r.raw_lat, r.raw_lon, pin_lat, pin_lon),
                raw_lat=r.raw_lat, raw_lon=r.raw_lon, loc_conf=r.loc_conf)


def anatomy(claims, loc, pin_dir):
    fig = S.plt.figure(figsize=(12, 9.4), constrained_layout=True)
    axes = fig.subplots(2, 1, gridspec_kw=dict(height_ratios=[1, 1]))
    tidy, alt_bits = [], []
    for ax, uid in zip(axes, [ARAVIND, WOCKHARDT]):
        s = claims[claims.unique_id == uid].sort_values(["field", "idx"]).reset_index(drop=True)
        pl = record_places(loc, pin_dir, uid)
        name = s.name.iloc[0] if "name" in s else uid
        n = len(s)
        counts = s.attribution.value_counts()
        n_svc = int((s.services != "").sum())
        n_svc_anon = int(((s.services != "") & (s.attribution == "unanchored")).sum())
        qkeys = QUOTES[uid]
        qpos = {}
        for i, r in s.iterrows():
            x, y = i % COLS, -(i // COLS)
            col = dict((a, c) for a, _, c in ATTR)[r.attribution]
            is_q = (r.field, r.idx) in qkeys
            ax.add_patch(S.plt.Rectangle((x + 0.06, y + 0.06), 0.88, 0.88, fc=col,
                                         ec=S.INK if is_q else "none", lw=1.6 if is_q else 0))
            if r.services and not is_q:
                ax.plot(x + 0.5, y + 0.5, "o", ms=3.2, color=S.INK if r.attribution != "own_anchored" else "#ffffff")
            if is_q:
                qpos[(r.field, r.idx)] = (x, y, r)
                k = qkeys.index((r.field, r.idx)) + 1
                ink = "#ffffff" if r.attribution in ("own_anchored", "other_facility") else S.INK
                ax.text(x + 0.5, y + 0.47, str(k), ha="center", va="center", fontsize=10, color=ink,
                        fontweight="bold")
            tidy.append(dict(unique_id=uid, record=name, listed_city=pl["city"], position=i, field=r.field,
                             idx=r.idx, attribution=r.attribution, services=r.services, quoted=is_q, text=r.text))
        rows = math.ceil(n / COLS)
        # quotes, two columns under the grid
        for k, key in enumerate(qkeys):
            x, y, r = qpos[key]
            lab = dict((a, l) for a, l, _ in ATTR)[r.attribution]
            svc = f"; claims {r.services.replace('|', ', ')}" if r.services else ""
            txt = textwrap.fill(f"{k + 1}. \"{r.text}\"", 66) + f"\n    [{r.field}, {lab.lower()}{svc}]"
            cx, cy = (0 if k % 2 == 0 else COLS / 2 + 0.5), -rows + 0.4 - (k // 2) * 3.3
            ax.text(cx, cy, txt, ha="left", va="top", fontsize=10, color=S.INK, linespacing=1.15)
        ax.set_xlim(-0.2, COLS + 0.2)
        ax.set_ylim(-rows - 6.6, 1.1)
        ax.set_aspect("equal")
        ax.axis("off")
        places = (f"Listed city: {pl['city']}, {pl['state']}.  Postcode {pl['pin']}: {pl['pin_place']}.  "
                  f"\nCoordinates: near {pl['coord_place']} ({pl['coords_to_pin_km']:,.0f} km from the postcode). "
                  f"Location confidence after cleaning: {pl['loc_conf']}.")
        S.panel_title(ax, f"{name} (record {uid[:8]}): {n} claim sentences, {n_svc} claim one of 8 tracked "
                          f"services, {n_svc_anon} of those name no facility\n{places}")
        alt_bits.append(
            f"{name} (listed in {pl['city']}): {n} sentences, {int(counts.get('own_anchored', 0))} name the facility, "
            f"{int(counts.get('other_facility', 0))} name another facility or its town, "
            f"{int(counts.get('unanchored', 0))} name nobody; postcode {pl['pin']} is in {pl['pin_place']} and the "
            f"coordinates are near {pl['coord_place']}")
    # legend row with counts over both records
    t = pd.DataFrame(tidy)
    handles = [S.plt.Rectangle((0, 0), 1, 1, fc=c) for _, _, c in ATTR]
    labels = [f"{l} ({int((t.attribution == a).sum())})" for a, l, _ in ATTR]
    handles.append(S.plt.Line2D([], [], marker="o", ls="", color=S.INK, ms=4))
    labels.append("dot: claims a tracked service")
    axes[1].legend(handles, labels, loc="lower left", bbox_to_anchor=(0, -0.02), ncol=5, fontsize=10.5,
                   handlelength=1.1, columnspacing=1.2)
    S.fig_title(fig, "An eye hospital listed in Hyderabad carries a Delhi government hospital's text (dialysis, "
                     "trauma, 1,241 beds) and a Delhi postcode; a Nagpur hospital's text and coordinates are Mumbai's")
    io.note(fig, "One tile per claim sentence in record order (capability, description, equipment, procedure). "
                       "Attribution from derived/v1/claims.parquet; places from derived/v1/facility_location.parquet "
                       "and data/raw/india_post_pincode_directory.parquet (nearest post office).")
    io.write_csv(t, "s1_anatomy")
    alt = ("Two facility records drawn as grids of tiles, one tile per claim sentence, coloured by whom the sentence "
           "names. " + ". ".join(alt_bits) + ". Most service sentences, including a 20-bed dialysis unit and a 3T MRI, "
           "name no facility at all, so no rule can tell they were copied from another hospital.")
    S.save(fig, io.out("s1_anatomy"), alt)
    return t


def rate_table(df, by, flag="direct"):
    g = df.groupby(by, observed=True)[flag].agg(k="sum", n="count").reset_index()
    w = [S.wilson(int(k), int(n)) for k, n in zip(g.k, g.n)]
    g["rate"], g["lo"], g["hi"] = zip(*w)
    return g


def who(claims, loc):
    direct = set(claims.loc[claims.context == "direct", "unique_id"])
    sf = io.load("scale_flags", ["unique_id", "facility_type_norm"]).drop_duplicates("unique_id")
    pv = io.load("prov_sources", ["unique_id", "n_urls"]).drop_duplicates("unique_id")
    r = loc[["unique_id", "state_final"]].merge(sf, on="unique_id", how="left").merge(pv, on="unique_id", how="left")
    r["direct"] = r.unique_id.isin(direct)
    N, K = len(r), int(r.direct.sum())
    p_all, lo_all, hi_all = S.wilson(K, N)

    st = rate_table(r, "state_final")
    st = st[st.n >= 100].sort_values("rate")
    st["state"] = st.state_final.str.title().str.replace(" And ", " and ")
    ft = r.copy()
    ft["type"] = ft.facility_type_norm.fillna("unknown").replace({"doctor": "other", "pharmacy": "other",
                                                                    "unknown": "other"})
    ft = rate_table(ft, "type").sort_values("rate")
    r["band"] = pd.cut(r.n_urls, [0, 2, 7, 14, 29, 50], labels=["1-2", "3-7", "8-14", "15-29", "30-50"])
    bd = rate_table(r, "band")

    fig = S.plt.figure(figsize=(12, 7.2), constrained_layout=True)
    gs = fig.add_gridspec(2, 2, width_ratios=[1.05, 1], height_ratios=[1, 1.15])
    a_st, a_ft, a_bd = fig.add_subplot(gs[:, 0]), fig.add_subplot(gs[0, 1]), fig.add_subplot(gs[1, 1])

    y = np.arange(len(st))
    a_st.axvspan(lo_all * 100, hi_all * 100, color=S.NEUTRAL, zorder=0)
    a_st.axvline(p_all * 100, color=S.MUTED, lw=1, ls="--", zorder=1)
    a_st.text(p_all * 100, len(st) - 0.3, f" all records {p_all * 100:.1f}%", color=S.INK_2, fontsize=10, va="bottom")
    S.add_interval(a_st, y, st.lo * 100, st.hi * 100, horizontal=True, cap=0, lw=1.6, color=S.AXIS)
    a_st.plot(st.rate * 100, y, "o", color=S.CATEGORICAL[0], ms=7, zorder=4)
    a_st.set_yticks(y, [f"{s} ({n:,})" for s, n in zip(st.state, st.n)], fontsize=10.5)
    a_st.set_xlim(0, 30)
    a_st.set_ylim(-0.7, len(st) - 0.1)
    a_st.set_xlabel("Records naming another facility (%, 95% Wilson interval)")
    a_st.grid(axis="y", visible=False)
    S.panel_title(a_st, f"By state: {len(st)} states with 100+ records (n in brackets)")

    for ax, d, lab, title, col in [
        (a_ft, ft, "type", "By facility type (facilityTypeId)", S.CATEGORICAL[0]),
        (a_bd, bd, "band", "By number of source URLs merged into the record", S.CATEGORICAL[1]),
    ]:
        x = np.arange(len(d))
        bars = ax.bar(x, d.rate * 100, color=col, width=0.62, **S.bar_style())
        S.add_interval(ax, x, d.lo * 100, d.hi * 100)
        for xi, rr in zip(x, d.itertuples()):
            ax.annotate(f"{rr.rate * 100:.1f}%\n{int(rr.k):,}/{int(rr.n):,}", (xi, rr.hi * 100), xytext=(0, 3),
                        textcoords="offset points", ha="center", va="bottom", fontsize=9.5, color=S.INK)
        ax.set_xticks(x, [str(v).title() if lab == "type" else str(v) for v in d[lab]])
        ax.set_ylim(0, 45)
        ax.set_ylabel("Records naming another\nfacility (%)")
        ax.grid(axis="x", visible=False)
        S.panel_title(ax, title)
    a_bd.set_xlabel("Source URLs in the record")
    lo_b, hi_b = bd.iloc[0], bd.iloc[-1]
    S.fig_title(fig, f"Contamination tracks how many web pages were merged into a record: "
                     f"{lo_b.rate * 100:.1f}% of records built from 1-2 URLs name another facility, "
                     f"{hi_b.rate * 100:.0f}% of those built from 30-50. States range only "
                     f"{st.rate.min() * 100:.0f}% to {st.rate.max() * 100:.0f}%")
    io.note(fig, f"Flag: at least one claim sentence places a service or fact at another named facility "
                       f"(context = direct in derived/v1/claims.parquet): {K:,} of {N:,} records. Sentence precision "
                       f"about 20 of 30 on a hand check; the audit's precision-adjusted estimate is about 1,405 (14%). "
                       f"Types: audit/scale/scale_flags.parquet; URLs: audit/provenance/q1_records.parquet (source_urls is capped at 50). Hospitals also have more URLs, so type and breadth overlap.")
    tidy = pd.concat([st.assign(panel="state", group=st.state)[["panel", "group", "k", "n", "rate", "lo", "hi"]],
                      ft.assign(panel="facility_type", group=ft.type)[["panel", "group", "k", "n", "rate", "lo", "hi"]],
                      bd.assign(panel="source_urls", group=bd.band.astype(str))[["panel", "group", "k", "n", "rate", "lo", "hi"]]])
    io.write_csv(tidy, "s1_who")
    alt = (f"{K:,} of {N:,} records ({p_all * 100:.1f}%) have a claim sentence that places care at another named "
           f"facility. Across the {len(st)} states with 100 or more records the share runs from "
           f"{st.rate.min() * 100:.0f}% ({st.state.iloc[0]}) to {st.rate.max() * 100:.0f}% ({st.state.iloc[-1]}); "
           f"only {', '.join(st.state[(st.hi < p_all) | (st.lo > p_all)])} have intervals that exclude the national "
           f"{p_all * 100:.1f}%. Hospitals are flagged at {ft.set_index('type').rate.get('hospital', np.nan) * 100:.0f}% "
           f"and clinics at {ft.set_index('type').rate.get('clinic', np.nan) * 100:.0f}%. The share climbs steadily with "
           f"the number of source URLs: {lo_b.rate * 100:.1f}% for 1-2 URLs ({int(lo_b.k)} of {int(lo_b.n)}) to "
           f"{hi_b.rate * 100:.0f}% for 30-50 URLs ({int(hi_b.k)} of {int(hi_b.n)}).")
    S.save(fig, io.out("s1_who"), alt)
    return dict(n=N, k=K, rate=p_all, lo=lo_all, hi=hi_all,
                band=bd[["band", "k", "n", "rate", "lo", "hi"]].astype({"band": str}).to_dict("records"),
                type=ft[["type", "k", "n", "rate"]].to_dict("records"))


def run():
    claims = io.load("claims", ["unique_id", "field", "idx", "text", "attribution", "context", "services"])
    loc = io.load("location")
    claims = claims.merge(loc[["unique_id", "name"]], on="unique_id", how="left")
    pin_dir = io.load("pincode", ["officename", "pincode", "district", "statename", "latitude", "longitude"])
    pin_dir["la"] = pd.to_numeric(pin_dir.latitude, errors="coerce")
    pin_dir["lo"] = pd.to_numeric(pin_dir.longitude, errors="coerce")
    pin_dir = pin_dir[pin_dir.la.between(6, 38) & pin_dir.lo.between(68, 98)].reset_index(drop=True)
    anatomy(claims, loc, pin_dir)
    res = who(claims, loc)
    print("s1", {k: v for k, v in res.items() if k not in ("band", "type")})
    print("s1 bands", res["band"])
    return res


if __name__ == "__main__":
    run()
