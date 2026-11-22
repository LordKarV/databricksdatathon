"""Live 'check the facility website now' (issue #37): the at-use-time layer of verification.

Fetches a facility's official website (at most 4 pages: home plus links about the service, departments, contact or
emergency), politely (robots.txt, 1 request per second per domain, 8 s total budget, fixed User-Agent), and looks
for the service with the claims lexicon, skipping sentences that say it is not offered here and now. The result
never changes the model's band. Only quotes and URLs are kept (24 h cache); page bodies are dropped after matching.

Network, clock and sleep are injectable so tests replay recorded pages with no network.
"""
from __future__ import annotations

import codecs
import gzip
import http.client
import ipaddress
import json
import re
import socket
import ssl
import threading
import time
import urllib.robotparser
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

USER_AGENT = "datathon-facility-check/0.1"
MAX_PAGES = 4
BUDGET_S = 8.0
PER_DOMAIN_GAP_S = 1.0
MAX_BYTES = 1_500_000
CACHE_TTL_S = 24 * 3600
UNREACHABLE_TTL_S = 600  # a site that did not answer is asked again after 10 min, not a day (#85)
CHUNK = 65_536
CACHE_MAX = 2000
MAX_QUOTES = 2
OUT = Path(__file__).resolve().parent / "out"

STATUS_TEXT = {
    "found": "website lists",
    "not_mentioned": "website does not mention it",
    "unreachable": "website could not be reached",
    "wrong_site": "website does not look like this facility",
    "no_website": "no official website on record",
}
LINK_WORDS = re.compile(r"service|department|speciali|facilit|contact|emergenc|casualty|trauma|about", re.I)
GENERIC_NAME = re.compile(r"^(hospitals?|clinics?|centres?|centers?|health|care|healthcare|medical|multi|super|"
                          r"speciality|specialty|nursing|home|the|and|of|pvt|ltd|private|limited|institute|research|"
                          r"memorial|dr|sri|shri|new|city|general|charitable|trust|society|diagnostics?)$", re.I)


@dataclass
class Page:
    status: int
    url: str
    content_type: str
    body: bytes


Transport = Callable[[str, float], Page]


# ---------- network ----------
# Hardening (#40): only http(s), on the first URL and on every redirect; each hop resolves its host once, every
# address must be global, and the socket connects to that checked address (no second lookup, so no DNS-rebinding
# window). TLS keeps the hostname for SNI and certificate checks; the Host header stays the hostname.
SCHEMES = {"http": 80, "https": 443}
MAX_REDIRECTS = 5
REDIRECTS = {301, 302, 303, 307, 308}
_TLS = ssl.create_default_context()


