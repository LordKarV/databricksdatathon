"""V10: S10 web-presence fields, plus S9 gov-named private rows."""
from v_common import con

c = con()
q = lambda s: c.execute(s).fetchall()
print("gov-named private:", q("""select name, address_city from w where operatorTypeId='private' and regexp_matches(lower(name), '\\bgovt\\.?\\b|\\bgovernment\\b|\\bdistrict hospital\\b|\\bcivil hospital\\b|\\baiims\\b|\\besi\\b|\\besic\\b|primary health|community health')"""))
for col in ["recency_of_page_update", "post_metrics_most_recent_social_media_post_date"]:
    print(col, q(f"""select count(*) filter (where not isnullish({col})), count(*) filter (where try_strptime({col}, '%Y-%m-%d') is not null),
      count(*) filter (where not isnullish({col}) and try_strptime({col}, '%Y-%m-%d') is null),
      min(try_strptime({col}, '%Y-%m-%d')), max(try_strptime({col}, '%Y-%m-%d')),
      count(*) filter (where try_strptime({col}, '%Y-%m-%d') between '2025-12-01' and '2025-12-31 23:59'),
      count(*) filter (where year(try_strptime({col}, '%Y-%m-%d'))=2025),
      count(*) filter (where try_strptime({col}, '%Y-%m-%d') > '2025-12-31 23:59') from w"""))
    print("  top dates:", q(f"select {col}, count(*) from w where try_strptime({col}, '%Y-%m-%d') is not null group by 1 order by 2 desc limit 6"))
    print("  by year:", q(f"select year(try_strptime({col}, '%Y-%m-%d')) y, count(*) from w where try_strptime({col}, '%Y-%m-%d') is not null group by 1 order by 1 desc limit 6"))
print("future page date:", q("select unique_id, name, recency_of_page_update from w where try_strptime(recency_of_page_update, '%Y-%m-%d') > '2025-12-31'"))
print("booleans:", q("select affiliated_staff_presence, count(*) from w group by 1 order by 2 desc"), q("select custom_logo_presence, count(*) from w group by 1 order by 2 desc"))
c.execute("create temp table e as select *, nnum(engagement_metrics_n_followers) fo, nnum(post_metrics_post_count) pc, nnum(distinct_social_media_presence_count) smc, try_strptime(post_metrics_most_recent_social_media_post_date,'%Y-%m-%d') pd from w")
print("followers odd values:", q("select count(*) filter (where not isnullish(engagement_metrics_n_followers) and fo is null), list(distinct engagement_metrics_n_followers) filter (where not isnullish(engagement_metrics_n_followers) and fo is null)[1:8] from e"))
print("followers >=1000, multiple of 100:", q("select count(*) filter (where fo>=1000), count(*) filter (where fo>=1000 and fo%100=0) from e"))
print("followers >=1000 exact multiples of 1000 / 10000:", q("select count(*) filter (where fo>=1000 and fo%1000=0), count(*) filter (where fo>=10000 and fo%10000=0) from e"))
print("non-round >=10000 shared:", q("""with b as (select fo, count(*) over (partition by fo) k from e where fo>=10000 and fo%1000<>0) select count(*), count(*) filter (where k>=2) from b"""))
print("182277:", q("select name, address_city from e where fo=182277"))
print("4756342:", q("select name, address_city from e where fo=4756342"))
print("top followers:", q("select name, fo from e order by fo desc nulls last limit 4"))
print("post_count 0 with date; post_count filled:", q("select count(*) filter (where pc=0 and pd is not null), count(*) filter (where pc is not null), count(*) filter (where pc=0) from e"))
print("website share by social count:", q("""select case when smc=0 then '0' when smc between 1 and 6 then '1-6' when smc>=7 then '7+' else 'na' end b, count(*),
   round(100*avg(case when isnullish(officialWebsite) then 0 else 1 end),1) from e group by 1 order by 1"""))
