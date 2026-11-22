"""Shared loaders for the provenance audit. Local snapshot only, no warehouse calls."""
import json
import os
import re
from urllib.parse import urlparse

import duckdb
import pandas as pd

_ROOT = os.environ.get("DATATHON_ROOT", os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../..")))
_DATA = os.environ.get("DATATHON_DATA_ROOT", os.path.join(_ROOT, "data"))
RAW = os.path.join(_DATA, "raw")
OUT = os.path.dirname(os.path.abspath(__file__))
UUID_RE = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


def facilities():
    """9,970 well-formed rows (UUID id and source='kie'), per the snapshot profile, minus 11
    exact duplicate rows (same unique_id, every column equal): 9,959 rows."""
    df = duckdb.sql(
        f"select * from '{RAW}/facilities.parquet' "
        f"where source='kie' and regexp_matches(unique_id, '{UUID_RE}')"
    ).df()
    return df.drop_duplicates().reset_index(drop=True)


def pincodes():
    return pd.read_parquet(f"{RAW}/india_post_pincode_directory.parquet")


def nfhs():
    return pd.read_parquet(f"{RAW}/nfhs_5_district_health_indicators.parquet")


def jlist(s):
    """JSON-array string -> list of non-empty strings. Null-like values -> []."""
    if not isinstance(s, str) or not s.startswith("["):
        return []
    try:
        v = json.loads(s)
    except ValueError:
        return []
    return [x.strip() for x in v if isinstance(x, str) and x.strip()]


def host(url):
    u = url if "://" in url else "http://" + url
    try:
        h = urlparse(u).netloc.lower().split(":")[0]
    except ValueError:  # a few malformed URLs, e.g. bracketed hosts
        h = re.sub(r"^[a-z]+://", "", u.lower()).split("/")[0].strip("[]\"'")
    return h[4:] if h.startswith("www.") else h


CANON_STATES = [
    "ANDAMAN AND NICOBAR ISLANDS", "ANDHRA PRADESH", "ARUNACHAL PRADESH", "ASSAM", "BIHAR",
    "CHANDIGARH", "CHHATTISGARH", "DELHI", "GOA", "GUJARAT", "HARYANA", "HIMACHAL PRADESH",
    "JAMMU AND KASHMIR", "JHARKHAND", "KARNATAKA", "KERALA", "LADAKH", "LAKSHADWEEP",
    "MADHYA PRADESH", "MAHARASHTRA", "MANIPUR", "MEGHALAYA", "MIZORAM", "NAGALAND", "ODISHA",
    "PUDUCHERRY", "PUNJAB", "RAJASTHAN", "SIKKIM", "TAMIL NADU", "TELANGANA",
    "THE DADRA AND NAGAR HAVELI AND DAMAN AND DIU", "TRIPURA", "UTTAR PRADESH", "UTTARAKHAND",
    "WEST BENGAL",
]
STATE_ALIASES = {
    "TAMILNADU": "TAMIL NADU", "ORISSA": "ODISHA", "PONDICHERRY": "PUDUCHERRY",
    "U.T OF PUDUCHERRY": "PUDUCHERRY", "JAMMU & KASHMIR": "JAMMU AND KASHMIR",
    "J&K": "JAMMU AND KASHMIR", "KASHMIR": "JAMMU AND KASHMIR", "CHATTISGARH": "CHHATTISGARH",
    "CG": "CHHATTISGARH", "UP": "UTTAR PRADESH", "U.P.": "UTTAR PRADESH", "U.P": "UTTAR PRADESH",
    "UTTARPRADESH": "UTTAR PRADESH", "UTTAR PRADES H": "UTTAR PRADESH", "MP": "MADHYA PRADESH",
    "M.P.": "MADHYA PRADESH", "MADHYAPRADESH": "MADHYA PRADESH", "MADHYA": "MADHYA PRADESH",
    "NCT OF DELHI": "DELHI", "NCT DELHI": "DELHI", "NCT": "DELHI", "NEW DELHI": "DELHI",
    "DELHI NCR": "DELHI", "DELHI/NCR": "DELHI", "DL": "DELHI", "PUNJAB REGION": "PUNJAB",
    "GJ": "GUJARAT", "MH": "MAHARASHTRA", "TS": "TELANGANA", "TELENGANA": "TELANGANA",
    "BR": "BIHAR", "UTTRANCHAL": "UTTARAKHAND", "UTTARANCHAL": "UTTARAKHAND", "U.K.": "UTTARAKHAND",
    "CHANDIGARH (UT)": "CHANDIGARH", "DAMAN AND DIU": "THE DADRA AND NAGAR HAVELI AND DAMAN AND DIU",
    "DADRA AND NAGAR HAVELI AND DAMAN AND DIU": "THE DADRA AND NAGAR HAVELI AND DAMAN AND DIU",
    "DADRA & NAGAR HAVELI & DAMAN & DIU": "THE DADRA AND NAGAR HAVELI AND DAMAN AND DIU",
}


def norm_state(s):
    """Stated state -> canonical PIN-directory state name, or None when it is not a state
    (about 2% of rows hold a city or district here). 'X, State' takes the last part."""
    if not isinstance(s, str) or s.strip().lower() in ("", "null"):
        return None
    t = re.sub(r"\s+", " ", s.strip().upper())
    for cand in (t, t.split(",")[-1].strip()):
        cand = cand.replace(" STATE", "")
        if cand in CANON_STATES:
            return cand
        if cand in STATE_ALIASES:
            return STATE_ALIASES[cand]
    return None


def norm_pin(z):
    if not isinstance(z, str):
        return None
    d = re.sub(r"\s", "", z)
    return int(d) if re.fullmatch(r"[1-9][0-9]{5}", d) else None


def pin_states():
    """pincode -> set of directory statenames (excluding the 'NA' placeholder)."""
    p = pincodes()
    p = p[p.statename != "NA"]
    return p.groupby("pincode").statename.agg(lambda s: set(s)).to_dict()
