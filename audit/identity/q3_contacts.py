"""Q3: phone formats, phones shared across facilities, emails, website domains."""
import collections, re
import pandas as pd
from common import load, OUT, norm_phone, domain, pin_ref

df = load().drop_duplicates("unique_id").reset_index(drop=True)
N = len(df)
print("records", N)

# --- phone formats
allp = [(r.unique_id, p) for r in df.itertuples() for p in r.phone_numbers_l]
kinds = collections.Counter(norm_phone(p)[1] for _, p in allp)
print("\nphone_numbers entries:", len(allp), dict(kinds))
raw_fmt = collections.Counter(re.sub(r"\d", "9", p)[:16] for _, p in allp)
print("top raw shapes:", raw_fmt.most_common(8))
bad = [p for _, p in allp if norm_phone(p)[1] == "invalid"]
print("invalid examples:", bad[:15])
op = df.officialPhone.dropna()
ok = collections.Counter(norm_phone(p)[1] for p in op)
print("officialPhone present:", len(op), "of", N, dict(ok))
dup_in_rec = sum(len(l) != len({norm_phone(p)[0] for p in l}) for l in df.phone_numbers_l if l)
print("records whose phone list repeats a number:", dup_in_rec, "of", sum(bool(l) for l in df.phone_numbers_l))
nph = df.phone_numbers_l.map(lambda l: len({norm_phone(p)[0] for p in l if norm_phone(p)[1] != "invalid"}))
print("distinct valid phones per record: median", nph.median(), "p90", nph.quantile(.9), "max", nph.max(),
      "| records with >=10:", (nph >= 10).sum())
# official phone not in its own phone list
notin = sum(1 for o, l in zip(df.officialPhone, df.phone_numbers_l)
            if o and norm_phone(o)[0] not in {norm_phone(p)[0] for p in l})
print("officialPhone not in own phone_numbers:", notin, "of", len(op))

# --- landline STD code vs state (only first 3-4 digits; coarse metro check)
METRO = {"11": "delhi", "22": "maharashtra", "33": "west bengal", "44": "tamil nadu", "80": "karnataka",
         "40": "telangana|andhra pradesh", "20": "maharashtra", "79": "gujarat"}
pin_state, _ = pin_ref()
st = df.pin.map(pin_state).fillna("")  # state of the record's PIN (stated state is too messy)
mm = tot = 0
ex = []
for r, s in zip(df.itertuples(), st):
    d, k = norm_phone(r.officialPhone) if r.officialPhone else (None, None)
    if k == "landline" and d[:2] in METRO:
        tot += 1
        if s and not re.search(METRO[d[:2]], s):
            mm += 1
            ex.append((r.unique_id, r.name, r.address_city, r.address_stateOrRegion, r.officialPhone))
print(f"\nofficialPhone metro-STD landlines: {tot}; state disagrees with STD metro: {mm}")
for e in ex[:8]:
    print("  ", e)

# --- phones shared across facilities
owner = collections.defaultdict(set)
for r in df.itertuples():
    for p in r.phone_numbers_l + ([r.officialPhone] if r.officialPhone else []):
        d, k = norm_phone(p)
        if k != "invalid":
            owner[d].add(r.Index)
sh = {p: s for p, s in owner.items() if len(s) > 1}
print("\ndistinct valid phones:", len(owner), "| shared by >=2 records:", len(sh),
      "| >=5:", sum(len(s) >= 5 for s in sh.values()), "| >=20:", sum(len(s) >= 20 for s in sh.values()))
recs_with_shared = set().union(*sh.values())
print("records holding at least one shared phone:", len(recs_with_shared), "of", N)
rows = []
for p, s in sorted(sh.items(), key=lambda x: -len(x[1])):
    g = df.loc[sorted(s)]
    rows.append(dict(phone=p, n=len(s), n_city=g.ncity.nunique(), n_name=g.nname.nunique(),
                     names="; ".join(g.name.head(6)), cities="; ".join(g.address_city.fillna("").head(6)),
                     official_for=int(sum(norm_phone(o)[0] == p for o in g.officialPhone.dropna()))))
S = pd.DataFrame(rows)
S.to_csv(OUT + "shared_phones.csv", index=False)
print(S.head(15).to_string())
print("shared phones spanning >=2 cities:", (S.n_city >= 2).sum(), "of", len(S),
      "| records in those:", len(set().union(*[sh[p] for p in S[S.n_city >= 2].phone])))
# shared phone that is the OFFICIAL phone of >=2 records in different cities
so = S[(S.official_for >= 2) & (S.n_city >= 2)]
print("phones that are officialPhone of >=2 records spanning >=2 cities:", len(so),
      "records", int(so.official_for.sum()))

# --- emails
em = df.email.dropna()
cf = em.str.contains("email protected|email\xa0protected", regex=True)
print("\nemail present:", len(em), "of", N, "| Cloudflare-obfuscated placeholder:", int(cf.sum()))
real = em[~cf]
valid = real.str.match(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")
print("other emails:", len(real), "valid single-address format:", int(valid.sum()),
      "| list-like or malformed:", int((~valid).sum()), list(real[~valid].head(5)))
edom = real[valid].str.split("@").str[1].str.lower()
fre = edom.isin(["gmail.com", "yahoo.com", "yahoo.co.in", "hotmail.com", "rediffmail.com", "outlook.com"])
print("free-mail domains:", int(fre.sum()), "of", int(valid.sum()))
ve = real[valid].str.lower()
vc = ve.value_counts()
print("emails shared by >=2 records:", int((vc >= 2).sum()), "covering", int(vc[vc >= 2].sum()), "records; top", vc.head(8).to_dict())
# email domain vs officialWebsite domain
d2 = df.loc[ve.index]
agree = [(e.split("@")[1] in (domain(w) or "")) for e, w in zip(ve, d2.officialWebsite)]
hasw = d2.officialWebsite.notna() & ~edom.isin(["gmail.com", "yahoo.com", "yahoo.co.in", "hotmail.com", "rediffmail.com", "outlook.com"]).values
print("non-free email with officialWebsite:", int(hasw.sum()), "| email domain matches website domain:",
      int(sum(a for a, h in zip(agree, hasw) if h)))

# --- website domains
df["dom"] = df.officialWebsite.map(domain)
print("\nofficialWebsite present:", df.dom.notna().sum(), "of", N)
dv = df.dom.value_counts()
print("official domains shared by >=2 records:", int((dv >= 2).sum()), "covering", int(dv[dv >= 2].sum()), "records")
rows = []
for d, n in dv[dv >= 2].items():
    g = df[df.dom == d]
    rows.append(dict(domain=d, n=n, n_city=g.ncity.nunique(), n_name=g.nname.nunique(),
                     names="; ".join(g.name.head(5)), cities="; ".join(g.address_city.fillna("").head(5))))
D = pd.DataFrame(rows)
D.to_csv(OUT + "shared_domains.csv", index=False)
print(D.head(40).to_string())
# all website domains in the websites list (directory / aggregator footprint)
wd = collections.Counter(domain(u) for l in df.websites_l for u in set(l))
print("\ntop domains inside websites lists:", wd.most_common(25))
