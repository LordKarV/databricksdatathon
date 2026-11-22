# Area brief inputs

Small committed tables that app/facts/build.py reads for the Area page's district brief (WS4 4b, #140), so a clean
checkout builds the same Area view as a machine that holds the git-ignored data/external. Regenerate with
`DATATHON_ROOT=<folder with data/external> python app/facts/gov/build_gov.py` and commit the result.
test_engine.py checks the PIN map against the LGD join whenever the LGD file is present.

| File | Rows | Source | Terms |
|---|---|---|---|
| pin_district_moved.csv | 1,109 | PINs whose point lies in another district than the PIN gazetteer files it under, from the LGD district polygons joined to India Post offices (external/lgd_district_polygons, validation C4) | CC0 1.0, attribution requested: Datameet and ramSeraph/indianopenmaps, from LGD (Government of India) |
| district_lgd.csv | 755 | India Post district name to the LGD district code most of its offices fall in (same join) | as above |
| laqshya.csv | 902 | LaQshya Maternity OT certificates, one row per facility (the latest), from the NHSRC LaQshya master data file dated 08-04-2026 (https://qps.nhsrcindia.org/sites/default/files/2026-04/LaQshya_Master_data-08-04-2026.pdf). `lgd_district` is the LGD district viz/geography/s3_csection.py matched each NHSRC district name to | Source: NHSRC, Ministry of Health and Family Welfare. Reproduced as published, names spelled as in the file; an expired certificate is shown as expired |
| pmndp_state.csv | 36 | Pradhan Mantri National Dialysis Programme, functional centres and districts per state, from NHSRC's table (https://www.nhsrcindia.org/pmndp-map-table, no date on the page, fetched 2026-11-21) | Source: NHSRC, PMNDP data. The PMNDP portal's own numbers are not used: its terms do not allow reproduction |

NHSRC copyright policy (https://www.nhsrcindia.org/copyright-policy): material "may be reproduced free of charge in
any format or media without requiring specific permission", accurately and with the source acknowledged.
The other inputs of the brief are already committed: viz/geography/data/s1_district.csv (WorldPop 2025, CC BY 4.0,
people per LGD district, and dataset listings per million) and s3_district.csv (NFHS-5 district fact sheets,
2019-21). The full licence notes for each source are in external/<source>/README.md.
