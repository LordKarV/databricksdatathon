"""Q4: existence signals (officialWebsite, officialPhone) and whether they go with fewer anomalies.
Anomaly proxy, per record:
  a_pin_state : the PIN's India Post state differs from the stated state (both resolvable)
  a_pin_far   : coordinates more than 50 km from the PIN's median post-office location
  a_foreign   : a claim sentence names a different major city (q2 detector, out/foreign_city_sentences.csv)
  a_geo_copy  : exact coordinates shared with a record in another city (5 decimals)"""
import re
import numpy as np, pandas as pd
from rapidfuzz import fuzz
from common import load, OUT, norm_phone, domain, haversine, pin_ref, norm_state

df = load().drop_duplicates("unique_id").reset_index(drop=True)
N = len(df)
pin_state, pin_ll = pin_ref()
valid = set(pin_state.values()) - {"na"}
df["st"] = df.address_stateOrRegion.map(lambda s: norm_state(s, valid))
df["pst"] = df.pin.map(pin_state)
ok = df.st.notna() & df.pst.notna() & (df.pst != "na")
df["a_pin_state"] = np.where(ok, df.st != df.pst, np.nan)
ll = df.pin.map(lambda p: tuple(pin_ll.loc[p]) if p in pin_ll.index else None)
df["pin_km"] = [haversine(a, o, *t) if t else np.nan for a, o, t in zip(df.latitude, df.longitude, ll)]
df["a_pin_far"] = np.where(df.pin_km.notna(), df.pin_km > 50, np.nan)
X = pd.read_csv(OUT + "foreign_city_sentences.csv")
df["a_foreign"] = df.unique_id.isin(set(X.unique_id)).astype(float)
key = df.latitude.round(5).astype(str) + "," + df.longitude.round(5).astype(str)
ncity_per_key = df.groupby(key).ncity.nunique()
df["a_geo_copy"] = (key.map(ncity_per_key) > 1).astype(float)
A = ["a_pin_state", "a_pin_far", "a_foreign", "a_geo_copy"]
df["any_anom"] = df[A].fillna(0).max(axis=1)
print("records", N)
print("stated state resolvable:", df.st.notna().sum(), "| PIN in directory:", df.pst.notna().sum(),
      "| both:", int(ok.sum()))
for a in A + ["any_anom"]:
    print(f"  {a}: {int(np.nansum(df[a]))} of {int(df[a].notna().sum())} ({np.nanmean(df[a]):.1%})")

# --- website classification
DIRECTORY = ("practo.com", "facebook.com", "justdial.com", "medindia.net", "business.site", "g.page", "google.com",
             "g.co", "sites.google.com", "youtube.com", "bit.ly", "webs.com", "instagram.com", "eka.care", "lybrate.com",
             "linkedin.com", "wix.com", "wixsite.com", "blogspot.com", "skedoc.com", "credihealth.com", "hexahealth.com",
             "sulekha.com", "indiamart.com", "wikipedia.org", "mappls.com", "docindia.org", "linktr.ee", "x.com",
             "twitter.com", "wa.me", "goo.gl", "maps.app.goo.gl", "clinicspots.com", "drlogy.com", "bajajfinservhealth.in")
GENERIC = r"\b(hospital|hospitals|clinic|clinics|centre|center|care|multi|speciality|specialty|super|multispeciality|" \
          r"multispecialty|dental|eye|health|healthcare|medical|research|institute|nursing|home|and|in|at|the|of)\b"


def web_class(d):
    if not isinstance(d, str):
        return "none"
    if any(d == x or d.endswith("." + x) for x in DIRECTORY):
        return "directory_or_host"
    if re.search(r"\.(gov|nic)\.in$|\.gov$", d):
        return "government_portal"
    return "own_domain"


df["dom"] = df.officialWebsite.map(domain)
df["web"] = df.dom.map(web_class)


