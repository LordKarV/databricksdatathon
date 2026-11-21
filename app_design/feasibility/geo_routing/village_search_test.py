"""Typed village name fallback: Nominatim search (4 user-style queries) vs the offline post office gazetteer.

Nominatim: 1 request per 1.1 s, identifying User-Agent, cached in out/nominatim_search_cache.json,
countrycodes=in. Searching on submit only; search-as-you-type is forbidden by the policy.
Writes out/village_search.json.
"""
import json
import time
import urllib.parse
import urllib.request

import pandas as pd

from geocode_test import OUT, UA, offline_tables

QUERIES = ["Muhra", "Muhra, Gaya", "Makepalli, Gadchiroli", "Ghat Sawali"]
CACHE = OUT / "nominatim_search_cache.json"


def search(q, cache):
    if q in cache:
        return cache[q]
    p = urllib.parse.urlencode({"q": q, "format": "jsonv2", "countrycodes": "in", "limit": 5,
                                "addressdetails": 1, "accept-language": "en"})
    req = urllib.request.Request(f"https://nominatim.openstreetmap.org/search?{p}", headers={"User-Agent": UA})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=20) as r:
        body = json.load(r)
    cache[q] = {"ms": round((time.perf_counter() - t0) * 1000), "body": body}
    time.sleep(1.1)
    return cache[q]


def main():
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    _, off = offline_tables()
    off["base"] = off.officename.str.lower().str.replace(r"\s+(b\.?o|s\.?o|h\.?o)\.?$", "", regex=True).str.strip()
    out = []
    for q in QUERIES:
        r = search(q, cache)
        CACHE.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
        name = q.split(",")[0].strip().lower()
        hits = off[off.base == name]
        if "," in q:
            hits = hits[hits.district.str.lower() == q.split(",")[1].strip().lower()]
        out.append({
            "query": q, "nominatim_ms": r["ms"], "nominatim_n": len(r["body"]),
            "nominatim_top": [{"name": h.get("name"), "type": h.get("addresstype"),
                               "district": h.get("address", {}).get("state_district"),
                               "state": h.get("address", {}).get("state"), "lat": h["lat"], "lon": h["lon"]}
                              for h in r["body"][:5]],
            "offline_office_n": len(hits),
            "offline_offices": hits[["officename", "pincode", "district", "statename"]].head(8).to_dict("records"),
        })
    (OUT / "village_search.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str))
    for o in out:
        print(o["query"], "| nominatim", o["nominatim_n"], [(t["name"], t["district"], t["state"]) for t in o["nominatim_top"]],
              "| offline", o["offline_office_n"], [(x["officename"], x["district"]) for x in o["offline_offices"]])


if __name__ == "__main__":
    main()
