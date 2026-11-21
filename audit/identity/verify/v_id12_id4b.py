"""ID12 existence-signal comparison and an ID4 distance-based alternative. Own PIN reference."""
import sys; sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/identity/verify")
from v_base import *
V = "/Users/karthikvattem/projects/datathon/audit/identity/verify/"
d = dedup(wellformed(raw()))
p = pd.read_parquet(RAW + "india_post_pincode_directory.parquet")
p["la"] = pd.to_numeric(p.latitude, errors="coerce"); p["lo"] = pd.to_numeric(p.longitude, errors="coerce")
ok = p.la.between(6, 37.5) & p.lo.between(68, 97.5)
print("PIN dir rows", len(p), "with usable coords", ok.sum(), "distinct pins", p.pincode.nunique(), "with usable coords", p[ok].pincode.nunique())
pc = p[ok].groupby("pincode").agg(la=("la", "median"), lo=("lo", "median"), sd=("la", "std"))
pst = p.groupby("pincode").statename.agg(lambda s: s.mode().iat[0].lower())
pdist = p.groupby("pincode").district.agg(lambda s: s.mode().iat[0].lower())
d["pin"] = d.address_zipOrPostcode.map(lambda v: (lambda m: int(m.group(0)) if m else np.nan)(re.search(r"[1-9]\d{5}", re.sub(r"\s", "", str(v)))) if not nul(v) else np.nan)
def km(a1, o1, a2, o2):
    r = np.pi / 180
    h = np.sin((a2-a1)*r/2)**2 + np.cos(a1*r)*np.cos(a2*r)*np.sin((o2-o1)*r/2)**2
    return 12742*np.arcsin(np.sqrt(h))
m = d.join(pc, on="pin")
d["pin_km"] = km(d.latitude, d.longitude, m.la, m.lo)
has_ref = d.pin_km.notna()
print("records with PIN centroid", has_ref.sum(), "| >50 km", (d.pin_km > 50).sum(), f"({(d.pin_km > 50).sum()/has_ref.sum():.1%})")
# alternative explanation: facility coords agree with stated-city centroid (median of same-city records) though PIN disagrees
d["c"] = d.address_city.map(lambda v: "" if nul(v) else re.sub(r"[^a-z]", "", v.lower()))
cc = d[d.c != ""].groupby("c")[["latitude", "longitude"]].median()
vcnt = d.c.value_counts()
mm = d.join(cc, on="c", rsuffix="_c")
d["city_km"] = km(d.latitude, d.longitude, mm.latitude_c, mm.longitude_c).where(d.c.map(vcnt) >= 5)
far = d.pin_km > 50
print("  of >50 km: coords within 25 km of own stated-city centroid (city n>=5):", (far & (d.city_km < 25)).sum(), "| city centroid unknown:", (far & d.city_km.isna()).sum())
# PIN centroid itself far from the PIN's own district centroid -> directory error
dc = p[ok].groupby(p.district.str.lower())[["la", "lo"]].median()
pin_d = pdist.reindex(pc.index)
pc2 = pc.join(dc, on=pin_d.rename("dist"), rsuffix="_d") if False else None
pcd = pd.DataFrame({"la": pc.la, "lo": pc.lo, "dist": pin_d})
pcd = pcd.join(dc, on="dist", rsuffix="_d")
pcd["off"] = km(pcd.la, pcd.lo, pcd.la_d, pcd.lo_d)
bad_pin = set(pcd.index[pcd.off > 100])
print("  PIN centroids >100 km from their own district centroid:", len(bad_pin), "of", len(pcd), "| facility >50km cases on such PINs:", int((far & d.pin.isin(bad_pin)).sum()))
# state mismatch
SA = {"tamilnadu": "tamil nadu", "orissa": "odisha", "pondicherry": "puducherry", "new delhi": "delhi", "nct of delhi": "delhi", "chattisgarh": "chhattisgarh", "telengana": "telangana", "uttaranchal": "uttarakhand", "jammu kashmir": "jammu and kashmir", "jammu & kashmir": "jammu and kashmir"}
valid = set(pst.unique())
def ns(s):
    t = re.sub(r"\s+", " ", re.sub(r"[^a-z& ]", " ", str(s).lower())).strip(); t = SA.get(t, t).replace("&", "and")
    return t if t in valid else None