def name_dom_match(name, d):
    if not isinstance(d, str):
        return np.nan
    lab = re.sub(r"\.(com|in|org|net|co|info|health|care|clinic|hospital|ac|edu|gov|nic|biz|life)(\.[a-z]+)?$", "", d)
    lab = re.sub(r"[^a-z0-9]", "", lab.split(".")[-1] if "." in lab else lab)
    full = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    core = re.sub(r"\s+", "", re.sub(GENERIC, " ", full))
    acro = "".join(w[0] for w in full.split() if w)
    if not lab:
        return np.nan
    return float(fuzz.partial_ratio(lab, core) >= 80 or fuzz.partial_ratio(lab, re.sub(r"\s+", "", full)) >= 85
                 or (len(acro) >= 2 and acro[:3] in lab))


df["name_dom_match"] = [name_dom_match(n, d) if w == "own_domain" else np.nan for n, d, w in zip(df.name, df.dom, df.web)]

# --- phone classification: directory phone = valid number held by records in >= 3 different cities
own = {}
for r in df.itertuples():
    for p in r.phone_numbers_l + ([r.officialPhone] if r.officialPhone else []):
        d, k = norm_phone(p)
        if k != "invalid":
            own.setdefault(d, set()).add(r.ncity)
df["oph"] = df.officialPhone.map(lambda p: norm_phone(p) if isinstance(p, str) else (None, "none"))
df["phone"] = [("none" if k == "none" else "invalid" if k == "invalid" else
                "shared_3plus_cities" if len(own.get(d, ())) >= 3 else k) for d, k in df.oph]
print("\nofficialWebsite class:", df.web.value_counts().to_dict())
print("own-domain websites whose domain matches the name:", int(np.nansum(df.name_dom_match)), "of",
      int(df.name_dom_match.notna().sum()))
print("officialPhone class:", df.phone.value_counts().to_dict())


def table(col):
    t = df.groupby(col).agg(n=("unique_id", "size"), **{a: (a, "mean") for a in A + ["any_anom"]})
    return t.round(3)


pd.set_option("display.width", 200)
print("\nanomaly rate by officialWebsite presence:")
print(table(df.officialWebsite.notna().rename("has_website")).to_string())
print("\nby officialPhone presence:")
print(table(df.officialPhone.notna().rename("has_phone")).to_string())
print("\nby website class:")
print(table("web").to_string())
print("\nby own-domain name match (1 = domain resembles the name):")
print(table("name_dom_match").to_string())
print("\nby phone class:")
print(table("phone").to_string())
print("\nhospitals only, by website class:")
h = df[df.facilityTypeId == "hospital"]
print(h.groupby("web").agg(n=("unique_id", "size"), any_anom=("any_anom", "mean")).round(3).to_string())
df["both"] = (df.web == "own_domain") & (df.name_dom_match == 1) & df.phone.isin(["mobile", "landline", "tollfree"])
print("\nown name-matching domain AND non-shared official phone:", int(df.both.sum()), "of", N)
print(df.groupby("both").agg(n=("unique_id", "size"), **{a: (a, "mean") for a in A + ["any_anom"]}).round(3).to_string())
# 2x2 with counts for the headline comparison
for c in ["a_pin_state", "a_pin_far", "a_geo_copy", "a_foreign"]:
    t = df[df[c].notna()].groupby("both")[c].agg(["sum", "count"])
    print(c, {bool(k): f"{int(v['sum'])}/{int(v['count'])}" for k, v in t.iterrows()})
df[["unique_id", "name", "address_city", "officialWebsite", "dom", "web", "name_dom_match", "officialPhone", "phone",
    "st", "pst", "pin_km"] + A + ["any_anom", "both"]].to_csv(OUT + "existence_signals.csv", index=False)
mm = df[df.name_dom_match == 0].sample(20, random_state=4)
print("\nsample of own domains that do NOT resemble the name (hand check):")
print(mm[["unique_id", "name", "address_city", "dom"]].to_string(index=False))
