"""Build a size-realistic offline pack: every facility (short id, name, lat, lon, first phone,
city) plus a PIN code -> centroid table, and report raw and gzip sizes.

Run with the project venv (has duckdb): ../../../.venv/bin/python make_pack.py
Writes apps/static/pack.json and outputs/pack_size.json.
ponytail: no per-service flags yet; the model will add a small bitmask per facility
(a few bytes each), so the real pack is this size plus about 10088 * 4 bytes.
"""
import gzip
import json
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
RAW = HERE.parents[2] / "data" / "raw"

fac = duckdb.sql(f"""
  select name, round(latitude, 4) lat, round(longitude, 4) lon,
         coalesce(json_extract_string(phone_numbers, '$[0]'), officialPhone) phone, address_city city
  from '{RAW}/facilities.parquet'
  where latitude is not null and name is not null
""").fetchall()
pins = duckdb.sql(f"""
  select pincode, round(avg(try_cast(latitude as double)), 3), round(avg(try_cast(longitude as double)), 3)
  from '{RAW}/india_post_pincode_directory.parquet'
  where try_cast(latitude as double) between 6 and 38 and try_cast(longitude as double) between 68 and 98
  group by pincode
""").fetchall()

pack = {"snapshot": "2026-11-21", "cols": ["name", "lat", "lon", "phone", "city"],
        "f": [list(r) for r in fac], "pin": {str(p): [la, lo] for p, la, lo in pins}}
raw = json.dumps(pack, separators=(",", ":"), ensure_ascii=False).encode()
(HERE / "apps" / "static").mkdir(exist_ok=True)
(HERE / "apps" / "static" / "pack.json").write_bytes(raw)
sizes = {"facilities": len(fac), "pincodes": len(pins), "raw_bytes": len(raw),
         "gzip6_bytes": len(gzip.compress(raw, 6)),
         "facilities_only_gzip6_bytes": len(gzip.compress(json.dumps(pack["f"], separators=(",", ":")).encode(), 6)),
         "pincodes_only_gzip6_bytes": len(gzip.compress(json.dumps(pack["pin"], separators=(",", ":")).encode(), 6))}
(HERE / "outputs" / "pack_size.json").write_text(json.dumps(sizes, indent=1))
print(sizes)