d["st"] = d.address_stateOrRegion.map(lambda v: None if nul(v) else ns(v))
d["pst"] = d.pin.map(pst)
cmp_ = d.st.notna() & d.pst.notna()
smis = cmp_ & (d.st != d.pst)
print("state comparable", cmp_.sum(), "mismatch", smis.sum())
# copied coords from different-city record (exact 5dp)
key = d.latitude.round(5).astype(str) + "," + d.longitude.round(5).astype(str)
g = d.groupby(key).c.nunique()
geo_copy = key.map(g) > 1
fc = pd.read_csv(V + "v_foreign_city.csv")
foreign = d.index.isin(fc.i)
anyan = smis | (d.pin_km > 50) | foreign | geo_copy
print("ID12 any anomaly", anyan.sum(), f"({anyan.mean():.1%})")
op = ~d.officialPhone.map(nul); ow = ~d.officialWebsite.map(nul)
for lab, s in [("officialPhone", op), ("officialWebsite", ow)]:
    for v in (True, False):
        mk = s == v; r50 = (d.pin_km[mk] > 50).sum() / d.pin_km[mk].notna().sum()
        print(f"  {lab} {'present' if v else 'absent'}: n={mk.sum()} any={anyan[mk].sum()} ({anyan[mk].mean():.1%}) | >50km {r50:.1%} | foreign-text {foreign[mk.values].mean():.1%}")
# confound: facility type and claim volume
nsent = d.apply(lambda r: sum(len(jlist(r[f])) for f in ["procedure", "equipment", "capability"]), axis=1)
print("  mean claim sentences: phone present", round(nsent[op].mean(), 1), "absent", round(nsent[~op].mean(), 1))
print("  type mix phone-absent:", d.facilityTypeId[~op].value_counts(normalize=True).round(2).head(4).to_dict(), "| present:", d.facilityTypeId[op].value_counts(normalize=True).round(2).head(4).to_dict())
for t in ["hospital", "clinic"]:
    mk = d.facilityTypeId == t
    a = (d.pin_km[mk & op] > 50).mean(); b = (d.pin_km[mk & ~op] > 50).mean()
    print(f"  within {t}: >50km phone present {a:.1%} (n={int((mk & op).sum())}) absent {b:.1%} (n={int((mk & ~op).sum())})")
print("  neither phone nor website:", int((~op & ~ow).sum()))
# ID4 alternative: within 0.1 km of a record whose PIN maps to a different district
d["pd"] = d.pin.map(pdist)
lat, lon = d.latitude.to_numpy(), d.longitude.to_numpy(); order = np.argsort(lat); flag = set()
for a in range(len(d)):
    i = order[a]
    for b in range(a + 1, len(d)):
        j = order[b]
        if lat[j] - lat[i] > 0.001: break
        if abs(lon[j] - lon[i]) > 0.0012: continue
        if km(lat[i], lon[i], lat[j], lon[j]) < 0.1 and isinstance(d.pd[i], str) and isinstance(d.pd[j], str) and d.pd[i] != d.pd[j]:
            flag |= {i, j}
print("ID4-alt records within 100 m of a record whose PIN is in a different district:", len(flag))
d.loc[sorted(flag), ["unique_id", "name", "address_city", "pin", "pd", "latitude", "longitude"]].to_csv(V + "v_id4_alt.csv", index=False)
# Refinements
alt = (far & (d.city_km < 25)) | (far & d.pin.isin(bad_pin))
print("ID12 >50km cases with an alternative explanation (coords match stated city, or PIN centroid itself off):", int(alt.sum()), "of", int(far.sum()))
# ID4-alt2: record sits within 100 m of another record AND is >30 km from its own PIN centroid AND the pair's PIN centroids are >30 km apart
pla = m.la.to_numpy(); plo = m.lo.to_numpy(); flag2 = set(); pairs2 = []
for a in range(len(d)):
    i = order[a]
    for b in range(a + 1, len(d)):
        j = order[b]
        if lat[j] - lat[i] > 0.001: break
        if abs(lon[j] - lon[i]) > 0.0012: continue
        if km(lat[i], lon[i], lat[j], lon[j]) >= 0.1 or np.isnan(pla[i]) or np.isnan(pla[j]): continue
        if km(pla[i], plo[i], pla[j], plo[j]) > 30:
            for x in (i, j):
                if d.pin_km[x] > 30: flag2.add(x)
            pairs2.append((i, j))
print("ID4-alt2 records sitting on a geocode shared (<100 m) with a record whose PIN is >30 km away, and themselves >30 km from own PIN:", len(flag2), "pairs", len(pairs2))
X = d.loc[sorted(flag2), ["unique_id", "name", "address_city", "pin", "pin_km", "latitude", "longitude"]]
X.to_csv(V + "v_id4_alt2.csv", index=False)
print(X.sample(min(12, len(X)), random_state=2).to_string())
s = d[far].sample(10, random_state=5)
print(s[["unique_id", "name", "address_city", "address_stateOrRegion", "pin", "pin_km", "city_km", "latitude", "longitude"]].to_string())
