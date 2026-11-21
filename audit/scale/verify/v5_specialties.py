"""V5: S5 and S6. Specialty duplication, breadth vs sources vs doctors, over-claim rules. DuckDB JSON functions."""
from v_common import con

c = con()
c.execute("""create temp table s as select unique_id, name, facilityTypeId ft, nnum(numberDoctors) nd, nnum(capacity) cap,
  coalesce(len(list_filter(from_json(specialties, '["VARCHAR"]'), lambda x: x is not null and trim(x) <> '')), 0) n_raw,
  coalesce(len(list_distinct(list_filter(from_json(specialties, '["VARCHAR"]'), lambda x: x is not null and trim(x) <> ''))), 0) n_spec,
  coalesce(len(list_distinct(list_filter(from_json(source_urls, '["VARCHAR"]'), lambda x: x is not null and trim(x) <> ''))), 0) n_urls,
  coalesce(len(from_json(source_urls, '["VARCHAR"]')), 0) n_urls_raw
  from w""")
print("raw items, distinct-per-record, rows with dup:", c.execute("select sum(n_raw), sum(n_spec), count(*) filter (where n_raw>n_spec), count(*) from s").fetchall())
print("vocab:", c.execute("select count(distinct x) from (select unnest(list_distinct(from_json(specialties,'[\"VARCHAR\"]'))) x from w) where x is not null and trim(x)<>''").fetchall())
print("by type p50/p90/max:", c.execute("select ft, count(*), quantile_cont(n_spec,0.5), quantile_cont(n_spec,0.9), max(n_spec) from s group by 1 order by 2 desc").fetchall())
print("url count distribution top:", c.execute("select n_urls_raw, count(*) from s group by 1 order by 2 desc limit 5").fetchall())
print("max urls:", c.execute("select max(n_urls_raw), count(*) filter (where n_urls_raw=50) from s").fetchall())
# rank correlations: on all rows, and on the SAME subset (doctors present) for a fair comparison
print("spearman spec~urls all:", c.execute("select corr(r1, r2) from (select rank() over (order by n_spec) r1, rank() over (order by n_urls) r2 from s)").fetchall())
print("spearman on doctors-present subset (urls, doctors, beds):", c.execute("""select corr(rs, ru), corr(rs, rd) from (select rank() over (order by n_spec) rs,
   rank() over (order by n_urls) ru, rank() over (order by nd) rd from s where nd is not null)""").fetchall())
print("spearman on both nd and cap present (urls, doctors, beds):", c.execute("""select corr(rs, ru), corr(rs, rd), corr(rs, rc), count(*) from (select rank() over (order by n_spec) rs,
   rank() over (order by n_urls) ru, rank() over (order by nd) rd, rank() over (order by cap) rc from s where nd is not null and cap is not null)""").fetchall())
print("median spec by url bucket:", c.execute("""select case when n_urls<=1 then '0-1' when n_urls<=3 then '2-3' when n_urls<=6 then '4-6' when n_urls<=12 then '7-12' else '>12' end b,
   count(*), quantile_cont(n_spec,0.5) from s group by 1 order by 1""").fetchall())
print("1-doctor hospitals with >=20 / >=30:", c.execute("select count(*), count(*) filter (where n_spec>=20), count(*) filter (where n_spec>=30) from s where ft='hospital' and nd=1").fetchall())
c.execute("""create temp table r as select *, n_spec>=30 r1, (ft='clinic' and n_spec>=15) r2, (ft='dentist' and n_spec>=10) r3,
   ((nd<=2 or cap<=30) and n_spec>=15) is true r4, (cap>=200 or nd>=50) is true large from s""")
print("rules r1..r4, union, union minus large, size-rule minus large:", c.execute("""select count(*) filter (where r1), count(*) filter (where r2), count(*) filter (where r3),
  count(*) filter (where r4), count(*) filter (where r1 or r2 or r3 or r4), count(*) filter (where (r1 or r2 or r3 or r4) and not large), count(*) filter (where r4 and not large) from r""").fetchall())
print("cited:", c.execute("select substr(unique_id,1,8), name, ft, nd, cap, n_spec, n_urls from s where substr(unique_id,1,8) in ('f6dd0266','b2ae8404','58242a13','373e1b29','93706a48','51d31015')").fetchall())
# eye/dental subspecialty share among r1 (variants inflate breadth inside one family)
print("rule r1 rows that are eye or dental named:", c.execute("select count(*) filter (where regexp_matches(lower(name), 'eye|nethra|netra|vision|dental|dent')), count(*) from r where r1").fetchall())
