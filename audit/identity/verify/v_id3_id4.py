"""ID3: disagreement inside hand-confirmed duplicate groups. ID4: exact shared geocodes across cities."""
import sys; sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/identity/verify")
from v_base import *
V = "/Users/karthikvattem/projects/datathon/audit/identity/verify/"
R = pd.read_csv(V + "v_pairs.csv"); G = pd.read_csv(V + "v_strict_groups.csv")
lab = pd.read_csv("/Users/karthikvattem/projects/datathon/audit/identity/labels/strong_groups_hand.csv")
u2g = dict(zip(G.unique_id, G.grp)); lab["grp"] = lab.unique_id.map(u2g)
R["grp"] = R.uid_a.map(u2g); R = R[R.strict & (R.grp == R.uid_b.map(u2g))]
td = set(lab[lab.label == "true_dup"].grp)
T = R[R.grp.isin(td)]
d = dedup(wellformed(raw())).set_index("unique_id")
def dom(u):
    return "" if nul(u) else re.sub(r"^www\d?\.", "", re.sub(r"^[a-z]+://", "", u.lower().strip()).split("/")[0])
T = T.assign(dom_a=T.uid_a.map(lambda u: dom(d.loc[u].officialWebsite)), dom_b=T.uid_b.map(lambda u: dom(d.loc[u].officialWebsite)))
T["dom_conflict"] = (T.dom_a != "") & (T.dom_b != "") & (T.dom_a != T.dom_b)
T["pin_conflict"] = (T.pin_a.fillna("") != T.pin_b.fillna("")) & T.pin_a.notna() & T.pin_b.notna()
g = T.groupby("grp").agg(km=("km", "max"), dom_conflict=("dom_conflict", "any"), pin_conflict=("pin_conflict", "any"), name=("name_a", "first"))
print("true-dup groups", len(g))
print("max km > 5:", (g.km > 5).sum(), "| km > 1:", (g.km > 1).sum(), "| domain conflict:", g.dom_conflict.sum(), "| PIN differs:", g.pin_conflict.sum())
print("any of km>5 or dom conflict:", ((g.km > 5) | g.dom_conflict).sum())
print(g[(g.km > 1) | g.dom_conflict].sort_values("km").to_string())
# ID4: exact 5-decimal coordinate shared with a record whose city differs
d2 = d.reset_index()
d2["key"] = d2.latitude.round(5).astype(str) + "," + d2.longitude.round(5).astype(str)
d2["c"] = d2.address_city.map(lambda v: "" if nul(v) else re.sub(r"[^a-z]", "", v.lower()))
grp = d2.groupby("key")
multi = d2[d2.key.map(grp.size()) > 1]
print("records sharing exact 5-dp coords with any other:", len(multi), "distinct coords", multi.key.nunique())
xc = multi[multi.key.map(multi.groupby("key").c.nunique()) > 1]
print("ID4 records sharing exact coords with a record of a different stated city:", len(xc), "coords", xc.key.nunique())
# how many of those differ by city only through spelling (e.g. Shimoga/Shivamogga, Bengaluru/Bangalore)?
xc2 = xc.copy(); xc2["st"] = xc2.address_stateOrRegion.fillna("").str.lower()
print("  ...with different stated state as well:", len(xc2[xc2.key.map(xc2.groupby("key").st.nunique()) > 1]))
print(xc[["key", "name", "address_city", "address_stateOrRegion", "address_zipOrPostcode"]].sort_values("key").to_string())
# 4-dp (~11 m) version
d2["key4"] = d2.latitude.round(4).astype(str) + "," + d2.longitude.round(4).astype(str)
m4 = d2[d2.key4.map(d2.groupby("key4").size()) > 1]
x4 = m4[m4.key4.map(m4.groupby("key4").c.nunique()) > 1]
print("4-dp version: records", len(x4))
