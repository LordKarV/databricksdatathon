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


# ---------- transport hardening (#40): http(s) only, pinned checked addresses ----------
DNS = {"hospital.example": ["203.0.113.7"], "private.example": ["10.0.0.5"],
       "mixed.example": ["203.0.113.8", "192.168.1.9"], "cdn.example": ["198.51.100.4"]}
# 203.0.113.0/24 and 198.51.100.0/24 are documentation ranges (not global); treat them as public in this stub.
PUBLIC_DOC = ("203.0.113.", "198.51.100.")


class FakeResp:
    def __init__(self, status: int, headers: dict, body: bytes) -> None:
        self.status, self._h, self._b = status, headers, body

    def getheader(self, k):
        return self._h.get(k)

    def read(self, n):  # a stream: each read consumes, like http.client
        out, self._b = self._b[:n], self._b[n:]
        return out


class Wire:
    """Stub DNS plus fake pinned connections; responses keyed by (host, path)."""

    def __init__(self, monkeypatch, responses: dict) -> None:
        self.responses, self.opened, self.sent = responses, [], []
        real_ip = V.ipaddress.ip_address

        class Addr:
            def __init__(self, a):
                self._ip = real_ip(a)
                self.is_global = self._ip.is_global or a.startswith(PUBLIC_DOC)

        monkeypatch.setattr(V.ipaddress, "ip_address", Addr)
        monkeypatch.setattr(V.socket, "getaddrinfo", self.getaddrinfo)
        monkeypatch.setattr(V, "open_connection", self.open)

    def getaddrinfo(self, host, port, *a, **k):
        try:
            addrs = [str(V.ipaddress.ip_address(host)._ip)]
        except ValueError:
            if host not in DNS:
                raise OSError("NXDOMAIN") from None
            addrs = DNS[host]
        return [(2, 1, 6, "", (x, port)) for x in addrs]

    def open(self, scheme, host, ip, port, timeout):
        self.opened.append((scheme, host, ip, port))
        wire = self

        class Conn:
            def request(self, method, path, headers):
                wire.sent.append((host, path, headers))
                self.path = path

            def getresponse(self):
                status, headers, body = wire.responses[(host, self.path)]
                return FakeResp(status, headers, body)

            def close(self):
                pass

        return Conn()


def test_connects_to_the_checked_address_with_hostname_headers(monkeypatch):
    w = Wire(monkeypatch, {("hospital.example", "/x?a=1"): (200, {"Content-Type": "text/html"}, b"<p>ok</p>")})
    page = V.http_transport("https://hospital.example/x?a=1", 2)
    assert page.status == 200 and page.body == b"<p>ok</p>"
    assert w.opened == [("https", "hospital.example", "203.0.113.7", 443)]  # one lookup, pinned IP, hostname for SNI
    assert w.sent[0][2]["User-Agent"] == V.USER_AGENT == "datathon-facility-check/0.1"


@pytest.mark.parametrize("target", ["ftp://hospital.example/file", "http://127.0.0.1/", "http://169.254.169.254/latest",
                                    "http://private.example/", "http://mixed.example/", "file:///etc/passwd",
                                    "http://[::1]/"])
def test_bad_redirect_is_refused_before_any_connection(monkeypatch, target):
    w = Wire(monkeypatch, {("hospital.example", "/"): (302, {"Location": target}, b"")})
    with pytest.raises(OSError):
        V.http_transport("https://hospital.example/", 2)
    assert [o[1] for o in w.opened] == ["hospital.example"]  # never connected to the redirect target


@pytest.mark.parametrize("start", ["ftp://hospital.example/", "http://private.example/", "http://mixed.example/",
                                   "http://10.1.2.3/", "http://nowhere.example/"])
def test_bad_start_url_never_connects(monkeypatch, start):
    w = Wire(monkeypatch, {})
    with pytest.raises(OSError):
        V.http_transport(start, 2)
    assert w.opened == []


