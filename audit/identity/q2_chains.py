"""Q2: chain branches and claim inheritance from the flagship or from sibling branches.
Three detectors: (a) verbatim claim sentences shared with a same-chain record in another city,
(b) claim sentences naming a different major city, (c) tertiary claims at small branch sites."""
import collections, re
import pandas as pd
from common import load, OUT, domain

df = load().drop_duplicates("unique_id").reset_index(drop=True)
df["dom"] = df.officialWebsite.map(domain)
N = len(df)

# brand -> (name regex, official domains). Generic words (care, max, global) need the domain.
CHAINS = {
    "apollo": (r"\bapollo\b", {"apollohospitals.com", "apolloclinic.com", "apollo247.com", "apollospectra.com", "apollocradle.com"}),
    "fortis": (r"\bfortis\b", {"fortishealthcare.com"}),
    "manipal": (r"\bmanipal (hospital|clinic)", {"manipalhospitals.com"}),
    "aravind": (r"\baravind eye", {"aravind.org"}),
    "max": (r"\bmax (super|smart|healthcare|hospital|multi|lab)", {"maxhealthcare.in", "maxlab.co.in"}),
    "narayana": (r"\bnarayana (?:health|hrudayalaya|multi|super)|\bnh narayana", {"narayanahealth.org"}),
    "care": (r"^care hospitals?\b|\bcare hospitals?,", {"carehospitals.com"}),
    "yashoda": (r"\byashoda hospital", {"yashodahospitals.com"}),
    "medanta": (r"\bmedanta\b", {"medanta.org"}),
    "kims": (r"\bkims\b|krishna institute of medical", {"kimshospitals.com"}),
    "aster": (r"\baster (medcity|cmi|rv|mims|hospital|prime|ramesh|dm)", {"asterhospitals.in", "asterdmhealthcare.com"}),
    "hcg": (r"\bhcg\b", {"hcgoncology.com"}),
    "asg_eye": (r"\basg eye", {"asgeyehospital.com"}),
    "dr_agarwals": (r"dr\.? ?agarwal", {"dragarwal.com"}),
    "sankara": (r"\bsankara (eye|nethralaya)", {"sankaraeye.com", "sankaranethralaya.org"}),
    "indira_ivf": (r"\bindira ivf", {"indiraivf.in", "indiraivf.com"}),
    "nova_ivf": (r"\bnova ivf", {"novaivffertility.com"}),
    "cloudnine": (r"\bcloudnine\b", {"cloudninecare.com"}),
    "motherhood": (r"\bmotherhood hospital", {"motherhoodindia.com"}),
    "paras": (r"\bparas (health|hospital|global|hmri)", {"parashospitals.com"}),
    "kauvery": (r"\bkauvery hospital", {"kauveryhospital.com"}),
    "rainbow": (r"\brainbow children", {"rainbowhospitals.in"}),
    "shalby": (r"\bshalby\b", {"shalby.org"}),
    "wockhardt": (r"\bwockhardt\b", {"wockhardthospitals.com"}),
    "esic": (r"\besic?\b|\bemployees state insurance", {"esic.nic.in", "esic.gov.in"}),
    "redcliffe": (r"\bredcliffe", {"redcliffelabs.com"}),
    "pathkind": (r"\bpathkind", {"pathkindlabs.com"}),
    "agilus": (r"\bagilus\b", {"agilus.in", "agilusdiagnostics.com"}),
    "sabka_dentist": (r"\bsabka dentist", {"sabkadentist.com"}),
    "clove": (r"\bclove dental", {"clovedental.in"}),
    "partha": (r"\bpartha dental", {"parthadental.com"}),
    "saaol": (r"\bsaaol\b", {"saaol.com"}),
}
nm = df.name.fillna("").str.lower()
df["chain_by_name"] = None
df["chain_by_dom"] = None
for b, (rx, doms) in CHAINS.items():
    df.loc[nm.str.contains(rx, regex=True) & df.chain_by_name.isna(), "chain_by_name"] = b
    df.loc[df.dom.isin(doms) & df.chain_by_dom.isna(), "chain_by_dom"] = b
df["chain"] = df.chain_by_name.fillna(df.chain_by_dom)
ch = df[df.chain.notna()]
print("records matched to a chain:", len(ch), "of", N, "| by name", df.chain_by_name.notna().sum(),
      "| by domain", df.chain_by_dom.notna().sum())
