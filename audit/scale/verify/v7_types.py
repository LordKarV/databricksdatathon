"""V7: S7, S8, S9. Type, operator, organization_type, affiliation, name-vs-type, veterinary (own regexes)."""
from v_common import con

c = con()
q = lambda s: c.execute(s).fetchall()
print("5803aea6 text:", q("select regexp_extract_all(description || ' ' || capability, '[^.\"]{0,40}(?:21 doctors|0 beds)[^.\"]{0,30}') from w where unique_id like '5803aea6%'"))
print("facilityTypeId:", q("select coalesce(facilityTypeId,'<NULL>'), count(*) from w group by 1 order by 2 desc"))
print("operatorTypeId:", q("select coalesce(operatorTypeId,'<NULL>'), count(*) from w group by 1 order by 2 desc"))
print("organization_type:", q("select organization_type, count(*) from w group by 1"))
c.execute("create temp table n as select *, lower(name) ln from w")
print("hospital-named typed:", q("select facilityTypeId, count(*) from n where regexp_matches(ln, '\\bhospitals?\\b') group by 1 order by 2 desc"))
print("nursing home typed:", q("select facilityTypeId, count(*) from n where ln like '%nursing home%' group by 1 order by 2 desc"))
print("clinic-only typed hospital:", q("select count(*) from n where regexp_matches(ln, '\\b(poly)?clinics?\\b') and not regexp_matches(ln, '\\bhospitals?\\b') and facilityTypeId='hospital'"))
print("lab/imaging no hospital word typed hospital:", q("""select count(*) from n where regexp_matches(ln, 'diagnostic|\\blabs?\\b|laborator|patholog|\\bimaging\\b|\\bscans?\\b|radiolog')
   and not regexp_matches(ln, '\\bhospitals?\\b') and facilityTypeId='hospital'"""))
# dental: denominators matter. dental-named total, typed dentist, typed clinic, typed hospital
print("dental-named (no hospital word) by type:", q("""select facilityTypeId, count(*) from n where regexp_matches(ln, '\\bdental\\b|dentist|\\bteeth\\b|\\btooth\\b|\\bsmile\\b|orthodont')
   and not regexp_matches(ln, '\\bhospitals?\\b') group by 1 order by 2 desc"""))
print("dental-named strict (dental|dentist only) by type:", q("""select facilityTypeId, count(*) from n where regexp_matches(ln, '\\bdental\\b|dentist') group by 1 order by 2 desc"""))
print("'smile' only (no dental word) names, sample:", q("""select name, facilityTypeId from n where regexp_matches(ln, '\\bsmile\\b') and not regexp_matches(ln, 'dental|dentist|teeth|tooth|orthodont') limit 12"""))
print("dentist-typed total and share named dental:", q("""select count(*), count(*) filter (where regexp_matches(ln,'dental|dentist|teeth|tooth|orthodont|smile|implant|ortho')) from n where facilityTypeId='dentist'"""))
# veterinary
for r in q("""select substr(unique_id,1,8), name, facilityTypeId, address_city from n where regexp_matches(ln, '\\b(pets?|veterinary|vet|animal|canine|feline|cattle|livestock)\\b')
   and not regexp_matches(ln, '\\bpet[- ]?(ct|scan|mri)\\b|pet\\s*/\\s*ct') order by name"""):
    print("VET?", r)
print("vet via specialties/description (veterinary word):", q("""select count(*) from n where (lower(description) like '%veterinar%' or lower(specialties) like '%veterinar%' or lower(capability) like '%veterinar%')"""))
for r in q("""select substr(unique_id,1,8), name, facilityTypeId, substr(description,1,120) from n where (lower(description) like '%veterinar%' or lower(capability) like '%veterinar%' or lower(capability) like '%for pets%' or lower(capability) like '%animal%') and not regexp_matches(ln, '\\b(pets?|veterinary|vet|animal)\\b') limit 12"""):
    print("VET-text", r)
# operator vs government names (own narrower regex)
print("gov-named operator:", q("""select operatorTypeId, count(*) from n where regexp_matches(ln, '\\bgovt\\.?\\b|\\bgovernment\\b|\\bdistrict hospital\\b|\\bcivil hospital\\b|\\baiims\\b|\\besi\\b|\\besic\\b|primary health|community health') group by 1 order by 2 desc"""))
# affiliation
c.execute("""create temp table a as select unique_id, operatorTypeId op, list_filter(from_json(affiliationTypeIds,'["VARCHAR"]'), lambda x: x is not null and trim(x)<>'') l, name, description from w""")
print("affiliation filled / dup:", q("select count(*) filter (where len(l)>0), count(*) filter (where len(l)>len(list_distinct(l))), count(*) from a"))
print("affil values:", q("select v, count(*) from (select unnest(list_distinct(l)) v from a) group by 1 order by 2 desc limit 15"))
print("government affil by operator:", q("select op, count(*) from a where list_contains(l,'government') group by 1 order by 2 desc"))
for r in q("select name, op, substr(description,1,140) from a where list_contains(l,'government') and op='private' order by hash(unique_id) limit 6"):
    print("GOVAFF", r)
