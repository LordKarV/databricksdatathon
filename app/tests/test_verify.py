"""Live website check (issue #37) on recorded fixtures: no network. Pages live in app/verify/fixtures."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from verify import check as V  # noqa: E402

FIX = APP / "verify" / "fixtures"
FID = "fac-asha"
SITE = {"name": "Asha Kidney Care Hospital", "city": "Darbhanga", "urls": ["https://www.ashakidney.example/"]}
ROBOTS_OK = "User-agent: *\nDisallow: /private/\n"


def html(name: str) -> bytes:
    return (FIX / name).read_bytes()


class Net:
    """Recorded responses keyed by URL, a fake clock that only moves when the checker sleeps or a fetch costs time."""

    def __init__(self, pages: dict[str, tuple[int, bytes] | Exception], cost: float = 0.1) -> None:
        self.pages, self.cost, self.t = pages, cost, 1000.0
        self.calls: list[tuple[float, str]] = []
        self.wall = 1_700_000_000.0

    def transport(self, url: str, timeout: float) -> V.Page:
        self.calls.append((self.t, url))
        self.t += self.cost
        got = self.pages.get(url, (404, b""))
        if isinstance(got, Exception):
            raise got
        status, body = got
        return V.Page(status, url, "text/html; charset=utf-8", body)

    def sleep(self, s: float) -> None:
        self.t += s

    def checker(self, sites: dict | None = None) -> V.Checker:
        polite = V.Polite(self.transport, clock=lambda: self.t, sleep=self.sleep)
        return V.Checker(sites if sites is not None else {FID: SITE}, V.Lexicon.load(FIX / "lexicon.json"),
                         polite=polite, now=lambda: self.wall)


BASE = "https://www.ashakidney.example"


def site_pages(**over) -> dict:
    pages = {BASE + "/robots.txt": (200, ROBOTS_OK.encode()), BASE + "/": (200, html("home.html")),
             BASE + "/departments/nephrology-and-dialysis": (200, html("dialysis.html")),
             BASE + "/about-us": (200, b"<p>About Asha Kidney Care Hospital.</p>"),
             BASE + "/contact": (200, b"<p>Call us.</p>"), BASE + "/emergency": (200, b"<p>Emergency 24x7.</p>")}
    pages.update(over)
    return pages


def test_found_with_verbatim_quotes_service_page_first():
    net = Net(site_pages())
    r = net.checker().check(FID, "dialysis")
    assert r["status"] == "found" and r["status_text"] == "website lists"
    assert r["quotes"][0] == {"text": "Our dialysis unit has 10 haemodialysis machines and runs 24 hours a day.",
                              "url": BASE + "/departments/nephrology-and-dialysis", "says": "yes"}
    assert all(q["says"] == "yes" for q in r["quotes"]) and len(r["quotes"]) <= 2
    # negated and future sentences are not counted as offered
    assert not any("not available" in q["text"] or "will be started" in q["text"] for q in r["quotes"])
    assert r["pages_checked"][1] == BASE + "/departments/nephrology-and-dialysis"  # service link followed first
    assert len(r["pages_checked"]) <= V.MAX_PAGES
    assert not any("elsewhere.example" in u for u in r["pages_checked"])  # same site only


def test_negated_only_is_not_mentioned_with_its_quote():
    net = Net(site_pages(**{BASE + "/": (200, html("negated.html"))}))
    r = net.checker().check(FID, "dialysis")
    assert r["status"] == "not_mentioned"
    assert r["quotes"] and all(q["says"] == "no" for q in r["quotes"])


def test_other_facility_site_is_wrong_site():
    net = Net(site_pages(**{BASE + "/": (200, html("other.html"))}))
    r = net.checker().check(FID, "dialysis")
    assert r["status"] == "wrong_site" and r["quotes"] == []


@pytest.mark.parametrize("pages", [
    {BASE + "/robots.txt": (200, b"User-agent: *\nDisallow: /\n"), BASE + "/": (200, b"<p>dialysis</p>")},
    {BASE + "/robots.txt": (403, b""), BASE + "/": (200, b"<p>dialysis</p>")},
    {BASE + "/robots.txt": OSError("timed out")},
    {BASE + "/robots.txt": (200, b""), BASE + "/": (503, b"")},
], ids=["robots-disallow", "robots-403", "network-error", "server-error"])
def test_unreachable(pages):
    net = Net(pages)
    r = net.checker().check(FID, "dialysis")
    assert r["status"] == "unreachable"
    assert not any(u == BASE + "/" for _, u in net.calls) or pages.get(BASE + "/", (0,))[0] == 503


def test_robots_disallowed_path_is_skipped():
    net = Net(site_pages(**{BASE + "/robots.txt": (200, b"User-agent: *\nDisallow: /departments/\n")}))
    r = net.checker().check(FID, "dialysis")
    assert not any("/departments/" in u for _, u in net.calls)
    assert r["status"] == "not_mentioned"


def test_one_request_per_second_per_domain_and_page_cap():
    net = Net(site_pages())
    net.checker().check(FID, "dialysis")
    times = [t for t, _ in net.calls]
    assert all(b - a >= V.PER_DOMAIN_GAP_S - 1e-9 for a, b in zip(times, times[1:], strict=False))
    pages = [u for _, u in net.calls if not u.endswith("/robots.txt")]
    assert len(pages) <= V.MAX_PAGES


def test_total_budget_is_8_seconds():
    net = Net(site_pages(), cost=3.0)  # each fetch takes 3 s
    start = net.t
    r = net.checker().check(FID, "dialysis")
    assert net.t - start <= V.BUDGET_S + 3.0  # the last fetch may finish after the budget, none starts after it
    assert all(t - start < V.BUDGET_S for t, _ in net.calls)
    assert r["status"] in ("found", "not_mentioned", "unreachable")


def test_cache_24h_keeps_only_quotes_and_urls():
    net = Net(site_pages())
    ch = net.checker()
    r1 = ch.check(FID, "dialysis")
    n = len(net.calls)
    r2 = ch.check(FID, "dialysis")
    assert r2["cached"] is True and len(net.calls) == n and r2["quotes"] == r1["quotes"]
    stored = json.dumps(list(ch._cache.values()))
    assert "SECRET-BODY-MARKER" not in stored and "<p>" not in stored
    net.wall += V.CACHE_TTL_S + 1
    assert ch.check(FID, "dialysis")["cached"] is False and len(net.calls) > n


def test_no_website_on_record():
    r = Net({}).checker().check("stub-101", "dialysis")
    assert r["status"] == "no_website" and r["status_text"] == "no official website on record"


def test_transport_sends_user_agent_and_blocks_private_hosts(monkeypatch):
    with pytest.raises(OSError):
        V.urllib_transport("http://127.0.0.1:9/", 1)
    seen = {}

    class Resp:
        status, headers = 200, {"Content-Type": "text/html"}

        def geturl(self):
            return "https://example.org/"

        def read(self, n):
            return b"ok"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(V, "_public_host", lambda h: True)
    monkeypatch.setattr(V._OPENER, "open", lambda req, timeout: seen.update(ua=req.get_header("User-agent")) or Resp())
    assert V.urllib_transport("https://example.org/", 1).body == b"ok"
    assert seen["ua"] == V.USER_AGENT == "datathon-facility-check/0.1"


def test_endpoint(monkeypatch):
    from fastapi.testclient import TestClient

    import app as app_module
    c = TestClient(app_module.app)
    monkeypatch.setattr(app_module, "_checker", lambda: None)
    assert c.post("/api/verify", json={"facility_id": FID, "service_id": "dialysis"}).status_code == 503
    net = Net(site_pages())
    monkeypatch.setattr(app_module, "_checker", lambda: net.checker())
    r = c.post("/api/verify", json={"facility_id": FID, "service_id": "dialysis"})
    assert r.status_code == 200 and r.json()["status"] == "found"
    assert c.post("/api/verify", json={"facility_id": FID, "service_id": "x"}).status_code == 422
    assert c.post("/api/verify", json={"facility_id": "a/b", "service_id": "dialysis"}).status_code == 422
