"""Shared loader and normalizers for the identity audit. Local snapshot only."""
import json, re, math
import duckdb, pandas as pd

D = "/Users/karthikvattem/projects/datathon/data/raw/"
OUT = "/Users/karthikvattem/projects/datathon/audit/identity/out/"
UUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
NULLS = {None, "", "null", "NULL", "[]", '[""]', "[null]"}


def parse_list(v):
    if not isinstance(v, str) or v in NULLS:
        return []
    try:
        x = json.loads(v)
    except Exception:
        return [v]
    if not isinstance(x, list):
        x = [x]
    return [str(s).strip() for s in x if s is not None and str(s).strip()]


def clean(v):
    return None if not isinstance(v, str) or v in NULLS else v


def load():
    """Well-formed rows only (UUID unique_id and source='kie'): 9970 rows."""
    df = duckdb.sql(f"""select * from '{D}facilities.parquet'
        where regexp_matches(unique_id, '{UUID}') and source = 'kie'""").df()
    for c in ["phone_numbers", "websites", "procedure", "equipment", "capability",
              "specialties", "source_urls"]:
        df[c + "_l"] = df[c].map(parse_list)
    for c in ["officialPhone", "officialWebsite", "email", "address_city",
              "address_zipOrPostcode", "numberDoctors", "capacity", "facilityTypeId"]:
        df[c] = df[c].map(clean)
    df["pin"] = df.address_zipOrPostcode.map(norm_pin)
    df["nname"] = df.name.map(norm_name)
    df["ncity"] = df.address_city.fillna("").str.lower().str.replace(r"[^a-z]", "", regex=True)
    return df


STOP = r"\b(the|pvt|private|ltd|limited|llp|and|of|dr|drs)\b"


def norm_name(s):
    s = (s if isinstance(s, str) else "").lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(STOP, " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_pin(v):
    m = re.search(r"\b([1-9]\d{5})\b", re.sub(r"(\d{3}) (\d{3})", r"\1\2", str(v or "")))
    return m.group(1) if m else None


def norm_phone(p):
    """Return (digits, kind). kind in mobile, landline, tollfree, invalid.
    Indian mobiles: 10 digits starting 6-9. Landline: STD code + number = 10 digits
    starting 1-5 (after dropping +91 / leading 0). Toll free: 1800/1860."""
    d = re.sub(r"\D", "", p if isinstance(p, str) else "")
    d = d[2:] if d.startswith("91180") or d.startswith("91186") else d
    if d.startswith("1800") or d.startswith("1860"):
        return d, "tollfree"
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    elif len(d) == 11 and d.startswith("0"):
        d = d[1:]
    if len(d) != 10:
        return d, "invalid"
    if d[0] in "6789":
        return d, "mobile"
    if d[0] in "12345":
        return d, "landline"
    return d, "invalid"


def domain(u):
    u = (u if isinstance(u, str) else "").strip().lower()
    u = re.sub(r"^[a-z]+://", "", u).split("/")[0].split("?")[0]
    u = re.sub(r"^www\d?\.", "", u)
    return u or None


def haversine(a1, o1, a2, o2):
    r = math.pi / 180
    h = (math.sin((a2 - a1) * r / 2) ** 2 +
         math.cos(a1 * r) * math.cos(a2 * r) * math.sin((o2 - o1) * r / 2) ** 2)
    return 12742 * math.asin(math.sqrt(h))


STATE_ALIAS = {
    "tamilnadu": "tamil nadu", "orissa": "odisha", "up": "uttar pradesh", "u p": "uttar pradesh",
    "uttarpradesh": "uttar pradesh", "uttar prades h": "uttar pradesh", "jammu kashmir": "jammu and kashmir",
    "jammu and kashmir": "jammu and kashmir", "pondicherry": "puducherry", "chattisgarh": "chhattisgarh",
    "punjab region": "punjab", "new delhi": "delhi", "nct of delhi": "delhi", "nct delhi": "delhi",
    "delhi ncr": "delhi", "nct": "delhi", "madhyapradesh": "madhya pradesh", "m p": "madhya pradesh",
    "mp": "madhya pradesh", "telengana": "telangana", "ts": "telangana", "uttranchal": "uttarakhand",
    "uttaranchal": "uttarakhand", "gj": "gujarat", "mh": "maharashtra", "br": "bihar", "dl": "delhi",
    "cg": "chhattisgarh", "chandigarh ut": "chandigarh", "west tripura": "tripura",
    "dadra and nagar haveli and daman and diu": "the dadra and nagar haveli and daman and diu",
    "daman and diu": "the dadra and nagar haveli and daman and diu",
}


def pin_ref():
    """PIN -> (modal state, median lat, median lon) from the India Post directory."""
    p = duckdb.sql(f"""select cast(pincode as varchar) pin, lower(statename) st,
        try_cast(latitude as double) la, try_cast(longitude as double) lo
        from '{D}india_post_pincode_directory.parquet'""").df()
    st = p.groupby("pin").st.agg(lambda s: s.mode().iat[0])
    g = p[(p.la.between(6, 38)) & (p.lo.between(68, 98))].groupby("pin")[["la", "lo"]].median()
    return st.to_dict(), g


def norm_state(s, valid):
    t = re.sub(r"[^a-z ]", " ", (s or "").lower().replace("&", " and "))
    t = re.sub(r"\s+", " ", t).strip()
    t = STATE_ALIAS.get(t, t)
    return t if t in valid else None


if __name__ == "__main__":  # self-check of the normalizers
    assert norm_phone("+919693969347") == ("9693969347", "mobile")
    assert norm_phone("09814198145") == ("9814198145", "mobile")
    assert norm_phone("+911143364336") == ("1143364336", "landline")
    assert norm_phone("+9118001031041")[1] == "tollfree"
    assert norm_phone("+9779700222939")[1] == "invalid"
    assert norm_pin("629 165") == "629165" and norm_pin("null") is None
    assert domain("https://www.Apollo247.com/clinic?x=1") == "apollo247.com"
    assert norm_name("Dr. Lad's Navjeevan Hospital Pvt Ltd") == "lad s navjeevan hospital"
    print("ok")
