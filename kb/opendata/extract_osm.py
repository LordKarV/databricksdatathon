"""Extract every OSM health feature in India with ALL tags from the Geofabrik extract.

Why not the HOT export or Overpass: the HOT export keeps 12 tags (no opening_hours, emergency,
beds, phone, website); overpass-api.de/robots.txt disallows /api/; the two public mirrors timed
out on a 3-node test query. The Geofabrik extract is one 1.7 GB download (robots.txt allows it)
and carries version and timestamp but no user names.

Run: .venv-kb2/bin/python -I kb/opendata/extract_osm.py <india.osm.pbf> <out.parquet>
Output: one row per feature: osm_id ("node/123"), lat, lon (way = mean of node locations,
relation = no coordinate here, filled later from the HOT export), version, timestamp, tags (JSON).
"""
import json
import sys

import osmium
import pandas as pd

AMENITY = {"hospital", "clinic", "doctors", "dentist", "health_post", "nursing_home"}


def keep(tags: dict) -> bool:
    if tags.get("amenity") in AMENITY:
        return True
    hc = tags.get("healthcare")
    return hc is not None and hc not in ("pharmacy", "no")


def main(pbf: str, out: str) -> None:
    fp = (osmium.FileProcessor(pbf)
          .with_locations()
          .with_filter(osmium.filter.KeyFilter("amenity", "healthcare")))
    rows = []
    for o in fp:
        tags = dict(o.tags)
        if not keep(tags):
            continue
        lat = lon = None
        if o.is_node():
            kind = "node"
            lat, lon = o.location.lat, o.location.lon
        elif o.is_way():
            kind = "way"
            pts = [(n.location.lat, n.location.lon) for n in o.nodes if n.location.valid()]
            if pts:  # ponytail: vertex mean, not area centroid; fine for buildings and campuses
                lat, lon = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
        else:
            kind = "relation"
        rows.append(dict(osm_id=f"{kind}/{o.id}", lat=lat, lon=lon, version=o.version,
                         timestamp=o.timestamp.isoformat() if o.timestamp else None,
                         tags=json.dumps(tags, ensure_ascii=False)))
    df = pd.DataFrame(rows)
    df.to_parquet(out, index=False)
    print(len(df), df.osm_id.str.split("/").str[0].value_counts().to_dict())


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
