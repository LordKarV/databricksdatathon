"""Same SQL as v_warehouse.sh on the local snapshot, for a side-by-side check."""
from v_common import con
c = con()
print(c.execute("""select count(*), count(*) filter (where numberDoctors='1'), count(*) filter (where regexp_full_match(numberDoctors,'[0-9]+')),
 count(*) filter (where regexp_full_match(capacity,'[0-9]+')), count(*) filter (where regexp_full_match(yearEstablished,'[0-9]+')),
 count(*) filter (where try_cast(numberDoctors as bigint)>1000), count(*) filter (where facilityTypeId='clinic' and try_cast(capacity as bigint)>=100),
 count(*) filter (where affiliationTypeIds like '%"government"%' and operatorTypeId='private'),
 count(*) filter (where post_metrics_most_recent_social_media_post_date like '2026-%'), count(*) filter (where post_metrics_most_recent_social_media_post_date like '2025-%'),
 count(*) filter (where affiliated_staff_presence='true') from w""").fetchall())
