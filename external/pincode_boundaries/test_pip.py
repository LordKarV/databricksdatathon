"""Self-check for the WKB parser and point-in-polygon in join_test.py. Run: python -I test_pip.py"""
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from join_test import contains, dist_km, parse_wkb  # noqa: E402


def ring(pts):
    return struct.pack("<I", len(pts)) + b"".join(struct.pack("<dd", *p) for p in pts)


outer = [(0, 0), (4, 0), (4, 4), (0, 4), (0, 0)]
hole = [(1, 1), (2, 1), (2, 2), (1, 2), (1, 1)]
poly = struct.pack("<BII", 1, 3, 2) + ring(outer) + ring(hole)
multi = struct.pack("<BII", 1, 6, 2) + poly + struct.pack("<BII", 1, 3, 1) + ring([(10, 10), (11, 10), (11, 11), (10, 10)])

g = parse_wkb(multi)
assert len(g) == 2 and len(g[0]) == 2
x = np.array([3.0, 1.5, 5.0, 10.8])
y = np.array([3.0, 1.5, 5.0, 10.2])
assert contains(g, x, y).tolist() == [True, False, False, True]
assert abs(dist_km(parse_wkb(poly), 5.0, 2.0) - 111.32 * np.cos(np.radians(2.0))) < 0.5
print("ok")
