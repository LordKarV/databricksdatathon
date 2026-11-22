"""Location-side merge detector: a record whose own address/description text carries a 6-digit PIN
from a different postal district (first 3 digits) than its zip field, or whose source URLs name
more than one city slug on justdial/practo. Writes merge_signal.parquet and prints counts."""
import json
import os
import re
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geo_common import GEO, load_facilities, parse_pin

f = load_facilities()
g = pd.read_parquet(GEO / "facility_geo.parquet").drop_duplicates("unique_id").set_index("unique_id")  # 11 unique_ids occur twice
PIN_RE = re.compile(r"(?<!\d)([1-9]\d{2}\s?\d{3})(?!\d)")
SLUG_RE = re.compile(r"(?:justdial\.com|practo\.com)/([a-z\-]+)/", re.I)
SKIP = {"doctor", "doctors", "clinic", "hospital", "consult", "search", "providers", "india"}


def text_pins(r):
    t = " ".join(str(x) for x in [r.address_line1, r.address_line2, r.address_line3, r.description] if x)
    return {int(m.replace(" ", "")) for m in PIN_RE.findall(t)}


def url_cities(s):
    try:
        urls = json.loads(s) if s and s.startswith("[") else []
    except ValueError:
        return set()
    return {m.lower() for u in urls if u for m in SLUG_RE.findall(u) if m.lower() not in SKIP}


f["pin"] = f.address_zipOrPostcode.map(parse_pin)
f["text_pins"] = f.apply(text_pins, axis=1)
f["other_pin_district"] = [any(p // 1000 != z // 1000 for p in tp) if pd.notna(z) else False for tp, z in zip(f.text_pins, f.pin)]
f["url_cities"] = f.source_urls.map(url_cities)
f["multi_url_city"] = f.url_cities.map(len) > 1
f["d_pin_km"] = f.unique_id.map(g.d_pin_km)
st = {
    "facilities": len(f),
    "text_has_other_postal_district_pin": int(f.other_pin_district.sum()),
    "source_urls_multi_city": int(f.multi_url_city.sum()),
    "either": int((f.other_pin_district | f.multi_url_city).sum()),
    "far_gt50_among_either": int(((f.other_pin_district | f.multi_url_city) & (f.d_pin_km > 50)).sum()),
    "far_gt50_among_neither": int((~(f.other_pin_district | f.multi_url_city) & (f.d_pin_km > 50)).sum()),
    "neither": int((~(f.other_pin_district | f.multi_url_city)).sum()),
}
print(json.dumps(st, indent=1))
f[["unique_id", "pin", "other_pin_district", "multi_url_city", "d_pin_km"]].assign(
    text_pins=f.text_pins.map(sorted).map(str), url_cities=f.url_cities.map(sorted).map(str)).to_parquet(GEO / "merge_signal.parquet", index=False)
(GEO / "merge_signal_stats.json").write_text(json.dumps(st, indent=1))
print(f[f.multi_url_city].sample(8, random_state=1)[["name", "address_city", "url_cities", "d_pin_km"]].to_string())
