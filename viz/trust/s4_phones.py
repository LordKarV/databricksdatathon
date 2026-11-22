"""Story 4: one phone number, 431 hospitals.

Chart s4_phones: the 12 phone numbers attached to the most records, with the number
of distinct state strings and cities they span, how many records list them as the
officialPhone, and the source domain most over-represented among their holders.
Numbers are partly masked on the chart (they are directory / call-centre lines, but a
slide does not need them in full); the CSV keeps them for reproducibility.

Inputs: data/raw/facilities.parquet (phone_numbers, officialPhone, city, state, as given),
derived/v1/facility_location.parquet (the 9,959 records), derived/v1/source_urls.parquet.
Run: .venv-viz/bin/python viz/trust/s4_phones.py
"""
from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd

import trust_io as io
import style as S

TOP = 12
MULTI_CITY = 3  # a number held by records in 3+ cities is treated as a directory line (audit ID5)


def norm_phone(p):
    """Digits of an Indian number: drop +91 / leading 0; keep 1800 / 1860 toll-free as is. None if not 10 digits."""
    d = re.sub(r"\D", "", p if isinstance(p, str) else "")
    if d.startswith("91180") or d.startswith("91186"):
        d = d[2:]
    if d.startswith("1800") or d.startswith("1860"):
        return d
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    elif len(d) == 11 and d.startswith("0"):
        d = d[1:]
    return d if len(d) == 10 else None


def parse_list(s):
    try:
        v = json.loads(s) if isinstance(s, str) else []
    except ValueError:
        return []
    return v if isinstance(v, list) else [v]


def mask(num):
    return f"{num[:4]} {num[4:6]}xx xxxx" if len(num) == 10 else f"{num[:6]}xx xxx"


def holders():
    ids = set(io.load("location", ["unique_id"]).unique_id)
    f = io.load("facilities", ["unique_id", "phone_numbers", "officialPhone", "address_city", "address_stateOrRegion"])
    f = f[f.unique_id.isin(ids)].drop_duplicates("unique_id")
    rows = []
    for r in f.itertuples():
        off = norm_phone(r.officialPhone)
        nums = {norm_phone(x) for x in parse_list(r.phone_numbers) + [r.officialPhone]} - {None}
        for n in nums:
            rows.append((r.unique_id, n, n == off, (r.address_city or "").strip().lower(),
                         (r.address_stateOrRegion or "").strip().lower()))
    h = pd.DataFrame(rows, columns=["unique_id", "phone", "is_official", "city", "state"])
    return f, h


def top_domain(su, uids, base):
    sub = su[su.unique_id.isin(uids)].drop_duplicates(["unique_id", "domain"])
    share = sub.domain.value_counts() / len(uids)
    lift = (share / base.reindex(share.index)).dropna()
    lift = lift[sub.domain.value_counts().reindex(lift.index) >= max(5, 0.3 * len(uids))]
    if lift.empty:
        return None, 0
    d = lift.idxmax()
    return d, int(sub.domain.value_counts()[d])


def run():
    f, h = holders()
    n_rec = len(f)
    per = h.groupby("phone").agg(records=("unique_id", "nunique"), official=("is_official", "sum"),
                                 cities=("city", "nunique"), states=("state", "nunique")).reset_index()
    per = per.sort_values("records", ascending=False)
    multi = per[per.cities >= MULTI_CITY]
    rec_multi = h[h.phone.isin(multi.phone)].unique_id.nunique()
    off = h[h.is_official]
    n_off = off.unique_id.nunique()
    off_multi = off[off.phone.isin(multi.phone)].unique_id.nunique()

    su = io.load("source_urls", ["unique_id", "domain"]).drop_duplicates()
    base = su.domain.value_counts() / su.unique_id.nunique()
    top = per.head(TOP).copy()
    dom = [top_domain(su, set(h[h.phone == p].unique_id), base) for p in top.phone]
    top["top_domain"], top["top_domain_records"] = zip(*dom)
    top["label"] = top.phone.map(mask)

    fig, ax = S.new_figure(size=(12, 7.2))
    y = np.arange(len(top))[::-1]
    ax.barh(y, top.records, color=S.SEMANTIC["unlikely"], height=0.62, **S.bar_style())
    ax.barh(y, top.official, color=S.SEMANTIC["verified"], height=0.62, **S.bar_style())
    for yi, r in zip(y, top.itertuples()):
        src = (f"; {r.top_domain_records} cite {r.top_domain}" if r.top_domain else "")
        ax.annotate(f"{r.records:,} records, {r.states} state names, {r.cities} cities{src}", (r.records, yi),
                    xytext=(6, 0), textcoords="offset points", va="center", fontsize=10.5, color=S.INK)
    ax.set_yticks(y, top.label, fontfamily="monospace", fontsize=11)
    ax.set_xlim(0, top.records.max() * 2.05)
    ax.set_xlabel(f"Records carrying the number (of {n_rec:,})")
    ax.grid(axis="y", visible=False)
    from matplotlib.patches import Patch
    ax.legend([Patch(fc=S.SEMANTIC["verified"]), Patch(fc=S.SEMANTIC["unlikely"])],
              ["...as the record's officialPhone", "...in phone_numbers only"], loc="lower right", fontsize=11)
    t0 = top.iloc[0]
    S.finding_title(ax, f"One mobile number sits on {t0.records} facility records in {t0.states} state names and is "
                        f"the 'official' phone of {t0.official}; {t0.top_domain_records} of those records cite "
                        f"{t0.top_domain}, a property-listing site", wrap=88,
                    subtitle=f"The {TOP} most-shared numbers, partly masked. {rec_multi:,} records carry a number held in "
                             f"{MULTI_CITY}+ cities; {off_multi:,} of {n_off:,} official phones are such numbers.")
    io.note(fig, f"Numbers normalised to 10 digits from phone_numbers and officialPhone in data/raw/facilities.parquet "
                 f"(9,959 records in derived/v1/facility_location.parquet). State and city strings as written in the "
                 f"record, so spelling variants count separately. Source domain: the domain most over-represented among "
                 f"holders versus all records (derived/v1/source_urls.parquet). Multi-city rule from audit ID5.")
    io.write_csv(top[["phone", "label", "records", "official", "cities", "states", "top_domain", "top_domain_records"]],
                 "s4_phones")
    alt = (f"Horizontal bars of the {TOP} phone numbers attached to the most facility records. The top number is on "
           f"{t0.records} records spread over {t0.states} state names and {t0.cities} cities, and is the official phone "
           f"of {t0.official}; {t0.top_domain_records} of its holders cite {t0.top_domain} as a source. In all, "
           f"{len(multi):,} numbers are held by records in {MULTI_CITY} or more cities, and {rec_multi:,} of {n_rec:,} "
           f"records carry at least one of them; {off_multi:,} of {n_off:,} official phones are such numbers.")
    S.save(fig, io.out("s4_phones"), alt)
    res = dict(n_records=n_rec, n_multi_numbers=len(multi), rec_multi=rec_multi, n_official=n_off,
               official_multi=off_multi, top=top.head(3)[["phone", "records", "official", "states", "cities",
                                                          "top_domain", "top_domain_records"]].to_dict("records"))
    print("s4", res)
    return res


if __name__ == "__main__":
    run()
