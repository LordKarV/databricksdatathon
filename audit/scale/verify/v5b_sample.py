"""V5b: spec~beds vs spec~urls on capacity-present rows; random hand-check sample of the S6 union minus large."""
from v_common import con

c = con()
c.execute("""create temp table s as select unique_id, name, facilityTypeId ft, nnum(numberDoctors) nd, nnum(capacity) cap,
  list_distinct(list_filter(from_json(specialties, '["VARCHAR"]'), lambda x: x is not null and trim(x) <> '')) sp,
  coalesce(len(list_distinct(from_json(source_urls, '["VARCHAR"]'))), 0) n_urls, description from w""")
c.execute("alter table s add column n_spec int; update s set n_spec = coalesce(len(sp),0)")
print("cap-present: corr(spec,urls), corr(spec,cap), n:", c.execute("""select corr(a,b), corr(a,cc), count(*) from (select rank() over (order by n_spec) a,
  rank() over (order by n_urls) b, rank() over (order by cap) cc from s where cap is not null)""").fetchall())
rows = c.execute("""select substr(unique_id,1,8), name, ft, nd, cap, n_spec, sp, substr(description,1,160) from s
  where (n_spec>=30 or (ft='clinic' and n_spec>=15) or (ft='dentist' and n_spec>=10) or ((nd<=2 or cap<=30) and n_spec>=15))
  and not coalesce(cap>=200 or nd>=50, false) order by hash(unique_id || 'v') limit 12""").fetchall()
for r in rows:
    print("\n", r[:6], "\n  ", r[6][:30], "\n  ", r[7])
