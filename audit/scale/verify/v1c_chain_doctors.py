"""V1c: chain-wide doctor counts below the 1,000 cutoff: one value shared by rows of the same brand (first name word) in different cities."""
from v_common import con
c = con()
r = c.execute("""with t as (select name, address_city, nnum(numberDoctors) nd, nnum(capacity) cap, lower(split_part(trim(name),' ',1)) w1 from w where nnum(numberDoctors) between 100 and 1000),
 g as (select w1, nd, count(*) k, count(distinct address_city) cities, list(name || ' / ' || address_city)[1:3] ex from t group by 1,2 having count(distinct address_city)>=2)
 select (select count(*) from t), sum(k), list(w1 || ':' || nd || ':' || k) from g""").fetchall()
print("rows with 100-1000 doctors; rows whose value is shared by same-brand rows in 2+ cities; groups:", r)
print("doctors >= 100 and > 2x beds:", c.execute("select count(*), count(*) filter (where nnum(numberDoctors) > 2*nnum(capacity)) from w where nnum(numberDoctors)>=100 and nnum(capacity) is not null").fetchall())
