"""Build crawl targets: candidate official websites per usable facility record.

Candidates = officialWebsite + websites + source_urls, kept only when the provenance classifier
(audit/provenance/domains.py) calls the host 'official' or 'official_like'. URL shorteners and
site builders that never name one facility are dropped. Hosts are grouped by registrable domain.

A domain claimed by records in 2+ cities (or 2+ records outside one duplicate group) is 'shared'
(chains: Apollo, Fortis, Manipal...). For a shared domain each record with a branch-specific URL
(non-root path on that domain) gets its own 'branch' target; the domain homepage is one
'shared_home' target linked to every record. Unshared domains get one 'site' target.

Order: hospitals, then clinics, then dentists/other; inside a tier, round-robin over states so
every state shows up early. Writes kb/crawl/targets.parquet and kb/crawl/targets_stats.json.
"""
import json
import re
import sys
from collections import Counter, defaultdict
from urllib.parse import urlparse

import pandas as pd

ROOT = "/Users/karthikvattem/projects/datathon"
sys.path.insert(0, f"{ROOT}/audit/provenance")
from common import facilities, host, jlist  # noqa: E402
from domains import classify  # noqa: E402

OUT = f"{ROOT}/kb/crawl"
# hosts that classify as official_like by name match but never belong to one facility
NOT_A_SITE = re.compile(r"(^|\.)(business\.site|g\.page|g\.co|bit\.ly|goo\.gl|sites\.google\.com|tinyurl\.com|"
                        r"linktr\.ee|near-place\.com|wheree\.com|wixsite\.com|weebly\.com|webs\.com|"
                        r"site123\.me|godaddysites\.com|ueniweb\.com|mystrikingly\.com|negocio\.site|"
                        r"wa\.me|api\.whatsapp\.com|t\.me|google\.com|google\.co\.in|infoisinfo\.co\.in|indiamart\.com|"
                        r"infoaboutcompanies\.com|5bestincity\.com|placestars\.com|homeopathiccolleges\.com|"
                        r"ayurveda\.in)$")
SECOND_LEVEL = {"co", "org", "net", "gov", "ac", "edu", "nic", "gen", "firm", "ind", "res", "com", "ltd", "plc"}
TIER = {"hospital": 0, "nursing_home": 0, "clinic": 1, "dentist": 2}


def reg_domain(h: str) -> str:
    """Approximate registrable domain: last two labels, or three for x.co.in style names.
    ponytail: no public-suffix list; fine for .in/.com/.org, wrong for rare ccTLD+2 suffixes."""
    parts = h.strip(".").split(".")
    if len(parts) >= 3 and parts[-2] in SECOND_LEVEL and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def norm_url(u: str) -> str | None:
    u = u.strip().strip("\"'")
    if not u:
        return None
    if "://" not in u:
        u = "https://" + u
    try:
        p = urlparse(u)
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not p.hostname or "." not in p.hostname:
        return None
    path = p.path or "/"
    return f"{p.scheme}://{p.hostname.lower()}{path}" + (f"?{p.query}" if p.query else "")


def is_root(u: str) -> bool:
    p = urlparse(u)
    return p.path in ("", "/") or re.fullmatch(r"/(index|home|default)\.(html?|php|aspx?)", p.path or "") is not None


def candidates(df: pd.DataFrame) -> tuple[pd.DataFrame, Counter]:
    rows, cls = [], Counter()
    for r in df.itertuples():
        w = r.officialWebsite
        off = {host(w)} if isinstance(w, str) and w not in ("null", "") else set()
        for field, urls in (("officialWebsite", [w] if off else []), ("websites", jlist(r.websites)),
                            ("source_urls", jlist(r.source_urls))):
            for u in urls:
                h = host(u)
                c = classify(h, off, r.name)
                cls[c] += 1
                if c not in ("official", "official_like"):
                    continue
                nu = norm_url(u)
                if nu is None or NOT_A_SITE.search(urlparse(nu).hostname or ""):
                    cls["dropped_not_a_site_or_bad_url"] += 1
                    continue
                h2 = urlparse(nu).hostname
                site = re.sub(r"^(www\d?|m)\.", "", h2)
                rows.append((r.unique_id, field, c, nu, site, reg_domain(h2)))
    cand = pd.DataFrame(rows, columns=["unique_id", "field", "cls", "url", "site", "domain"]).drop_duplicates(["unique_id", "url"])
    return cand, cls


def gov_sample(df: pd.DataFrame) -> list[str]:
    """A few government-portal URLs from the data, for the one reachability probe."""
    out = []
    for r in df.itertuples():
        for u in jlist(r.source_urls):
            if classify(host(u), set(), r.name) == "government":
                out.append(u)
        if len(out) >= 20:
            break
    return out