print(ch.chain.value_counts().to_dict())
mis = df[df.chain_by_dom.notna() & (df.chain_by_name != df.chain_by_dom)]
print("\nchain official domain but name lacks the brand (website misattribution candidates):", len(mis))
print(mis[["unique_id", "name", "address_city", "officialWebsite", "chain_by_dom"]].to_string(index=False))
mis[["unique_id", "name", "address_city", "officialWebsite", "chain_by_dom"]].to_csv(OUT + "chain_domain_name_mismatch.csv", index=False)

# --- claim sentences
CL = ["procedure", "equipment", "capability"]


def norm_s(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.lower())).strip()


sent = [(i, c, s, norm_s(s)) for i, r in df.iterrows() for c in CL for s in r[c + "_l"]]
S = pd.DataFrame(sent, columns=["i", "field", "text", "ns"])
S = S[S.ns.str.len() >= 25]  # skip short generic items ("Cardiology", "24/7 emergency")
print("\nclaim sentences (>= 25 chars normalized):", len(S))
S["city"] = S.i.map(df.ncity)
S["chain"] = S.i.map(df.chain)
own = S.groupby("ns").agg(nrec=("i", "nunique"), ncity=("city", "nunique"))
S = S.join(own, on="ns")
# distinctive sentences only: >= 40 chars and held by <= 10 records (boilerplate such as
# "Wheelchair accessible entrance" sits on hundreds of records and says nothing about inheritance)
shared = S[(S.ncity >= 2) & (S.nrec <= 10) & (S.ns.str.len() >= 40)]
rec_shared = shared.groupby("i").size()
df["n_sent"] = S.groupby("i").size().reindex(df.index).fillna(0)
df["n_shared_xcity"] = rec_shared.reindex(df.index).fillna(0)
for lab, m in [("chain", df.chain.notna()), ("non-chain", df.chain.isna())]:
    d = df[m & (df.n_sent > 0)]
    print(f"{lab}: records with claims {len(d)}, with >=1 sentence repeated verbatim in another city: "
          f"{(d.n_shared_xcity > 0).sum()} ({(d.n_shared_xcity > 0).mean():.1%}); share of sentences {d.n_shared_xcity.sum() / d.n_sent.sum():.1%}")
sc_ = shared.groupby("ns").chain.agg(lambda x: x.notna().all() and x.nunique() == 1)
print("distinctive cross-city sentences:", shared.ns.nunique(), "| held only by records of one chain:", int(sc_.sum()))
ex = shared[shared.ns.isin(sc_[sc_].index)].drop_duplicates("ns").sample(12, random_state=1)
for r in ex.itertuples():
    holders = S[S.ns == r.ns].i.unique()
    print(f"  [{r.chain}] {r.text[:120]!r} -> " + "; ".join(f"{df.name[h][:35]} ({df.address_city[h]})" for h in holders[:4]))
top = shared.drop_duplicates("ns").sort_values("ncity", ascending=False)
print("\nmost repeated distinctive cross-city sentences:")
print(top[["ncity", "nrec", "field", "text"]].head(10).to_string(index=False))
bp = S.drop_duplicates("ns").sort_values("nrec", ascending=False)
print("boilerplate: sentences on >= 50 records:", int((S.drop_duplicates("ns").nrec >= 50).sum()),
      "| their share of all sentence occurrences:", round((S.nrec >= 50).mean(), 3))
shared.to_csv(OUT + "shared_xcity_sentences.csv", index=False)

# --- (b) sentences naming another major city
ALIAS = {"bangalore": "bengaluru", "gurgaon": "gurugram", "bombay": "mumbai", "madras": "chennai",
         "calcutta": "kolkata", "trivandrum": "thiruvananthapuram", "calicut": "kozhikode",
         "vizag": "visakhapatnam", "cochin": "kochi", "poona": "pune", "mysore": "mysuru", "baroda": "vadodara"}
cities = df.ncity.value_counts()
MAJOR = sorted(set(c for c in cities[cities >= 25].index if len(c) >= 5) | set(ALIAS) | set(ALIAS.values()))
rx = re.compile(r"\b(" + "|".join(MAJOR) + r")\b")


def canon(c):
    return ALIAS.get(c, c)


