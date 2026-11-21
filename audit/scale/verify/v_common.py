"""Independent loader for the verification of the scale audit. Local snapshot only."""
import duckdb

RAW = "/Users/karthikvattem/projects/datathon/data/raw/facilities.parquet"


def con():
    c = duckdb.connect()
    c.sql(f"create view raw as select * from '{RAW}'")
    # well-formed: 36-char lowercase UUID and source='kie'
    c.sql("""create view w as select * from raw
             where source = 'kie' and unique_id similar to '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'""")
    # numeric helper: null-like -> NULL, else try_cast to bigint
    c.sql("""create macro nnum(x) as case when x is null or lower(trim(x)) in ('', 'null', '[]', '[""]', '[null]') then null
             else try_cast(trim(x) as bigint) end""")
    c.sql("""create macro isnullish(x) as x is null or lower(trim(x)) in ('', 'null', '[]', '[""]', '[null]', 'none', 'nan')""")
    return c