def main() -> None:
    df = facilities()
    loc = pd.read_parquet(f"{ROOT}/cleaning/geo_identity/facility_location.parquet")[["unique_id", "state_final", "address_city"]]
    grp = pd.read_parquet(f"{ROOT}/cleaning/geo_identity/facility_groups.parquet")[["unique_id", "dup_group_id"]]
    meta = df[["unique_id", "name", "facilityTypeId"]].merge(loc, on="unique_id", how="left").merge(grp, on="unique_id", how="left")
    meta = meta.drop_duplicates("unique_id").set_index("unique_id")
    cand, cls = candidates(df)
    cand = cand.join(meta, on="unique_id")

    # site = host without www/m: site builders (placeweb.site, setmore.com) host one facility per
    # subdomain, so the site, not the registrable domain, is the unit; domain is the rate-limit key
    by_dom = cand.groupby("site").agg(n_rec=("unique_id", "nunique"), n_city=("address_city", "nunique"),
                                        n_grp=("dup_group_id", "nunique"))
    shared = set(by_dom[(by_dom.n_city > 1) | (by_dom.n_grp > 1)].index)

    targets = []
    for dom, g in cand.groupby("site"):
        rdom = g.domain.iloc[0]
        uids = sorted(g.unique_id.unique())
        given = [u for u in dict.fromkeys(g.url) if not is_root(u)]
        scheme = "http" if (g.url.str.startswith("http://").all()) else "https"
        hosts = Counter(urlparse(u).hostname for u in g.url)
        home = f"{scheme}://{hosts.most_common(1)[0][0]}/"
        if dom not in shared:
            targets.append(dict(target_id=dom, site=dom, domain=rdom, kind="site", shared=False, seeds=[home] + given[:2],
                                unique_ids=uids))
            continue
        targets.append(dict(target_id=dom, site=dom, domain=rdom, kind="shared_home", shared=True, seeds=[home], unique_ids=uids))
        for uid, gu in g.groupby("unique_id"):
            branch = [u for u in dict.fromkeys(gu.url) if not is_root(u)]
            if branch:
                targets.append(dict(target_id=f"{dom}#{uid[:8]}", site=dom, domain=rdom, kind="branch", shared=True,
                                    seeds=branch[:3], unique_ids=[uid]))
    t = pd.DataFrame(targets)
    t["facility_types"] = t.unique_ids.map(lambda us: sorted({str(meta.facilityTypeId.get(u)) for u in us}))
    t["states"] = t.unique_ids.map(lambda us: sorted({s for s in (meta.state_final.get(u) for u in us) if isinstance(s, str)}))
    t["tier"] = t.facility_types.map(lambda fs: min(TIER.get(f, 3) for f in fs))
    # shared_home pages only describe the chain; crawl them after branch and own-site targets of the same tier
    t["tier"] = t.tier + t.kind.eq("shared_home").astype(int) * 0.5
    t["state0"] = t.states.map(lambda s: s[0] if s else "UNKNOWN")
    t["rank_in_state"] = t.groupby(["tier", "state0"]).cumcount()
    t = t.sort_values(["tier", "rank_in_state", "state0"]).reset_index(drop=True)
    t["priority"] = range(len(t))
    t = t.drop(columns=["state0", "rank_in_state"])
    t.to_parquet(f"{OUT}/targets.parquet", index=False)

    recs = set(cand.unique_id)
    usable = meta.index.nunique()
    ft = meta.facilityTypeId.astype(str)
    stats = {
        "usable_records": int(usable),
        "url_class_counts_all_candidate_fields": dict(cls.most_common()),
        "records_with_official_candidate": len(recs),
        "records_without_official_candidate": int(usable - len(recs)),
        "records_with_candidate_by_type": {k: [int(sum(1 for u in recs if ft.get(u) == k)), int((ft == k).sum())]
                                           for k in ft.value_counts().index},
        "sites": int(cand.site.nunique()),
        "registrable_domains": int(cand.domain.nunique()),
        "shared_sites": len(shared),
        "targets_by_kind": t.kind.value_counts().to_dict(),
        "targets_total": len(t),
        "targets_by_tier": {str(k): int(v) for k, v in t.tier.value_counts().sort_index().items()},
        "records_with_candidate_by_state": dict(Counter(meta.state_final.get(u) or "UNKNOWN" for u in recs).most_common()),
        "largest_shared_sites": by_dom.loc[sorted(shared)].sort_values("n_rec", ascending=False).head(25).n_rec.to_dict(),
        "gov_probe_candidates": gov_sample(df)[:5],
    }
    json.dump(stats, open(f"{OUT}/targets_stats.json", "w"), indent=1, default=int)
    print(json.dumps({k: v for k, v in stats.items() if k != "url_class_counts_all_candidate_fields"}, indent=1, default=int))


if __name__ == "__main__":
    assert reg_domain("www.apollohospitals.com") == "apollohospitals.com"
    assert reg_domain("kims.co.in") == "kims.co.in" and reg_domain("a.b.org.in") == "b.org.in"
    assert norm_url("drrajskin.in") == "https://drrajskin.in/"
    assert is_root("https://x.com/index.html") and not is_root("https://x.com/contact")
    assert NOT_A_SITE.search("abc.business.site") and not NOT_A_SITE.search("mybusiness.com")
    main()
