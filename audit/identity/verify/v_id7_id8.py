"""ID7 email quality, ID8 officialWebsite classes and sharing. Own rules."""
import sys; sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/identity/verify")
from v_base import *
import collections
d = dedup(wellformed(raw()))
e = d.email.map(lambda v: None if nul(v) else v.strip())
print("ID7 email present", e.notna().sum(), "of", len(d))
ph = e.fillna("").str.contains(r"email.{0,3}protected", case=False)
print("  contains 'email protected' placeholder:", ph.sum(), "| exactly the placeholder:", e.fillna("").str.fullmatch(r"\[email.{0,3}protected\]").sum())
print("  placeholder variants", e[ph].value_counts().head(4).to_dict())
valid = e.fillna("").str.fullmatch(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
bad = e.notna() & ~valid & ~ph
print("  valid single address", valid.sum(), "| malformed/other (not placeholder)", bad.sum())
print("  malformed sample", e[bad].sample(8, random_state=1).tolist())
free = r"@(gmail|yahoo|ymail|rediffmail|hotmail|outlook|live|icloud|aol|protonmail|yahoo\.co)\."
print("  free-mail among valid", e[valid].str.lower().str.contains(free).sum())
vc = e[valid].str.lower().value_counts()
print("  shared addresses", (vc > 1).sum(), "records", vc[vc > 1].sum())
# ID8 websites
def dom(u):
    u = u.lower().strip(); u = re.sub(r"^[a-z]+://", "", u).split("/")[0].split("?")[0]
    return re.sub(r"^www\d?\.", "", u)
w = d.officialWebsite.map(lambda v: None if nul(v) else dom(v))
print("ID8 officialWebsite present", w.notna().sum())
DIR = r"(practo|justdial|business\.site|facebook|g\.page|instagram|linkedin|google|goo\.gl|wix|wixsite|blogspot|wordpress|sulekha|lybrate|indiamart|tradeindia|youtube|twitter|x\.com|bajajfinservhealth|hexahealth|credihealth|medindia|skedoc|clinicspots|docindia|justdial|wikipedia|zoominfo|umdaa|kivihealth|mfine|tatahealth|apollo247|1mg|healthfrog|quickobook|myupchar|sehat|vaidam|joonsquare|placesmap|mappls|magicpin|zomato|wheree|onefivenine|linktr\.ee|sites\.google)\b"
gov = w.fillna("").str.contains(r"\.gov\.in$|\.nic\.in$|\.gov$")
dr = w.fillna("").str.contains(DIR) & ~gov
print("  directory/host", dr.sum(), "| gov", gov.sum(), "| own", (w.notna() & ~dr & ~gov).sum())
print("  top directory domains", w[dr].value_counts().head(8).to_dict())
city = d.address_city.map(lambda v: "" if nul(v) else re.sub(r"[^a-z]", "", v.lower()))
vcw = w.value_counts(); sh = vcw[vcw > 1]
print("  domains shared by >1 record:", len(sh), "records", sh.sum())
xc = [k for k in sh.index if city[w == k].replace("", np.nan).dropna().nunique() >= 2]
print("  shared domains spanning >=2 cities", len(xc), "records", vcw[xc].sum())
# Is the finder's 'own domain' count inflated by directory domains it missed?
own = w[w.notna() & ~dr & ~gov]
print("  'own' domains shared by >=5 records (likely chains or directories):", own.value_counts()[own.value_counts() >= 5].head(15).to_dict())
# How many 'malformed' emails are actually lists of valid addresses?
EM = r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
def all_valid_list(v):
    parts = jlist(v) if v.startswith("[") else re.split(r"[,;/ ]+", v)
    parts = [p.strip() for p in parts if p.strip()]
    return len(parts) >= 2 and all(re.fullmatch(EM, p) for p in parts)
b = e[bad]
lv = b.map(all_valid_list)
print("ID7 'malformed' that are lists of >=2 valid addresses:", lv.sum(), "of", len(b), "| truly unusable:", (~lv).sum())
print("  truly unusable sample", b[~lv].head(12).tolist())
