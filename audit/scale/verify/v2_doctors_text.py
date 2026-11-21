"""V2: S2 checks. Read cited one-doctor large rows; independent doctor-count-in-text agreement."""
import json, re
from v_common import con

c = con()
for uid in ["b5a57699-76c4-4ba4-9936-713c233e752a", "9790323a-5717-4137-abe6-e679f7980e50"]:
    r = c.execute("select name, address_city, numberDoctors, capacity, description from w where unique_id=?", [uid]).fetchone()
    print(r[:4], "|", r[4][:300])
print("5803aea6:", c.execute("select unique_id, name, numberDoctors, capacity from w where unique_id like '5803aea6%'").fetchall())
# five self-picked one-doctor rows with capacity >= 300
for r in c.execute("select name, address_city, capacity, specialties, source_urls from w where nnum(numberDoctors)=1 and nnum(capacity)>=300 order by hash(unique_id) limit 6").fetchall():
    print("pick:", r[0], r[1], r[2], "urls:", len(json.loads(r[4])) if r[4] and r[4].startswith("[") else r[4])

# independent extractor: an integer directly followed (optionally via 1-2 adjectives) by a doctor noun
RX = re.compile(r"\b(\d{1,3}(?:,\d{3})*|\d+)\s*\+?\s+(?:[a-z-]+\s+){0,2}?(?:doctors|doctor|physicians|consultants|specialists|surgeons|medical officers)\b", re.I)
rows = c.execute("select numberDoctors, description, capability, procedure, equipment from w where nnum(numberDoctors) is not null").fetchall()
tot = agree = 0
for nd, desc, *arrs in rows:
    parts = [desc or ""]
    for a in arrs:
        try:
            x = json.loads(a) if a else []
            parts += [s for s in x if isinstance(s, str)] if isinstance(x, list) else []
        except ValueError:
            pass
    ns = {int(m.group(1).replace(",", "")) for m in RX.finditer(" . ".join(parts))}
    if ns:
        tot += 1
        agree += int(nd) in ns
print(f"doctor field equals a text count: {agree}/{tot} = {agree/tot:.3f}")