def resolve_public(host: str, port: int) -> str:
    """The address to connect to, or OSError if the name does not resolve or any address is not global."""
    if not host:
        raise OSError("no host")
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addrs = [i[4][0] for i in infos]
    if not addrs or not all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addrs):
        raise OSError(f"non-public address for {host}")
    return addrs[0]


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host: str, ip: str, port: int, timeout: float) -> None:
        super().__init__(host, port, timeout=timeout)
        self.ip = ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self.ip, self.port), self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host: str, ip: str, port: int, timeout: float) -> None:
        super().__init__(host, port, timeout=timeout, context=_TLS)
        self.ip = ip

    def connect(self) -> None:
        raw = socket.create_connection((self.ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


def open_connection(scheme: str, host: str, ip: str, port: int, timeout: float) -> http.client.HTTPConnection:
    return (_PinnedHTTPS if scheme == "https" else _PinnedHTTP)(host, ip, port, timeout)


def http_transport(url: str, timeout: float) -> Page:
    """GET with pinned, checked addresses and manual http(s)-only redirects, all within `timeout` seconds in total.

    A socket timeout alone bounds each read, not the whole fetch: a server that trickles bytes or redirects kept a
    check running 41 to 56 s against its 8 s budget (#85). So every connect, redirect and chunk checks the deadline."""
    deadline = time.monotonic() + timeout

    def left() -> float:
        t = deadline - time.monotonic()
        if t <= 0:
            raise TimeoutError("fetch budget spent")
        return t
    for _ in range(MAX_REDIRECTS + 1):
        u = urlsplit(url)
        if u.scheme not in SCHEMES:
            raise OSError(f"scheme not allowed: {u.scheme!r}")
        port = u.port or SCHEMES[u.scheme]
        ip = resolve_public(u.hostname or "", port)
        conn = open_connection(u.scheme, u.hostname, ip, port, left())
        try:
            conn.request("GET", urlunsplit(("", "", u.path or "/", u.query, "")),
                         headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain;q=0.9"})
            r = conn.getresponse()
            loc = r.getheader("Location")
            if r.status in REDIRECTS and loc:
                url = urljoin(url, loc)
                continue
            body = bytearray()
            while len(body) < MAX_BYTES:
                if getattr(conn, "sock", None) is not None:
                    conn.sock.settimeout(left())
                chunk = r.read(min(CHUNK, MAX_BYTES - len(body)))
                if not chunk:
                    break
                body += chunk
                left()
            return Page(r.status, url, r.getheader("Content-Type") or "", bytes(body))
        finally:
            conn.close()
    raise OSError("too many redirects")


# ---------- HTML to text ----------
class _Text(HTMLParser):
    BLOCK = {"p", "div", "li", "br", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article",
             "header", "footer", "nav", "ul", "ol", "table", "title", "option", "dd", "dt"}
    SKIP = {"script", "style", "noscript", "template", "svg", "nav"}  # menus are link labels, not sentences

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.title = ""
        self._skip = 0
        self._a: list[str] | None = None
        self._href = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "title":
            self._in_title = True
        if tag == "a":
            self._href = dict(attrs).get("href") or ""
            self._a = []

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "title":
            self._in_title = False
        if tag == "a" and self._a is not None:
            self.links.append((self._href, " ".join(self._a)))
            self._a = None

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:  # used for the identity check only, never quoted
            self.title += data
            return
        self.parts.append(data)
        if self._a is not None:
            self._a.append(data.strip())


def page_text(p: Page) -> tuple[str, str, list[tuple[str, str]]]:
    charset = re.search(r"charset=([\w-]+)", p.content_type or "")
    enc = charset.group(1) if charset else "utf-8"
    try:
        codecs.lookup(enc)
    except LookupError:  # an unknown charset label returned 500 (#85); read it as UTF-8
        enc = "utf-8"
    raw = p.body.decode(enc, errors="replace")
    if "html" not in (p.content_type or "html").lower() and not re.search(r"<html|<body", raw[:2000], re.I):
        return raw, "", []
    t = _Text()
    t.feed(raw)
    return "".join(t.parts), t.title.strip(), t.links


def sentences(text: str) -> list[str]:
    out = []
    for line in text.split("\n"):
        line = re.sub(r"\s+", " ", line).strip()
        for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])", line):
            if 6 <= len(s) <= 400 and len(s.split()) >= 4:
                out.append(s)
    return out


# ---------- matching ----------
@dataclass
class Lexicon:
    core: dict[str, re.Pattern]
    exclude: dict[str, re.Pattern | None]
    nonoffer: dict[str, re.Pattern]

    @classmethod
    def load(cls, path: Path = OUT / "lexicon.json") -> Lexicon:
        d = json.loads(path.read_text())
        c = lambda p: re.compile(p, re.I) if p else None  # noqa: E731
        return cls({k: c(v["core"]) for k, v in d["services"].items()},
                   {k: c(v["exclude"]) for k, v in d["services"].items()},
                   {k: c(v) for k, v in d["nonoffer"].items()})

    def classify(self, service: str, s: str) -> str | None:
        """'yes' (offered), 'no' (mentioned but not offered here and now) or None (not about the service)."""
        if not self.core[service].search(s):
            return None
        ex = self.exclude.get(service)
        if ex is not None and ex.search(s):
            return None
        return "no" if any(p.search(s) for p in self.nonoffer.values()) else "yes"


def name_tokens(name: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", (name or "").lower()) if len(t) > 2 and not GENERIC_NAME.match(t)]


def looks_like(name: str, city: str | None, host: str, title: str, text: str) -> bool:
    """Does the page name this facility? Distinctive name words in its title or text (not the domain: a lapsed
    domain can be resold to someone else)."""
    toks = name_tokens(name)
    if not toks:
        return True  # nothing distinctive to check against
    hay = f"{title} {text[:200_000]}".lower()
    hits = sum(1 for t in toks if t in hay)
    return hits >= max(1, (len(toks) + 1) // 2)


# ---------- polite fetching ----------
class Polite:
    """Per-domain spacing (shared across requests), robots.txt per host, and a total time budget per check."""

    def __init__(self, transport: Transport = http_transport, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.transport, self.clock, self.sleep = transport, clock, sleep
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def _wait_turn(self, host: str, deadline: float) -> bool:
        with self._lock:
            now = self.clock()
            at = max(now, self._last.get(host, -1e9) + PER_DOMAIN_GAP_S)
            if at >= deadline:
                return False
            self._last[host] = at
        if at > now:
            self.sleep(at - now)
        return True

    def get(self, url: str, deadline: float) -> Page | None:
        host = urlsplit(url).hostname or ""
        if not self._wait_turn(host, deadline):
            return None
        try:
            left = deadline - self.clock()
            return self.transport(url, left) if left > 0 else None
        except (OSError, ValueError):
            return None

    def robots(self, base: str, deadline: float) -> urllib.robotparser.RobotFileParser | None:
        rp = urllib.robotparser.RobotFileParser()
        p = self.get(urljoin(base, "/robots.txt"), deadline)
        if p is None or p.status >= 500:
            return None  # unknown: treat the site as unreachable rather than guess
        if p.status in (401, 403):
            rp.disallow_all = True
        elif p.status >= 400:
            rp.allow_all = True
        else:
            rp.parse(p.body.decode("utf-8", errors="replace").splitlines())
        return rp


def _norm(url: str) -> str:
    s = urlsplit(url)
    return urlunsplit((s.scheme, s.netloc.lower(), s.path or "/", s.query, ""))


def _same_site(a: str, b: str) -> bool:
    strip = lambda h: (h or "").lower().removeprefix("www.")  # noqa: E731
    return strip(urlsplit(a).hostname) == strip(urlsplit(b).hostname)


# ---------- the check ----------
@dataclass
class Checker:
    sites: dict
    lexicon: Lexicon
    polite: Polite = field(default_factory=Polite)
    now: Callable[[], float] = time.time
    _cache: dict = field(default_factory=dict)

    @classmethod
    def from_out(cls, out: Path = OUT, **kw) -> Checker | None:
        if not (out / "sites.json.gz").is_file() or not (out / "lexicon.json").is_file():
            return None
        sites = json.loads(gzip.decompress((out / "sites.json.gz").read_bytes()))
        return cls(sites, Lexicon.load(out / "lexicon.json"), **kw)

    def check(self, facility_id: str, service_id: str) -> dict:
        key = (facility_id, service_id)
        hit = self._cache.get(key)
        ttl = UNREACHABLE_TTL_S if hit and hit["status"] == "unreachable" else CACHE_TTL_S
        if hit and self.now() - hit["checked_at_ms"] / 1000 < ttl:
            return {**hit, "cached": True}
        res = self._run(facility_id, service_id)
        if res["status"] != "no_website":
            if len(self._cache) >= CACHE_MAX:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = res
        return res

    def _result(self, fid: str, sid: str, status: str, quotes=(), pages=(), started: float | None = None) -> dict:
        t = self.now() if started is None else started
        return {"facility_id": fid, "service_id": sid, "status": status, "status_text": STATUS_TEXT[status],
                "quotes": list(quotes)[:MAX_QUOTES], "pages_checked": list(pages),
                "checked_at": datetime.fromtimestamp(t, UTC).isoformat(timespec="seconds"),
                "checked_at_ms": int(t * 1000), "cached": False,
                "note": "A website check is shown next to the plan; it never changes the band."}

    def _run(self, fid: str, sid: str) -> dict:
        site = self.sites.get(fid)
        started = self.now()
        if not site or not site.get("urls"):
            return self._result(fid, sid, "no_website", started=started)
        deadline = self.polite.clock() + BUDGET_S
        queue = [_norm(u) for u in site["urls"]]
        seen: set[str] = set()
        robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        fetched: list[str] = []
        yes: list[dict] = []
        no: list[dict] = []
        identity = False
        while queue and len(fetched) < MAX_PAGES and self.polite.clock() < deadline:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            host = urlsplit(url).netloc
            if host not in robots:
                robots[host] = self.polite.robots(url, deadline)
            rp = robots[host]
            if rp is None or not rp.can_fetch(USER_AGENT, url):
                continue
            page = self.polite.get(url, deadline)
            if page is None or page.status >= 400 or not page.body:
                continue
            fetched.append(page.url)
            text, title, links = page_text(page)
            del page  # bodies are never kept
            identity = identity or looks_like(site["name"], site.get("city"), host, title, text)
            for s in sentences(text):
                kind = self.lexicon.classify(sid, s)
                if kind and not any(q["text"] == s for q in yes + no):
                    (yes if kind == "yes" else no).append({"text": s, "url": fetched[-1], "says": kind})
            if len(fetched) == 1:  # follow links from the first page only: service words first, then the rest
                skip = ("#", "mailto:", "tel:", "javascript:")
                cand = [(_norm(urljoin(fetched[0], h)), t) for h, t in links if h and not h.startswith(skip)]
                cand = [(u, t) for u, t in cand if u.startswith("http") and _same_site(u, fetched[0]) and u not in seen]
                svc = [u for u, t in cand if self.lexicon.core[sid].search(f"{u} {t}")]
                dept = [u for u, t in cand if LINK_WORDS.search(f"{u} {t}") and u not in svc]
                queue = list(dict.fromkeys(svc + dept + queue))
        if not fetched:
            return self._result(fid, sid, "unreachable", started=started)
        if not identity:
            return self._result(fid, sid, "wrong_site", pages=fetched, started=started)
        if yes:
            yes.sort(key=lambda q: not q["text"].endswith((".", "!", "?")))  # full sentences before headings (stable)
            return self._result(fid, sid, "found", yes, fetched, started)
        return self._result(fid, sid, "not_mentioned", no, fetched, started)
