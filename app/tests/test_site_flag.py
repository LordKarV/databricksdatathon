"""#117 A, BE-001: a listed website the crawl could not check or flags unreliable is never cited, and the card says
which. "unchecked" (no usable page) is neutral with no reason line; "unreliable" (no_identity, other_org) shows its
reason in one short line. Display only: ranking, p and bands are unchanged.

Skips when app/facts/out is not built.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from facts.build import SITE_STATUS  # noqa: E402
from facts.engine import SITE_STRINGS, Engine  # noqa: E402
from services import SERVICES  # noqa: E402

ENGINE = Engine.load()
pytestmark = pytest.mark.skipif(ENGINE is None, reason="facility data not built (app/facts/build.py)")
UNRELIABLE = {"no_identity", "other_org"}
PLACES = [(26.5951, 85.4808), (25.6, 85.95), (25.48, 80.33), (25.61, 85.14)]
LABELS = {"unchecked": ("Listed website could not be checked", "लिस्टिंग की वेबसाइट जाँची नहीं जा सकी"),
          "unreliable": ("Listed website unreliable", "लिस्टिंग में दी गई वेबसाइट भरोसे लायक नहीं")}


def _with(flags: dict[int, tuple[str | None, bool]]) -> Engine:
    """A copy of the engine with the reason code (and its status) and url_site set for some facility indexes."""
    e = copy.copy(ENGINE)
    e.fac = dict(ENGINE.fac, site_flag=list(ENGINE.fac["site_flag"]), site_status=list(ENGINE.fac["site_status"]),
                 url_site=list(ENGINE.fac["url_site"]))
    for i, (flag, site) in flags.items():
        e.fac["site_flag"][i], e.fac["site_status"][i], e.fac["url_site"][i] = flag, SITE_STATUS.get(flag), site
    return e


def test_strings_have_english_and_hindi():
    for k, v in SITE_STRINGS.items():
        assert set(v) == {"en", "hi"} and v["en"] and v["hi"], k
    assert UNRELIABLE <= set(SITE_STRINGS)
    for status, (en, hi) in LABELS.items():
        assert SITE_STRINGS[status] == {"en": en, "hi": hi}


def test_status_follows_reason():
    assert SITE_STATUS == {"no_usable_page": "unchecked", "no_identity": "unreliable", "other_org": "unreliable"}
    for code, status in zip(ENGINE.fac["site_flag"], ENGINE.fac["site_status"], strict=True):
        assert status == SITE_STATUS.get(code), (code, status)


def test_export_counts_by_label_and_reason():
    sc, status = ENGINE.site_check, ENGINE.fac["site_status"]
    assert sc["n_unchecked"] == status.count("unchecked") == sc["by_reason"].get("no_usable_page", 0)
    assert sc["n_unreliable"] == status.count("unreliable") == sum(sc["by_reason"].get(r, 0) for r in UNRELIABLE)
    assert sc["n_flagged"] == sc["n_unchecked"] + sc["n_unreliable"] <= sc["n_with_site"]


@pytest.mark.parametrize("code", ["no_usable_page", "no_identity", "other_org"])
def test_label_and_reason_line(code):
    w = _with({0: (code, True)}).website(0)
    status = SITE_STATUS[code]
    assert w["site_status"] == status and w["reason"] == code
    assert (w["label"]["en"], w["label"]["hi"]) == LABELS[status]
    if status == "unchecked":  # neutral: no reason against the site, on the card or the Why page
        assert w["reason_line"] is None
        assert w["text"]["en"] == "Listed website could not be checked. We do not cite it as a source."
        assert w["text"]["hi"] == "लिस्टिंग की वेबसाइट जाँची नहीं जा सकी। " + SITE_STRINGS["not_cited"]["hi"]
    else:
        en = SITE_STRINGS[code]["en"]
        assert w["reason_line"] == {"en": en[0].upper() + en[1:] + ".", "hi": SITE_STRINGS[code]["hi"] + "।"}
        assert w["text"]["en"] == f"Listed website unreliable: {en}. We do not cite it as a source."
        assert len(w["reason_line"]["en"]) <= 60, "one short line"


def test_flagged_site_is_never_cited():
    for la, lo in PLACES:
        for s in SERVICES:
            for o in ENGINE.plan(s, la, lo, 40, "gps")["options"]:
                i = ENGINE.fid[o["facility_id"]]
                status = ENGINE.fac["site_status"][i]
                assert (o["website"] or {}).get("site_status") == status
                assert (o["website"] or {}).get("reason") == ENGINE.fac["site_flag"][i]
                if status:
                    assert "own website" not in o["is_real"] and SITE_STRINGS[status]["en"] in o["is_real"]
                    if ENGINE.fac["url_site"][i]:
                        assert all(ev["source_url"] == "" for ev in o["evidence"]), o["name"]


@pytest.mark.parametrize("code", ["no_usable_page", "no_identity", "other_org"])
@pytest.mark.parametrize("site", [True, False])
def test_label_changes_citation_not_ranking(code, site):
    s, la, lo = "dialysis", 24.79, 85.0
    base = ENGINE.plan(s, la, lo, 40, "gps")["options"]
    i = ENGINE.fid[base[0]["facility_id"]]
    e = _with({i: (code, site), **{ENGINE.fid[o["facility_id"]]: (None, False) for o in base[1:]}})
    got = e.plan(s, la, lo, 40, "gps")["options"]
    assert [(o["facility_id"], o["p"], o["band"]) for o in got] == [(o["facility_id"], o["p"], o["band"]) for o in base]
    first = got[0]
    assert (first["website"]["site_status"], first["website"]["reason"]) == (SITE_STATUS[code], code)
    want = "" if site else (ENGINE.fac["url"][i] or "")
    assert [ev["source_url"] for ev in first["evidence"]] == [want] * len(first["evidence"])
    assert first["evidence"], "D: the card keeps its own quotes, so it is never left with no evidence"
    assert all(o["website"] is None for o in got[1:])


def test_unflagged_site_keeps_its_link():
    e = _with({})
    i = next(j for j, (f, u) in enumerate(zip(e.fac["site_status"], e.fac["url"], strict=True)) if not f and u)
    assert e.cited_url(i) == e.fac["url"][i] and e.website(i) is None
