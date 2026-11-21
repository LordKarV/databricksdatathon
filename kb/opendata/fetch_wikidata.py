"""Fetch Indian medical facilities from Wikidata (CC0) through the QLever SPARQL mirror.

query.wikidata.org/robots.txt disallows /sparql for all user agents, so we use QLever
(qlever.dev, University of Freiburg), which serves the full Wikidata graph and has no
robots.txt (404, so allowed). Three queries, 2 s apart. Raw JSON and query text go to
data/crawl/opendata/wikidata/.

Run: .venv/bin/python -I kb/opendata/fetch_wikidata.py
"""
import json
import time
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path

UA = "datathon-facility-check/0.1"
ENDPOINT = "https://qlever.dev/api/wikidata"
OUT = Path("/Users/karthikvattem/projects/datathon/data/crawl/opendata/wikidata")
PFX = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX schema: <http://schema.org/>
"""
# Q4260475 medical facility (superclass of hospital Q16917, clinic, health centre...), Q668 India.
BASE = "?item wdt:P31/wdt:P279* wd:Q4260475 ; wdt:P17 wd:Q668 ."
QUERIES = {
    "core": PFX + f"""SELECT ?item ?label ?coord WHERE {{
  {BASE}
  OPTIONAL {{ ?item rdfs:label ?label FILTER(LANG(?label) = "en") }}
  OPTIONAL {{ ?item wdt:P625 ?coord }}
}}""",
    # One long table of the statements we care about; values that are items get an English label.
    # P31 instance of, P6801 beds, P856 website, P137 operator, P131 admin unit, P281 postcode,
    # P1995 health specialty, P912 has facility, P571 inception, P1813 short name, P127 owned by.
    "props": PFX + f"""SELECT ?item ?prop ?value ?valueLabel WHERE {{
  {BASE}
  VALUES ?prop {{ wdt:P31 wdt:P6801 wdt:P856 wdt:P137 wdt:P131 wdt:P281 wdt:P1995 wdt:P912 wdt:P571 wdt:P1813 wdt:P127 }}
  ?item ?prop ?value .
  OPTIONAL {{ ?value rdfs:label ?valueLabel FILTER(LANG(?valueLabel) = "en") }}
}}""",
    # State of each item: walk P131 up to a first-level division of India (Q131541 state, Q467745 UT).
    "state": PFX + f"""SELECT ?item ?state ?stateLabel WHERE {{
  {BASE}
  ?item wdt:P131+ ?state .
  VALUES ?stype {{ wd:Q131541 wd:Q467745 }}
  ?state wdt:P31 ?stype .
  OPTIONAL {{ ?state rdfs:label ?stateLabel FILTER(LANG(?stateLabel) = "en") }}
}}""",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rp = urllib.robotparser.RobotFileParser("https://qlever.dev/robots.txt")
    rp.read()
    assert rp.can_fetch(UA, ENDPOINT), "robots.txt disallows the endpoint"
    for name, q in QUERIES.items():
        (OUT / f"{name}.rq").write_text(q)
        req = urllib.request.Request(
            ENDPOINT, data=urllib.parse.urlencode({"query": q}).encode(),
            headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            body = r.read()
        d = json.loads(body)
        (OUT / f"{name}.json").write_bytes(body)
        print(name, len(d["results"]["bindings"]), "rows", d.get("meta", {}).get("query-time-ms"), "ms")
        time.sleep(2)
    stats = urllib.request.urlopen(urllib.request.Request(ENDPOINT + "?cmd=stats", headers={"User-Agent": UA}),
                                   timeout=60).read()
    (OUT / "qlever_stats.json").write_bytes(stats)
    (OUT / "fetched_at.txt").write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


if __name__ == "__main__":
    main()
