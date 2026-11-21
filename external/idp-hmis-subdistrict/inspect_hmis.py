"""Profile the HMIS sub-district subset and check its codes against the LGD archive.

Usage: python -I inspect_hmis.py HMIS_CSV LGD_DIR OUT_JSON
"""
import json
import sys

import duckdb

hmis, lgd, out = sys.argv[1], sys.argv[2], sys.argv[3]
c = duckdb.connect()
c.execute(f"create view h as select * from read_csv('{hmis}', header=true, all_varchar=false)")
q = lambda s: c.execute(s).fetchall()
cols = [r[0] for r in q("select column_name from (describe h)")]
n = q("select count(*) from h")[0][0]
r = {
    "rows": n,
    "columns": len(cols),
    "date_range": q("select min(date)::varchar, max(date)::varchar, count(distinct date) from h")[0],
    "months": [x[0] for x in q("select distinct strftime(date, '%Y-%m') d from h order by d")],
    "sector_counts": dict(q("select sector, count(*) from h group by 1 order by 1")),
    "n_states": q("select count(distinct state_code) from h")[0][0],
    "n_districts": q("select count(distinct district_code) from h")[0][0],
    "n_subdistricts": q("select count(distinct subdistrict_code) from h")[0][0],
    "dup_keys": q("select count(*) from (select date, subdistrict_code, sector, count(*) c from h group by all having c > 1)")[0][0],
    "null_rate": {k: round(q(f'select avg(("{k}" is null)::int) from h')[0][0], 4) for k in cols},
    "negatives": {k: q(f'select count(*) from h where "{k}" < 0')[0][0]
                  for k in cols[9:]},
    "csec_gt_inst_deliv": q("select count(*) from h where csec_total > inst_deliv_csec")[0][0],
    "all_zero_rows": q("select count(*) from h where " + " and ".join(f'coalesce("{k}",0)=0' for k in cols[9:]))[0][0],
    "max_values": {k: q(f'select max("{k}") from h')[0][0] for k in cols[9:]},
    "p999_values": {k: q(f'select quantile_cont("{k}", 0.999) from h')[0][0] for k in cols[9:]},
}
# Are HMIS district/sub-district codes LGD codes? Compare names on shared codes.
c.execute(f"create view ld as select * from '{lgd}/districts.parquet'")
c.execute(f"create view ls as select * from '{lgd}/subdistricts.parquet'")
hd = "select distinct district_code::int dc, district_name dn, state_name sn from h"
r["district_code_in_lgd"] = q(f"select count(*), count(ld.district_code), sum((lower(ld.district_name)=lower(x.dn))::int) from ({hd}) x left join ld on ld.district_code=x.dc")[0]
hs = "select distinct subdistrict_code::int sc, subdistrict_name snm, district_code::int dc from h"
r["subdistrict_code_in_lgd"] = q(f"select count(*), count(ls.subdistrict_code), sum((lower(ls.subdistrict_name)=lower(x.snm))::int), sum((ls.district_code=x.dc)::int) from ({hs}) x left join ls on ls.subdistrict_code=x.sc")[0]
r["district_name_mismatch_examples"] = q(f"select x.dc, x.dn, ld.district_name from ({hd}) x join ld on ld.district_code=x.dc where lower(ld.district_name)<>lower(x.dn) limit 15")
r["subdistrict_name_mismatch_examples"] = q(f"select x.sc, x.snm, ls.subdistrict_name from ({hs}) x join ls on ls.subdistrict_code=x.sc where lower(ls.subdistrict_name)<>lower(x.snm) limit 15")
r["unmapped_district_examples"] = q(f"select x.* from ({hd}) x left join ld on ld.district_code=x.dc where ld.district_code is null limit 15")
r["state_names"] = [x[0] for x in q("select distinct state_name from h order by 1")]
json.dump(r, open(out, "w"), indent=1, default=str)
print(json.dumps({k: v for k, v in r.items() if k not in ("null_rate", "negatives", "max_values", "p999_values")}, default=str, indent=1))
print("nonzero null rates:", {k: v for k, v in r["null_rate"].items() if v})
print("negatives:", {k: v for k, v in r["negatives"].items() if v})
print("max:", r["max_values"])
print("p99.9:", r["p999_values"])
