"""ID5/ID6: phone sharing and phone format, own parser."""
import sys; sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/identity/verify")
from v_base import *
import collections
d = dedup(wellformed(raw()))
def kind(p):
    s = re.sub(r"[^\d+]", "", str(p))
    dg = re.sub(r"\D", "", s)
    if re.match(r"^(91)?0?1(800|860)", dg) or dg.startswith("1800") or dg.startswith("1860"):
        return dg[-10:] if len(dg) >= 10 else dg, "tollfree"
    if s.startswith("+") and not s.startswith("+91"):
        return dg, "invalid"
    if len(dg) == 12 and dg.startswith("91"): dg = dg[2:]
    elif len(dg) == 11 and dg.startswith("0"): dg = dg[1:]
    elif len(dg) == 13 and dg.startswith("910"): dg = dg[3:]
    if len(dg) != 10: return dg, "invalid"
    return dg, ("mobile" if dg[0] in "6789" else "landline" if dg[0] in "12345" else "invalid")
ent = [(i, p) for i, v in enumerate(d.phone_numbers) for p in jlist(v)]
K = [kind(p) for _, p in ent]
print("ID6 phone entries", len(ent), collections.Counter(k for _, k in K))
inv = [p for (_, p), (_, k) in zip(ent, K) if k == "invalid"]
print("  invalid sample", inv[:12])
per = collections.defaultdict(list)
for (i, _), (dg, k) in zip(ent, K):
    if k != "invalid": per[i].append(dg)
nonempty = sum(1 for v in d.phone_numbers if jlist(v))
rep = sum(1 for i in per if len(per[i]) != len(set(per[i])))
print("records with non-empty phone list", nonempty, "| repeat a number:", rep)
ds = pd.Series({i: len(set(v)) for i, v in per.items()})
print("median distinct valid", ds.median(), "| >=10:", (ds >= 10).sum())
op = d.officialPhone.map(lambda v: None if nul(v) else v)
print("officialPhone present", op.notna().sum(), "of", len(d))
miss = sum(1 for i, v in op.items() if v and kind(v)[0] not in set(per.get(i, [])))
print("officialPhone not in own list", miss)
# sharing: phone -> set of records (list + official), and set of cities
own = collections.defaultdict(set)
for i in range(len(d)):
    s = set(per.get(i, []))
    if op[i] and kind(op[i])[1] != "invalid": s.add(kind(op[i])[0])
    for x in s: own[x].add(i)
city = d.address_city.map(lambda v: "" if nul(v) else re.sub(r"[^a-z]", "", v.lower()))
print("distinct valid phones", len(own))
shared = {x: s for x, s in own.items() if len(s) >= 2}
xc = {x: s for x, s in shared.items() if len({city[i] for i in s} - {""}) >= 2}
print("shared by >=2 records:", len(shared), "| span >=2 cities:", len(xc), "records", len(set().union(*xc.values())))
top = sorted(own.items(), key=lambda t: -len(t[1]))[:5]
for x, s in top:
    print("  top", x, "records", len(s), "cities", len({city[i] for i in s} - {""}), "as officialPhone", sum(1 for i in s if op[i] and kind(op[i])[0] == x))
# official phones held by records in >=3 cities
ncity = {x: len({city[i] for i in s} - {""}) for x, s in own.items()}
offk = op.map(lambda v: kind(v)[0] if v and kind(v)[1] != "invalid" else None)
h3 = offk.map(lambda x: x is not None and ncity.get(x, 0) >= 3)
print("ID5 records whose officialPhone is held by records in >=3 cities:", h3.sum(), "of officialPhone-present", op.notna().sum())
# alt: cities counted over holders other than itself? same thing. Also >=3 cities counting only via officialPhone field
# chain membership by finder's brand list is theirs; approximate with own small brand regex
brands = r"apollo|fortis|manipal|max |max$|narayana|aster|medanta|yashoda|kims|care hospital|rainbow|cloudnine|motherhood|nova ivf|indira ivf|clove dental|sabka dentist|dr\.? agarwal|vasan|maxivision|asg eye|centre for sight|lilavati|columbia asia|sparsh|shalby|hcg|metropolis|srl|thyrocare|pathkind|lal path|dr lal|medicover|sahyadri|ruby hall|kauvery|meenakshi|wockhardt|global hospital|gleneagles|jupiter|ckb|nephroplus|ujala cygnus|paras|zoi|seeds of innocens|bloom ivf|oasis|birla fertility|homeocare|dr batra|max lab|healthians|sunshine"
ch = d.name.str.lower().str.contains(brands, regex=True)
print("  of which name matches my brand regex:", (h3 & ch).sum(), "| non-chain:", (h3 & ~ch).sum())
x = "9693969347"
s = own[x]
urls = collections.Counter(re.sub(r"^https?://(www\.)?", "", u).split("/")[0] for i in s for u in jlist(d.source_urls[i]))
print("9693969347 holders' top source domains", urls.most_common(5))
# lift of proptiger among holders vs all
allp = sum(1 for v in d.source_urls if "proptiger.com" in str(v)) / len(d)
hp = sum(1 for i in s if "proptiger.com" in str(d.source_urls[i])) / len(s)
print("proptiger share holders", round(hp, 3), "all", round(allp, 3), "lift", round(hp / allp, 1))
pd.DataFrame([(x, len(s), ncity[x]) for x, s in own.items() if len(s) >= 2], columns=["phone", "records", "cities"]).sort_values("records", ascending=False).to_csv("/Users/karthikvattem/projects/datathon/audit/identity/verify/v_shared_phones.csv", index=False)
# STD check for metro codes vs state
std = {"11": "delhi", "22": "maharashtra", "33": "west bengal", "44": "tamil nadu", "80": "karnataka", "40": "telangana", "20": "maharashtra", "79": "gujarat"}
pin = pd.read_parquet(RAW + "india_post_pincode_directory.parquet")
pst = pin.groupby("pincode").statename.agg(lambda s: s.mode().iat[0].lower())
pcode = d.address_zipOrPostcode.map(lambda v: (lambda m: int(m.group(0)) if m else None)(re.search(r"[1-9]\d{5}", re.sub(r"\s", "", str(v)))))
n = mm = 0; ex = []
for i in range(len(d)):
    k = offk[i]
    if not isinstance(k, str) or k[0] not in "1234": continue
    c = k[:2] if k[:2] in std else None
    if not c: continue
    if k[:2] in ("80", "40", "20", "79"):
        pass
    else:
        pass
    st = pst.get(pcode[i]) if pcode[i] else None
    if st is None: continue
    n += 1
    exp = std[c]
    ok = exp in st or (exp == "telangana" and "andhra" in st) or (exp == "delhi" and st in ("delhi",))
    if not ok:
        mm += 1; ex.append((d.name[i][:40], k, st))
print("ID6 metro-STD officialPhones with PIN state", n, "mismatch", mm, ex[:6])
