"""Shared loaders and normalisers for the location-consistency audit."""
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/karthikvattem/projects/datathon")
GEO = ROOT / "audit/geo"
FAC = ROOT / "data/raw/facilities.parquet"
PIN_DIR = ROOT / "data/raw/india_post_pincode_directory.parquet"
NFHS = ROOT / "data/raw/nfhs_5_district_health_indicators.parquet"

# India Post postal zones by first PIN digit (9 = Army Postal Service)
ZONE = {
    1: {"DELHI", "HARYANA", "PUNJAB", "HIMACHAL PRADESH", "JAMMU AND KASHMIR", "CHANDIGARH", "LADAKH"},
    2: {"UTTAR PRADESH", "UTTARAKHAND"},
    3: {"RAJASTHAN", "GUJARAT", "THE DADRA AND NAGAR HAVELI AND DAMAN AND DIU"},
    4: {"MAHARASHTRA", "MADHYA PRADESH", "GOA", "CHHATTISGARH"},
    5: {"ANDHRA PRADESH", "TELANGANA", "KARNATAKA"},
    6: {"TAMIL NADU", "KERALA", "PUDUCHERRY", "LAKSHADWEEP"},
    7: {"WEST BENGAL", "ODISHA", "ASSAM", "ARUNACHAL PRADESH", "MANIPUR", "MEGHALAYA", "MIZORAM",
        "NAGALAND", "TRIPURA", "SIKKIM", "ANDAMAN AND NICOBAR ISLANDS"},
    8: {"BIHAR", "JHARKHAND"},
}

# hand-written aliases seen in address_stateOrRegion (lowercased, punctuation stripped)
STATE_ALIAS = {
    "tamilnadu": "TAMIL NADU", "orissa": "ODISHA", "up": "UTTAR PRADESH", "u p": "UTTAR PRADESH",
    "uttarpradesh": "UTTAR PRADESH", "uttar prades h": "UTTAR PRADESH", "mp": "MADHYA PRADESH",
    "m p": "MADHYA PRADESH", "madhyapradesh": "MADHYA PRADESH", "madhya": "MADHYA PRADESH",
    "chattisgarh": "CHHATTISGARH", "cg": "CHHATTISGARH", "jammu kashmir": "JAMMU AND KASHMIR",
    "jammu j k": "JAMMU AND KASHMIR", "kashmir": "JAMMU AND KASHMIR", "srinagar kashmir": "JAMMU AND KASHMIR",
    "pondicherry": "PUDUCHERRY", "u t of puducherry": "PUDUCHERRY", "nct of delhi": "DELHI",
    "nct delhi": "DELHI", "nct": "DELHI", "delhi ncr": "DELHI", "new delhi": "DELHI", "dl": "DELHI",
    "east delhi": "DELHI", "west delhi": "DELHI", "south delhi": "DELHI", "north west delhi": "DELHI",
    "south east delhi area": "DELHI", "ts": "TELANGANA", "telengana": "TELANGANA", "gj": "GUJARAT",
    "mh": "MAHARASHTRA", "ms": "MAHARASHTRA", "br": "BIHAR", "uttaranchal": "UTTARAKHAND",
    "uttranchal": "UTTARAKHAND", "uk": "UTTARAKHAND", "u k": "UTTARAKHAND", "ut": "UTTARAKHAND",
    "punjab region": "PUNJAB", "chandigarh ut": "CHANDIGARH",
    "andaman and nicobar islands": "ANDAMAN AND NICOBAR ISLANDS",
    "dadra nagar haveli daman diu": "THE DADRA AND NAGAR HAVELI AND DAMAN AND DIU",
    "dadra and nagar haveli and daman and diu": "THE DADRA AND NAGAR HAVELI AND DAMAN AND DIU",
    "daman and diu": "THE DADRA AND NAGAR HAVELI AND DAMAN AND DIU",
}

# city/district renames and spellings a user may type (alias -> name used in the PIN directory)
CITY_ALIAS = {
    "bombay": "mumbai", "gurgaon": "gurugram", "bangalore": "bengaluru", "madras": "chennai",
    "calcutta": "kolkata", "poona": "pune", "trivandrum": "thiruvananthapuram", "allahabad": "prayagraj",
    "baroda": "vadodara", "mysore": "mysuru", "cochin": "kochi", "benares": "varanasi", "banaras": "varanasi",
    "pondicherry": "puducherry", "mangalore": "mangaluru", "belgaum": "belagavi", "calicut": "kozhikode",
    "vizag": "visakhapatnam", "gauhati": "guwahati", "simla": "shimla", "cawnpore": "kanpur",
    "trichy": "tiruchirappalli", "tanjore": "thanjavur", "ahmedabad": "ahmadabad", "bhubaneshwar": "bhubaneswar",
    "hubli": "dharwad", "gulbarga": "kalaburagi", "bellary": "ballari", "shimoga": "shivamogga",
    "tumkur": "tumakuru", "bijapur": "vijayapura", "kanchipuram": "kancheepuram", "alleppey": "alappuzha",
    "quilon": "kollam", "palghat": "palakkad", "trichur": "thrissur", "cannanore": "kannur",
}


def norm(s) -> str:
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return ""
    s = str(s).lower().replace("&", " and ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


OFFICE_SUFFIX = re.compile(r"\s+(b o|s o|h o|bo|so|ho|po|gpo|ndso|mdg)(\s.*)?$")


def office_base(name: str) -> str:
    """'Navrangpura S.O' -> 'navrangpura'; 'Bank Street SO Central Delhi' -> 'bank street'."""
    return OFFICE_SUFFIX.sub("", norm(name)).strip()


def hav_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def load_facilities() -> pd.DataFrame:
    """Well-formed rows only: UUID unique_id and source='kie' (9,970 rows)."""
    f = pd.read_parquet(FAC)
    ok = f.unique_id.str.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-", na=False) & (f.source == "kie")
    return f[ok].reset_index(drop=True)


def parse_pin(z) -> int | None:
    s = re.sub(r"[\s-]", "", str(z or ""))
    return int(s) if re.fullmatch(r"[1-9]\d{5}", s) else None


def nearest(lat, lon, plat, plon, chunk=400):
    """Index of nearest point (equirectangular argmin, exact haversine distance)."""
    idx = np.empty(len(lat), dtype=int)
    k = np.cos(np.radians(22.0))
    for i in range(0, len(lat), chunk):
        a, b = lat[i:i + chunk, None], lon[i:i + chunk, None]
        idx[i:i + chunk] = np.argmin((a - plat) ** 2 + ((b - plon) * k) ** 2, axis=1)
    return idx, hav_km(lat, lon, plat[idx], plon[idx])


if __name__ == "__main__":
    assert parse_pin("613 007") == 613007 and parse_pin("000000") is None and parse_pin("10") is None
    assert office_base("Navrangpura S.O") == "navrangpura" and office_base("Kair B.O") == "kair"
    assert office_base("Bank Street SO Central Delhi") == "bank street"
    assert round(float(hav_km(28.6, 77.2, 19.07, 72.88))) in range(1140, 1160)
    print("ok")
