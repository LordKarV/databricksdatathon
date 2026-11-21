"""Independent loader for verifying the service-claim audit. Local snapshot only.
Parses JSON arrays in DuckDB (not Python json), so parsing bugs in the finder's common.py would show up as diffs."""
import duckdb

RAW = "/Users/karthikvattem/projects/datathon/data/raw/facilities.parquet"
LISTS = ["procedure", "equipment", "capability", "specialties"]


def arr(c):
    # '[...]' strings -> VARCHAR[]; null-likes and invalid JSON -> empty list; drop null/blank items
    return (f"""coalesce(list_filter(list_transform(
        case when json_valid({c}) and left(trim({c}),1)='[' then from_json({c}, '["VARCHAR"]') end,
        lambda x: trim(x)), lambda x: x is not null and x <> ''), []) as {c}""")


def load(con=None):
    con = con or duckdb.connect()
    q = f"""select unique_id, name, facilityTypeId, address_city, address_stateOrRegion, address_zipOrPostcode,
               capacity, numberDoctors,
               {', '.join(arr(c) for c in LISTS)},
               case when description is null or lower(description)='null' then '' else description end as description
            from '{RAW}'
            where regexp_full_match(unique_id, '[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}')
              and source = 'kie'"""
    return con.sql(q).df()
