"""V1: numeric fields parse check and impossible values (S1, S2)."""
from v_common import con

c = con()
q = lambda s: print(c.sql(s).fetchall() if not s.strip().lower().startswith("select *") else c.sql(s))
print("well-formed rows", c.execute("select count(*) from w").fetchone())
for col in ["numberDoctors", "capacity", "yearEstablished"]:
    print(col, c.execute(f"""select count(*) filter (where not isnullish({col})) filled,
        count(*) filter (where not isnullish({col}) and not regexp_full_match(trim({col}), '[0-9]+')) non_digit,
        count(*) filter (where not isnullish({col}) and {col} <> trim({col})) whitespace,
        count(*) filter (where {col} is null) sqlnull, count(*) filter (where {col}='null') lit_null,
        list(distinct {col}) filter (where not isnullish({col}) and not regexp_full_match(trim({col}), '[0-9]+')) odd
        from w""").fetchone())
print(c.execute("""select count(*) filter (where nnum(numberDoctors)=0) d0, count(*) filter (where nnum(numberDoctors)>1000) d1000,
  count(*) filter (where nnum(numberDoctors)>500) d500,
  count(*) filter (where nnum(capacity)=0) c0, count(*) filter (where nnum(capacity)>5000) c5000,
  count(*) filter (where nnum(capacity)>3000) c3000,
  count(*) filter (where nnum(yearEstablished)<1800) y1800, count(*) filter (where nnum(yearEstablished)>2026) y2026,
  count(*) filter (where nnum(yearEstablished)>2025) y2025,
  count(*) filter (where nnum(capacity) between 1900 and 2026) capyear
  from w""").fetchone())
print("distinct union of impossible rows:", c.execute("""select count(*) from w where nnum(numberDoctors)=0 or nnum(numberDoctors)>1000
  or nnum(capacity)=0 or nnum(capacity)>5000 or nnum(yearEstablished)<1800 or nnum(yearEstablished)>2026""").fetchone())
print(c.execute("""select unique_id, name, address_city, numberDoctors, capacity, yearEstablished from w
  where nnum(numberDoctors)>1000 or nnum(capacity)>5000 or nnum(yearEstablished)<1800 or nnum(yearEstablished)>2024 order by name""").df().to_string())
print(c.execute("""select unique_id, name, address_city, numberDoctors, capacity, yearEstablished from w
  where nnum(numberDoctors)=0 or nnum(capacity)=0 order by name""").df().to_string())
# S2
print("doctor value counts", c.execute("select nnum(numberDoctors) v, count(*) n from w where nnum(numberDoctors) is not null group by 1 order by 2 desc limit 6").fetchall())
print("cap>=300 with doctors / doctors=1:", c.execute("""select count(*) filter (where nnum(numberDoctors) is not null),
  count(*) filter (where nnum(numberDoctors)=1) from w where nnum(capacity)>=300""").fetchone())
print("both present / docs<=2 & cap>=200 / docs=1 & cap>=100:", c.execute("""select count(*), count(*) filter (where nnum(numberDoctors)<=2 and nnum(capacity)>=200),
  count(*) filter (where nnum(numberDoctors)=1 and nnum(capacity)>=100) from w where nnum(numberDoctors) is not null and nnum(capacity) is not null""").fetchone())
print("hospital-typed 1-doctor share:", c.execute("""select facilityTypeId, count(*) filter (where nnum(numberDoctors)=1), count(*) filter (where nnum(numberDoctors) is not null) from w group by 1 order by 3 desc""").fetchall())
