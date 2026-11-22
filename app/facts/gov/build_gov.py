"""Write the small committed inputs of the Area brief (WS4 4b, #140) from git-ignored data under DATATHON_ROOT.

app/facts/build.py reads only these CSVs, so a clean checkout builds the same Area view as a machine that holds
data/external. Run from the repo root when the source data changes, then commit the CSVs:
    DATATHON_ROOT=<folder with data/external> python app/facts/gov/build_gov.py

Outputs (sources and licences in README.md here):
    pin_district_moved.csv  pin, district, state: PINs whose point lies in another LGD district than the one the
                            gazetteer files it under (facts/build.py pin_districts, validation C4)
    district_lgd.csv        district, state (India Post spelling) -> dist_lgd, the LGD code most of its offices carry
    laqshya.csv             LaQshya Maternity OT certificates (NHSRC master data 08-04-2026), one row per facility,
                            with the LGD district viz/geography/s3_csection.py matched it to
    pmndp_state.csv         PMNDP functional dialysis centres per state (NHSRC map table)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

GOV = Path(__file__).resolve().parent
sys.path.insert(0, str(GOV.parents[1]))
from facts import build  # noqa: E402

EXT = build.DATA_ROOT / "data" / "external"
LQ = EXT / "laqshya_master"
PMNDP = EXT / "pmndp_counts_and_state_lists"
LQ_MATCH = build.ROOT / "viz" / "geography" / "data" / "s3_laqshya_match.csv"


def district_lgd() -> pd.DataFrame:
    o = pd.read_parquet(build.LGD_PINS, columns=["district", "statename", "dist_lgd"]).dropna()
    o = o[o.dist_lgd > 0]
    m = o.groupby(["district", "statename"]).dist_lgd.agg(lambda c: int(c.mode()[0])).reset_index()
    return m.rename(columns={"statename": "state"}).sort_values(["state", "district"])


def laqshya() -> pd.DataFrame:
    """One row per facility with a Maternity OT certificate: the certificate the C-section brief names."""
    rows = pd.read_parquet(LQ / "laqshya.parquet")
    rows = rows[rows.dept == "Maternity OT"].set_index("sno")
    fac = pd.read_parquet(LQ / "laqshya_facilities.parquet").dropna(subset=["Maternity OT"])
    match = pd.read_csv(LQ_MATCH).set_index("lq_id")
    out = []
    for f in fac.itertuples(index=False):
        sno = max((s for s in f.snos if s in rows.index), key=lambda s: rows.date_validity[s])
        r = rows.loc[sno]
        m = match.loc[f.lq_id] if f.lq_id in match.index else None
        ok = m is not None and bool(m.matched)
        out.append({"state": f.state, "district": f.district, "lgd_district": m.lgd_dtname if ok else None,
                    "nfhs_state": m.nfhs_state if ok else None, "name": f.name, "facility_type": f.ftype,
                    "department": "Maternity OT", "certified": r.date_result.date(), "valid_to": r.date_validity.date(),
                    "status": r.status})
    return pd.DataFrame(out).sort_values(["state", "district", "name"])


def pmndp() -> pd.DataFrame:
    """NHSRC's PMNDP table (nhsrcindia.org/pmndp-map-table, no date on the page). Not the PMNDP portal's own numbers:
    its terms forbid reproduction without MoHFW permission (external/pmndp_counts_and_state_lists/README.md)."""
    p = pd.read_csv(PMNDP / "pmndp_state_counts.csv")
    fetched = re.match(r"(\d{4}-\d{2}-\d{2})", (PMNDP / "fetch_log.txt").read_text()).group(1)
    return pd.DataFrame({"state_key": p.state_key, "state": p.state_raw,
                         "functional_centres": p.nhsrc_functional_centres,
                         "functional_districts": p.nhsrc_functional_districts,
                         "total_districts": p.nhsrc_total_districts, "fetched": fetched})


def main() -> None:
    if not build.LGD_PINS.is_file():
        raise SystemExit(f"{build.LGD_REL} not found under DATATHON_ROOT or the repo")
    moved = build.pin_districts(build.pins())
    pd.DataFrame([(p, d, s) for p, (d, s) in sorted(moved.items())], columns=["pin", "district", "state"]).to_csv(
        GOV / "pin_district_moved.csv", index=False)
    for name, df in (("district_lgd", district_lgd()), ("laqshya", laqshya()), ("pmndp_state", pmndp())):
        df.to_csv(GOV / f"{name}.csv", index=False)
        print(f"{name}.csv: {len(df)} rows")
    print(f"pin_district_moved.csv: {len(moved)} rows")


if __name__ == "__main__":
    main()
