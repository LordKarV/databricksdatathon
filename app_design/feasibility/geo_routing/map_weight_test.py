"""Measure the bytes a phone pays for a Leaflet map with OSM tiles.

Fetches Leaflet 1.9.4 JS and CSS from cdnjs with gzip, and every tile a 360 x 640 CSS px
viewport touches at zoom 12 centred on the rural Madhubani test point (8 tiles here, counting
partial tiles). One request at a time with an identifying User-Agent, well inside the
tile policy (https://operations.osmfoundation.org/policies/tiles/). Writes out/map_weight.json.
"""
import gzip
import json
import math
import time
import urllib.request

from geocode_test import OUT, UA

LEAFLET = {
    "leaflet.js": "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.js",
    "leaflet.css": "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.css",
}
LAT, LON, Z = 26.45, 85.95, 12
VIEW_W, VIEW_H = 360, 640


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
        enc = r.headers.get("Content-Encoding")
        cache = r.headers.get("Cache-Control")
    ms = round((time.perf_counter() - t0) * 1000)
    body = gzip.decompress(raw) if enc == "gzip" else raw
    return {"wire_bytes": len(raw), "bytes": len(body), "encoding": enc, "cache_control": cache, "ms": ms}


def tile_xy(lat, lon, z):
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def main():
    res = {k: fetch(u) for k, u in LEAFLET.items()}
    cx, cy = tile_xy(LAT, LON, Z)
    xs = range(math.floor(cx - VIEW_W / 512), math.floor(cx + VIEW_W / 512) + 1)
    ys = range(math.floor(cy - VIEW_H / 512), math.floor(cy + VIEW_H / 512) + 1)
    tiles = []
    for x in xs:
        for y in ys:
            t = fetch(f"https://tile.openstreetmap.org/{Z}/{x}/{y}.png")
            tiles.append({"z": Z, "x": x, "y": y, **t})
            time.sleep(0.5)
    lib = sum(v["wire_bytes"] for v in res.values())
    tb = sum(t["wire_bytes"] for t in tiles)
    out = {"leaflet": res, "tiles": tiles, "n_tiles": len(tiles), "tile_bytes_total": tb,
           "tile_bytes_mean": round(tb / len(tiles)), "leaflet_wire_bytes": lib,
           "first_map_view_bytes": lib + tb}
    (OUT / "map_weight.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "tiles"}, indent=1))
    assert tile_xy(0, 0, 1) == (1.0, 1.0)


if __name__ == "__main__":
    main()
