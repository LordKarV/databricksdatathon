"""#117 A: a listed website the crawl flags unreliable is never cited, and the card says so. Display only.

Skips when app/facts/out is not built.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from facts.engine import SITE_STRINGS, Engine  # noqa: E402
from services import SERVICES  # noqa: E402

ENGINE = Engine.load()
pytestmark = pytest.mark.skipif(ENGINE is None, reason="facility data not built (app/facts/build.py)")
REASONS = {"no_usable_page", "no_identity", "other_org"}
PLACES = [(26.5951, 85.4808), (25.6, 85.95), (25.48, 80.33), (25.61, 85.14)]


def _with(flags: dict[int, tuple[str | None, bool]]) -> Engine:
    """A copy of the engine with site_flag / url_site set for some facility indexes."""
    e = copy.copy(ENGINE)
    e.fac = dict(ENGINE.fac, site_flag=list(ENGINE.fac["site_flag"]), url_site=list(ENGINE.fac["url_site"]))
    for i, (flag, site) in flags.items():
        e.fac["site_flag"][i], e.fac["url_site"][i] = flag, site
    return e


def test_strings_have_english_and_hindi():
    for k, v in SITE_STRINGS.items():
        assert set(v) == {"en", "hi"} and v["en"] and v["hi"], k
    assert REASONS <= set(SITE_STRINGS)


def test_export_flags_only_known_reasons():
    assert set(ENGINE.fac["site_flag"]) <= REASONS | {None}
    sc = ENGINE.site_check
    assert sc["n_unreliable"] == sum(sc["by_reason"].values()) == sum(f is not None for f in ENGINE.fac["site_flag"])
    assert sc["n_unreliable"] <= sc["n_with_site"]


def test_flagged_site_is_never_cited():
    for la, lo in PLACES:
        for s in SERVICES:
            for o in ENGINE.plan(s, la, lo, 40, "gps")["options"]:
                i = ENGINE.fid[o["facility_id"]]
                flag = ENGINE.fac["site_flag"][i]
                assert (o["website"] or {}).get("reason") == flag
                if flag:
                    assert "own website" not in o["is_real"] and SITE_STRINGS["label"]["en"] in o["is_real"]
                    if ENGINE.fac["url_site"][i]:
                        assert all(ev["source_url"] == "" for ev in o["evidence"]), o["name"]


@pytest.mark.parametrize("site", [True, False])
def test_flag_changes_citation_not_ranking(site):
    s, la, lo = "dialysis", 24.79, 85.0
    base = ENGINE.plan(s, la, lo, 40, "gps")["options"]
    i = ENGINE.fid[base[0]["facility_id"]]
    e = _with({i: ("no_usable_page", site), **{ENGINE.fid[o["facility_id"]]: (None, False) for o in base[1:]}})
    got = e.plan(s, la, lo, 40, "gps")["options"]
    assert [(o["facility_id"], o["p"], o["band"]) for o in got] == [(o["facility_id"], o["p"], o["band"]) for o in base]
    first = got[0]
    assert first["website"]["reason"] == "no_usable_page"
    assert first["website"]["label"] == SITE_STRINGS["label"]
    assert first["website"]["text"]["en"].startswith(SITE_STRINGS["label"]["en"] + ": ")
    want = "" if site else (ENGINE.fac["url"][i] or "")
    assert [ev["source_url"] for ev in first["evidence"]] == [want] * len(first["evidence"])
    assert first["evidence"], "D: the card keeps its own quotes, so it is never left with no evidence"
    assert all(o["website"] is None for o in got[1:])


def test_unflagged_site_keeps_its_link():
    e = _with({})
    i = next(j for j, (f, u) in enumerate(zip(e.fac["site_flag"], e.fac["url"], strict=True)) if not f and u)
    assert e.cited_url(i) == e.fac["url"][i] and e.website(i) is None
