"""Minimal single-band float32 GeoTIFF reader using only numpy and zlib.

Why: the venv has no rasterio/GDAL/tifffile and we may not pip install. The
GeoServer WCS output is a plain single-band tiled or stripped TIFF, so a small
reader covers it. Supports compression 1 (none) and 8 (deflate), big or little
endian, strips or tiles. ponytail: no predictor, no BigTIFF, no multi-band;
switch to rasterio on Databricks where it can be installed.

Returns (array[rows, cols] float32, geo) where geo = (lon0, lat0, dlon, dlat)
for the upper-left corner of the upper-left cell, from ModelTiepoint (33922)
and ModelPixelScale (33550), or ModelTransformation (34264).
"""
import struct
import zlib

import numpy as np

TYPES = {1: ("B", 1), 2: ("c", 1), 3: ("H", 2), 4: ("I", 4), 5: ("II", 8), 6: ("b", 1), 7: ("B", 1), 8: ("h", 2), 9: ("i", 4), 10: ("ii", 8), 11: ("f", 4), 12: ("d", 8), 16: ("Q", 8)}


def _tags(buf, endian):
    (ifd,) = struct.unpack(endian + "I", buf[4:8])
    (n,) = struct.unpack(endian + "H", buf[ifd:ifd + 2])
    tags = {}
    for k in range(n):
        tag, typ, cnt, val = struct.unpack(endian + "HHI4s", buf[ifd + 2 + 12 * k: ifd + 14 + 12 * k])
        fmt, size = TYPES[typ]
        raw = val if cnt * size <= 4 else buf[struct.unpack(endian + "I", val)[0]:][: cnt * size]
        tags[tag] = struct.unpack(endian + fmt * cnt, raw[: cnt * size]) if typ != 2 else raw[:cnt]
    return tags


def read(path):
    with open(path, "rb") as fh:
        buf = fh.read()
    endian = {b"MM": ">", b"II": "<"}[buf[:2]]
    if struct.unpack(endian + "H", buf[2:4])[0] != 42:
        raise ValueError("not a classic TIFF")
    t = _tags(buf, endian)
    width, height = t[256][0], t[257][0]
    if t[258][0] != 32 or t.get(339, (3,))[0] != 3 or t.get(277, (1,))[0] != 1:
        raise ValueError("expected single-band float32")
    comp = t.get(259, (1,))[0]
    if comp not in (1, 8) or t.get(317, (1,))[0] != 1:
        raise ValueError(f"unsupported compression/predictor {comp}")
    dt = np.dtype(endian + "f4")

    def chunk(off, cnt, shape):
        data = buf[off:off + cnt]
        if comp == 8:
            data = zlib.decompress(data)
        return np.frombuffer(data, dt, count=shape[0] * shape[1]).reshape(shape)

    out = np.empty((height, width), np.float32)
    if 322 in t:  # tiled
        tw, th = t[322][0], t[323][0]
        across = -(-width // tw)
        for i, (off, cnt) in enumerate(zip(t[324], t[325])):
            r, c = divmod(i, across)
            tile = chunk(off, cnt, (th, tw))
            r0, c0 = r * th, c * tw
            h, w = min(th, height - r0), min(tw, width - c0)
            out[r0:r0 + h, c0:c0 + w] = tile[:h, :w]
    else:  # strips
        rps = t.get(278, (height,))[0]
        for i, (off, cnt) in enumerate(zip(t[273], t[279])):
            r0 = i * rps
            h = min(rps, height - r0)
            out[r0:r0 + h] = chunk(off, cnt, (h, width))
    if 34264 in t:  # ModelTransformation (GeoServer writes this, no rotation)
        m = t[34264]
        return out, (m[3], m[7], m[0], -m[5])
    sx, sy = t[33550][0], t[33550][1]
    _, _, _, lon0, lat0, _ = t[33922][:6]
    return out, (lon0, lat0, sx, sy)


if __name__ == "__main__":
    import sys

    a, g = read(sys.argv[1])
    print(a.shape, g, float(np.nanmin(a)), float(np.nanmax(a)))