def own_places(r):
    t = " ".join(str(x).lower() for x in [r.address_city, r.address_line1, r.address_line2, r.address_line3,
                                           r.address_stateOrRegion, r["name"]])
    return {canon(m) for m in rx.findall(re.sub(r"[^a-z ]", "", t.replace(",", " ")))} | {canon(r.ncity)}


rows = []
for i, r in df.iterrows():
    mine = own_places(r)
    for c in CL:
        for s in r[c + "_l"]:
            hits = {canon(m) for m in rx.findall(s.lower())} - mine
            if hits:
                rows.append((i, r.unique_id, r["name"], r.address_city, r.chain, c, s, ";".join(sorted(hits))))
X = pd.DataFrame(rows, columns=["i", "unique_id", "name", "city", "chain", "field", "text", "other_city"])
X.to_csv(OUT + "foreign_city_sentences.csv", index=False)
print("\nsentences naming another major city:", len(X), "in records", X.i.nunique(), "of", N)
for lab, m in [("chain", df.chain.notna()), ("non-chain", df.chain.isna())]:
    d = df[m]
    k = X.i.isin(d.index).groupby(X.i).first().sum()
    print(f"  {lab}: {int(k)} of {len(d)} records ({k / len(d):.1%})")

# --- (c) tertiary claims at small branch sites
HIGH = {
    "transplant": r"(kidney|renal|liver|heart|lung|bone marrow|stem cell|organ) transplant", "cardiac_surgery": r"cardiac surg|cardiothoracic|\bcabg\b|bypass surg|open heart|valve replacement",
    "neurosurgery": r"neurosurg|brain surg", "cath_lab": r"cath(eterization)? ?lab|angioplasty|\bptca\b",
    "radiation": r"radiotherap|radiation therap|linac|linear accelerator|brachytherap",
    "nicu": r"\bnicu\b|neonatal intensive", "dialysis": r"dialysis|haemodialysis|hemodialysis",
    "mri": r"\bmri\b|magnetic resonance", "robotic": r"robotic surg|da vinci",
}
small = (df.facilityTypeId.isin(["clinic", "dentist", "doctor", "farmacy"]) |
         nm.str.contains(r"clinic|collection cent|diagnostic|\blab\b|labs\b|pharmacy|dental|dentist|sugar|ivf|fertility"))
txt = df.apply(lambda r: " ".join(r.procedure_l + r.equipment_l + r.capability_l).lower(), axis=1)
print("\ntertiary-claim rates at small sites (clinic/dentist/lab/IVF/dental by type or name):")
res = []
for k, p in HIGH.items():
    hit = txt.str.contains(p, regex=True)
    for lab, m in [("chain", df.chain.notna()), ("non-chain", df.chain.isna())]:
        base = m & small
        res.append(dict(claim=k, group=lab, small_sites=int(base.sum()), claiming=int((base & hit).sum()),
                        rate=round((base & hit).sum() / max(base.sum(), 1), 3)))
R = pd.DataFrame(res).pivot(index="claim", columns="group", values=["small_sites", "claiming", "rate"])
print(R.to_string())
df["small"] = small
tc = df[small & df.chain.notna() & txt.str.contains(HIGH["transplant"] + "|" + HIGH["cardiac_surgery"] + "|" + HIGH["neurosurgery"], regex=True)]
print("(transplant counts organ and marrow transplant only; hair and cornea transplant excluded)")
print("\nchain small sites claiming transplant / cardiac surgery / neurosurgery:", len(tc))
tc_rows = []
for i, r in tc.iterrows():
    for c in CL:
        for s in r[c + "_l"]:
            if re.search(HIGH["transplant"] + "|" + HIGH["cardiac_surgery"] + "|" + HIGH["neurosurgery"], s.lower()):
                tc_rows.append((r.unique_id, r["name"], r.address_city, r.chain, r.facilityTypeId, c, s))
T = pd.DataFrame(tc_rows, columns=["unique_id", "name", "city", "chain", "type", "field", "text"])
T.to_csv(OUT + "chain_small_site_tertiary_claims.csv", index=False)
df[["unique_id", "chain", "chain_by_name", "chain_by_dom", "small", "n_sent", "n_shared_xcity"]].to_csv(OUT + "chain_membership.csv", index=False)
