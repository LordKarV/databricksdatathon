"""V1b: year value distribution (crawl-year artifact check), DY Patil row, read text of doctors>1000 rows."""
import json
from v_common import con

c = con()
print("year top:", c.execute("select nnum(yearEstablished) y, count(*) from w where nnum(yearEstablished) is not null group by 1 order by 2 desc limit 12").fetchall())
print("year>=2020 by year:", c.execute("select nnum(yearEstablished) y, count(*) from w where nnum(yearEstablished)>=2020 group by 1 order by 1").fetchall())
print("DY Patil:", c.execute("select unique_id, name, numberDoctors, capacity from w where name ilike '%patil%' and nnum(numberDoctors)>=500").fetchall())
print("doctors between 500 and 1000:", c.execute("select name, address_city, numberDoctors, capacity from w where nnum(numberDoctors) between 500 and 1000 order by nnum(numberDoctors) desc").fetchall())
rows = c.execute("""select name, numberDoctors, capacity, description, capability from w where nnum(numberDoctors)>1000""").fetchall()
import re
for n, nd, cap, desc, capab in rows:
    txt = (desc or "") + " " + " ".join(json.loads(capab) if capab and capab.startswith("[") else [])
    hits = re.findall(r"[^.]{0,80}\b(?:doctors?|physicians?|specialists?|consultants?)\b[^.]{0,40}", txt, re.I)[:3]
    print("---", n, nd, cap, "|", hits)