def test_redirect_hops_are_each_pinned_and_capped(monkeypatch):
    w = Wire(monkeypatch, {("hospital.example", "/"): (301, {"Location": "https://cdn.example/home"}, b""),
                           ("cdn.example", "/home"): (200, {}, b"hi")})
    assert V.http_transport("http://hospital.example/", 2).url == "https://cdn.example/home"
    assert [(o[0], o[2]) for o in w.opened] == [("http", "203.0.113.7"), ("https", "198.51.100.4")]
    loop = Wire(monkeypatch, {("hospital.example", "/"): (302, {"Location": "/"}, b"")})
    with pytest.raises(OSError, match="too many redirects"):
        V.http_transport("http://hospital.example/", 2)
    assert len(loop.opened) == V.MAX_REDIRECTS + 1


@pytest.mark.parametrize("target", ["ftp://x.example/", "http://127.0.0.1/", "http://169.254.169.254/"])
def test_checker_reports_unreachable_for_bad_redirects(monkeypatch, target):
    w = Wire(monkeypatch, {("hospital.example", "/robots.txt"): (302, {"Location": target}, b""),
                           ("hospital.example", "/"): (302, {"Location": target}, b"")})
    t = [0.0]
    polite = V.Polite(V.http_transport, clock=lambda: t[0], sleep=lambda d: t.__setitem__(0, t[0] + d))
    ch = V.Checker({FID: {**SITE, "urls": ["https://hospital.example/"]}}, V.Lexicon.load(FIX / "lexicon.json"),
                   polite=polite)
    assert ch.check(FID, "dialysis")["status"] == "unreachable"
    assert {o[1] for o in w.opened} == {"hospital.example"}


def test_pinned_connections_dial_the_ip_and_keep_sni(monkeypatch):
    dialed, wrapped = [], []
    monkeypatch.setattr(V.socket, "create_connection", lambda addr, timeout: dialed.append(addr) or "raw-sock")

    class Ctx:
        def wrap_socket(self, sock, server_hostname):
            wrapped.append((sock, server_hostname))
            return "tls-sock"

    c = V._PinnedHTTPS("hospital.example", "203.0.113.7", 443, 2)
    c._context = Ctx()
    c.connect()
    h = V._PinnedHTTP("hospital.example", "203.0.113.7", 80, 2)
    h.connect()
    assert dialed == [("203.0.113.7", 443), ("203.0.113.7", 80)]
    assert wrapped == [("raw-sock", "hospital.example")] and c.sock == "tls-sock"
    assert c.host == "hospital.example"  # Host header comes from this, not the IP


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


def test_fetch_stops_at_its_budget_even_when_bytes_trickle(monkeypatch):
    # #85: a slow server kept a check running 41-56 s; the transport now enforces one total deadline
    t = [0.0]
    monkeypatch.setattr(V.time, "monotonic", lambda: t[0])

    class Slow(FakeResp):
        def read(self, n):
            t[0] += 3.0  # every chunk takes 3 s
            return b"x" * 10

    class Conn:
        def request(self, *a, **k):
            pass

        def getresponse(self):
            return Slow(200, {"Content-Type": "text/html"}, b"")

        def close(self):
            pass
    monkeypatch.setattr(V, "resolve_public", lambda host, port: "93.184.216.34")
    monkeypatch.setattr(V, "open_connection", lambda *a: Conn())
    with pytest.raises(TimeoutError):
        V.http_transport("https://slow.example/", 8.0)
    assert t[0] <= 12.0


def test_unknown_charset_reads_as_utf8():
    text, _, _ = V.page_text(V.Page(200, "https://a.example/", "text/html; charset=x-made-up",
                                            b"<p>Dialysis unit</p>"))
    assert "Dialysis unit" in text


def test_unreachable_is_not_cached_for_a_day():
    c = V.Checker.__new__(V.Checker)
    c._cache = {("f", "s"): {"status": "unreachable", "checked_at_ms": 0}}
    c.now = lambda: V.UNREACHABLE_TTL_S + 1
    c._run = lambda fid, sid: {"status": "found", "checked_at_ms": 1}
    assert c.check("f", "s")["status"] == "found"
