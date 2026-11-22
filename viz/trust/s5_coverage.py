"""Story 5: what a coverage table says vs what a referral can use.

No organiser coverage table was found on disk, so the "reported" column is the naive
fill rate a coverage table built with COUNT(column) / COUNT(*) gives on the raw file.
For each field, three rates over the same 10,088 raw rows:
- reported: not SQL NULL;
- has a value: in one of the 9,959 well-formed, de-duplicated records and not a null
  encoding ('null', 'NULL', '[]', '[""]', '[null]', empty);
- usable: also passes the field's check (rules in USABLE_RULES, from the cleaning tables).

Inputs: data/raw/facilities.parquet, data/raw/PROFILE.json (null encodings),
derived/v1/facility_location.parquet, derived/v1/record_trust.parquet,
audit/scale/scale_flags.parquet, audit/provenance/q2_records.parquet, audit/geo/facility_geo.parquet.
Run: .venv-viz/bin/python viz/trust/s5_coverage.py
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

import trust_io as io
import style as S

NULLS = {"null", "NULL", "[]", '[""]', "[null]", "", '""'}
USABLE_RULES = {
    "name": "non-empty name",
    "address_zipOrPostcode": "6-digit postcode found in the India Post directory",
    "latitude": "coordinates within 50 km of the record's own postcode centre",
    "officialPhone": "valid Indian number not held by records in 3+ cities (directory line)",
    "email": "parsed address, not a Cloudflare placeholder",
    "officialWebsite": "the facility's own domain (not a directory, social or other organisation)",
    "description": "a description of the facility, not extractor meta-text, a bare label or truncated scrape",
    "specialties": "at least one non-empty tag",
    "capability": "at least one non-empty sentence",
    "procedure": "at least one non-empty sentence",
    "equipment": "at least one non-empty sentence",
    "facilityTypeId": "one of hospital / clinic / dentist / doctor / pharmacy",
    "operatorTypeId": "private / public / government",
    "yearEstablished": "plausible year (cleaned)",
    "numberDoctors": "plausible count, not 1 doctor at a large facility (cleaned)",
    "capacity": "plausible bed count that agrees with the record's own text",
    "affiliationTypeIds": "at least one affiliation value",
    "area": "positive number",
    "acceptsVolunteers": "true or false",
}
LABELS = {"address_zipOrPostcode": "postcode", "latitude": "coordinates", "officialPhone": "official phone",
          "officialWebsite": "official website", "facilityTypeId": "facility type", "operatorTypeId": "operator type",
          "yearEstablished": "year established", "numberDoctors": "number of doctors",
          "affiliationTypeIds": "affiliation", "acceptsVolunteers": "accepts volunteers"}


def nonempty_list(s):
    try:
        v = json.loads(s)
    except (TypeError, ValueError):
        return False
    return isinstance(v, list) and any(isinstance(x, str) and x.strip() for x in v)


def usable_masks(rec):
    """Boolean Series per field over the 9,959 records (index = unique_id)."""
    u = rec.index
    loc = io.load("location", ["unique_id", "raw_coords_to_pin_km"]).set_index("unique_id").reindex(u)
    rt = io.load("record_trust", ["unique_id", "emails_clean", "website_class", "trust_flags"]).set_index("unique_id").reindex(u)
    sf = io.load("scale_flags", ["unique_id", "doctors_clean", "capacity_clean", "year_clean", "facility_type_norm",
                                 "operator_norm", "scale_flags"]).drop_duplicates("unique_id").set_index("unique_id").reindex(u)
    ds = io.load("prov_desc", ["unique_id", "style"]).drop_duplicates("unique_id").set_index("unique_id").reindex(u)
    geo = io.load("geo", ["unique_id", "pin_in_dir"]).drop_duplicates("unique_id").set_index("unique_id").reindex(u)
    flags = sf.scale_flags.map(lambda x: set(x) if x is not None else set())
    tflags = rt.trust_flags.map(lambda x: set(x) if x is not None else set())
    has = lambda c: ~rec[c].isna() & ~rec[c].astype(str).str.strip().isin(NULLS)  # noqa: E731
    from s4_phones import norm_phone
    return {
        "name": has("name"),
        "address_zipOrPostcode": geo.pin_in_dir.fillna(False).astype(bool),
        "latitude": loc.raw_coords_to_pin_km.le(50).fillna(False),
        "officialPhone": rec.officialPhone.map(norm_phone).notna() & ~tflags.map(lambda s: "official_phone_is_directory" in s),
        "email": rt.emails_clean.map(lambda x: x is not None and len(x) > 0),
        "officialWebsite": rt.website_class.eq("own"),
        "description": has("description") & ~ds["style"].isin(["extractor_meta", "label_only", "scraped_truncated"]),
        "specialties": rec.specialties.map(nonempty_list),
        "capability": rec.capability.map(nonempty_list),
        "procedure": rec.procedure.map(nonempty_list),
        "equipment": rec.equipment.map(nonempty_list),
        "facilityTypeId": sf.facility_type_norm.isin(["hospital", "clinic", "dentist", "doctor", "pharmacy"]),
        "operatorTypeId": rec.operatorTypeId.isin(["private", "public", "government"]),
        "yearEstablished": sf.year_clean.notna() & ~flags.map(lambda s: "year_implausible" in s),
        "numberDoctors": sf.doctors_clean.notna() & ~flags.map(lambda s: bool(s & {"doctors_implausible", "doctors_1_large_facility"})),
        "capacity": sf.capacity_clean.notna() & ~flags.map(lambda s: bool(s & {"capacity_implausible", "clinic_with_100plus_beds",
                                                                                "capacity_text_disagree", "text_bed_totals_conflict"})),
        "affiliationTypeIds": rec.affiliationTypeIds.map(nonempty_list),
        "area": pd.to_numeric(rec.area, errors="coerce").gt(0),
        "acceptsVolunteers": rec.acceptsVolunteers.isin(["true", "false"]),
    }


def run():
    raw = io.load("facilities")
    N = len(raw)
    ids = set(io.load("location", ["unique_id"]).unique_id)
    rec = raw[raw.unique_id.isin(ids)].drop_duplicates("unique_id").set_index("unique_id")
    masks = usable_masks(rec)
    rows = []
    for c, m in masks.items():
        k_rep = int(raw[c].notna().sum())
        k_val = int((~rec[c].isna() & ~rec[c].astype(str).str.strip().isin(NULLS)).sum())
        k_use = int(m.fillna(False).astype(bool).sum())
        r = dict(field=c, label=LABELS.get(c, c), n=N, reported=k_rep, has_value=k_val, usable=k_use,
                 rule=USABLE_RULES[c])
        for key in ("reported", "has_value", "usable"):
            p, lo, hi = S.wilson(r[key], N)
            r.update({f"{key}_rate": p, f"{key}_lo": lo, f"{key}_hi": hi})
        rows.append(r)
    d = pd.DataFrame(rows).sort_values("usable_rate").reset_index(drop=True)
    d["gap_pts"] = (d.reported_rate - d.usable_rate) * 100

    fig, ax = S.new_figure(size=(12, 8.6))
    y = np.arange(len(d))
    ax.hlines(y, d.usable_rate * 100, d.reported_rate * 100, color=S.AXIS, lw=2.2, zorder=1)
    specs = [("reported", "Coverage table (not SQL NULL)", S.SEMANTIC["not_verified"], "o"),
             ("has_value", "Has a value (no 'null' string, no duplicate row)", S.SEMANTIC["likely"], "o"),
             ("usable", "Usable for a referral (passes its check)", S.SEMANTIC["verified"], "o")]
    for key, lab, col, mk in specs:
        ax.scatter(d[f"{key}_rate"] * 100, y, s=70, color=col, edgecolor=S.SURFACE, linewidth=1.2, zorder=3 + (key == "usable"),
                   label=lab)
    for yi, r in d.iterrows():
        ax.annotate(f"{r.usable_rate * 100:.0f}%", (r.usable_rate * 100, yi), xytext=(-8, 0), textcoords="offset points",
                    ha="right", va="center", fontsize=10, color=S.INK)
        ax.annotate(f"{r.reported_rate * 100:.0f}%", (r.reported_rate * 100, yi), xytext=(8, 0),
                    textcoords="offset points", ha="left", va="center", fontsize=10, color=S.INK_2)
    ax.set_yticks(y, d.label)
    ax.set_xlim(-8, 112)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_ylim(-0.7, len(d) - 0.3)
    ax.set_xlabel(f"Share of the {N:,} raw rows (%). Census of the file: 95% Wilson intervals are within +/-1 point")
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=3, fontsize=10.5, handletextpad=0.3)
    big = d.sort_values("gap_pts", ascending=False).head(3)
    full = int((d.reported_rate > 0.95).sum())
    dd = d.set_index("field")
    S.fig_title(fig, f"A COUNT(column) coverage table shows all {len(d)} fields at least "
                     f"{np.floor(d.reported_rate.min() * 1000) / 10:.1f}% filled, because 'null' is stored as text; "
                     f"usable values: official website {dd.loc['officialWebsite'].usable_rate * 100:.0f}%, "
                     f"year established {dd.loc['yearEstablished'].usable_rate * 100:.0f}%, "
                     f"bed capacity {dd.loc['capacity'].usable_rate * 100:.0f}%")
    io.note(fig, "Reported = COUNT(column) on data/raw/facilities.parquet; the 'null' string encodings are listed in "
                 "data/raw/PROFILE.json. Has a value = one of the 9,959 well-formed de-duplicated records and not a null "
                 "encoding. Usable checks: derived/v1/record_trust.parquet (phone, email, website), "
                 "derived/v1/facility_location.parquet (coordinates), audit/geo/facility_geo.parquet (postcode), "
                 "audit/scale/scale_flags.parquet (year, doctors, beds, type), audit/provenance/q2_records.parquet "
                 "(description). Rules per field in out/s5_coverage.csv.", width=185)
    io.write_csv(d, "s5_coverage")
    alt = ("Dot plot of 19 fields, each with three rates over the 10,088 raw rows: what a coverage table reports "
           "(not SQL NULL), the share that has a real value, and the share that passes a usability check. "
           + "; ".join(f"{r.label}: reported {r.reported_rate * 100:.0f}%, usable {r.usable_rate * 100:.0f}%"
                       for r in big.itertuples())
           + f". {full} fields look more than 95% complete in a coverage table because 'null' is stored as text.")
    S.save(fig, io.out("s5_coverage"), alt)
    print("s5", d[["field", "reported", "has_value", "usable"]].to_string())
    return d


if __name__ == "__main__":
    run()
