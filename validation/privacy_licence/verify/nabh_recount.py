"""Own recount of restricted-list (NABH / NMC) entries in public-class files and exports (ids + list-only names)."""
import re, sys
sys.path.insert(0, "/Users/karthikvattem/projects/datathon/validation/privacy_licence/verify")
import checks as c
import pandas as pd

nabh = pd.read_parquet(c.ROOT / "data/external/nabh_accredited/nabh_hco.parquet")
nmc = pd.read_parquet(c.ROOT / "data/external/nmc_colleges/nmc_colleges.parquet")
vf = {c.norm(n) for n in c.raw().name.dropna()}
rawtxt = c.read("data/raw/facilities.parquet")
for key, names, ids in (("nabh", nabh.name, nabh.acc_no), ("nmc", nmc.college_name, nmc.college_code)):
    idset = {str(x).strip() for x in ids.dropna() if str(x).strip()} - set(re.findall(r"\S+", rawtxt))
    nn = {n: 1 for n in map(c.norm, names.dropna()) if len(n.split()) >= 3 and len(n) >= 15 and n not in vf}
    in_raw = c.names_in(rawtxt, nn)  # list names the provided table itself mentions are not list copies
    nn = {n: 1 for n in nn if n not in in_raw}
    best = []
    for rel in [r for r in c.tracked() if c.public(r)] + list(c.exports()):
        t = c.read(rel)
        if not t:
            continue
        toks = set(re.findall(r"[A-Za-z0-9/-]+", t))
        n_id = len(idset & toks)
        n_nm = len(c.names_in(t, nn))
        if n_id or n_nm:
            best.append((n_id + n_nm, n_id, n_nm, rel))
    best.sort(reverse=True)
    print(key, "entries", len(names), "list-only ids", len(idset), "list-only names", len(nn), "files", len(best),
          "top", best[:4], flush=True)
