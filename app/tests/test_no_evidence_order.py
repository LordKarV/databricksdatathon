"""#117 D: a pair with no quote of its own is never ranked above a pair with one.

The options rest on `_ranked`'s citation rule (#85): a pair with no usable quote is not offered at all, so it cannot
rank above a quoted one. Route stops come from the planner; a stop with no quote of its own is one whose capability is
implied by another strongly evidenced capability of the same facility (planner/implied.py), and that facility has its
own quote for the service asked. Skips when app/facts/out is not built.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
import itinerary  # noqa: E402
from facts.engine import Engine  # noqa: E402
from services import SERVICES  # noqa: E402

ENGINE = Engine.load()
pytestmark = pytest.mark.skipif(ENGINE is None, reason="facility data not built (app/facts/build.py)")
# The demo places of validation/demo_qa.py (that script runs on import, so the points are repeated here).
PTS = {"Sitamarhi": (26.5951, 85.4808), "Mohania": (25.15, 83.68), "Pusa": (25.6, 85.95), "Patna": (25.61, 85.14),
       "Gaya": (24.78, 85.0), "Bahraich": (27.57, 81.6), "Banda": (25.48, 80.33), "Darbhanga": (26.15, 85.9)}


def _demo_plans():
    for place, (la, lo) in PTS.items():
        for s in SERVICES:
            yield place, s, itinerary.attach(ENGINE.plan(s, la, lo, 40, "gps"), ENGINE)


@pytest.fixture(scope="module")
def demo():
    return list(_demo_plans())


def test_every_demo_option_cites_its_own_quote(demo):
    for place, s, p in demo:
        for o in p["options"]:
            assert o["evidence"], (place, s, o["name"])


def test_route_stop_without_a_quote_rests_on_its_own_evidence(demo):
    for place, s, p in demo:
        for r in (p.get("itinerary") or {}).get("plans", []):
            for st in r["stops"]:
                if st["evidence"]:
                    continue
                fid = st["facility_id"]
                assert st["n_evidence"] == 0, (place, s, st["name"])  # not a quote the server lacks
                assert ENGINE.score(fid, s)[5], (place, s, st["name"])  # own quote for the service asked
                assert ENGINE._f("url", ENGINE.fid[fid]), (place, s, st["name"])


def test_no_quote_pair_never_ranks_above_a_quoted_one(monkeypatch):
    # Take the nearest-first service's first option away its quotes: it leaves the list, the rest keep their order.
    s, la, lo = "trauma_emergency", 25.15, 83.68
    before = [o["facility_id"] for o in ENGINE.plan(s, la, lo, 40, "gps")["options"]]
    assert len(before) >= 2
    real = Engine.score

    def drop_first(self, facility_id, service_id):
        band, p, lo_, hi, contrib, ev = real(self, facility_id, service_id)
        return (band, 0.99, lo_, hi, contrib, []) if facility_id == before[0] else (band, p, lo_, hi, contrib, ev)

    monkeypatch.setattr(Engine, "score", drop_first)
    after = [o["facility_id"] for o in ENGINE.plan(s, la, lo, 40, "gps")["options"]]
    assert before[0] not in after
    # #140 2b: a facility whose town disagrees with its map point is never emergency option 1 (Sharda, here)
    rest, far = before[1:], ENGINE.fac.get("town_far") or [None] * len(ENGINE.fid)
    k = next((j for j, f in enumerate(rest) if not far[ENGINE.fid[f]]), 0)
    assert after[: len(rest)] == [rest[k], *rest[:k], *rest[k + 1:]]
