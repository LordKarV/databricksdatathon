"""Fresh polite fetch of 20 crawl targets to re-check kb/crawl/sites.parquet site_status (seed 7171).

robots.txt is read first and obeyed for our user agent; at most 1 request per second per domain; one retry on a
transient error. Writes out/liveness.json. Classes are compared at group level (reachable, dead, not_facility,
blocked), since a page can legitimately change between the crawl and now.
"""
from __future__ import annotations

import json
import os
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
import urllib.robotparser

import pandas as pd

ROOT = "/Users/karthikvattem/projects/datathon"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
UA = "Mozilla/5.0 (compatible; data-audit/1.0)"
ALLOC = {"ok": 7, "ok_thin": 2, "dns_fail": 4, "http_4xx": 2, "hijacked_spam": 1, "parked_or_for_sale": 1, "timeout": 1, "suspended_or_expired": 1, "robots_disallow": 1}
GROUP = {"ok": "reachable", "ok_thin": "reachable", "dns_fail": "dead", "timeout": "dead", "connect_error": "dead", "tls_error": "dead",
         "http_5xx": "dead", "protocol_error": "dead", "http_4xx": "not_facility", "hijacked_spam": "not_facility", "parked_or_for_sale": "not_facility",
         "suspended_or_expired": "not_facility", "empty": "not_facility", "robots_disallow": "blocked", "robots_txt_forbidden": "blocked"}
PARKED = re.compile(r"domain (?:is|may be) for sale|buy this domain|parked|sedo|dan\.com|afternic|hugedomains|this domain has expired", re.I)
SPAM = re.compile(r"\b(?:slot|gacor|togel|judi|casino|betting|situs|maxwin)\b", re.I)
SUSP = re.compile(r"account (?:has been )?suspended|index of /|hosting has expired|website is suspended|defaultwebpage\.cgi", re.I)
GAP = 1.1


def get(url: str, timeout: float = 15) -> tuple[int, str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
        body = r.read(400_000).decode("utf-8", "replace")
        return r.status, r.geturl(), body


def star_disallows_all(txt: str) -> bool:
    star = False
    for line in txt.splitlines():
        k, _, v = line.split("#")[0].partition(":")
        k, v = k.strip().lower(), v.strip()
        if k == "user-agent":
            star = v == "*"
        elif k == "disallow" and star and v == "/":
            return True
    return False


def classify(site: str, home: str | None) -> tuple[str, str]:
    host = site.split("/")[0]
    try:
        socket.getaddrinfo(host, 443)
    except socket.gaierror:
        try:
            socket.getaddrinfo("www." + host, 443)
        except socket.gaierror as e:
            return "dns_fail", str(e)
    base = (home or f"https://{site}/").rstrip("/")
    root = re.match(r"https?://[^/]+", base).group(0)
    rp = urllib.robotparser.RobotFileParser()
    try:
        st, _, txt = get(root + "/robots.txt", timeout=10)
        rp.parse(txt.splitlines())
        if star_disallows_all(txt):  # robotparser reads only the first '*' group; a later 'Disallow: /' for '*' is honoured
            return "robots_disallow", "robots.txt: a User-agent * group disallows /"
    except urllib.error.HTTPError as e:
        rp.parse([] if e.code in (404, 410) else ["User-agent: *", "Disallow: /"])
        if e.code in (401, 403):
            return "robots_txt_forbidden", f"robots.txt {e.code}"
    except Exception:
        rp.parse([])  # unreachable robots.txt: the page fetch below decides
    if not rp.can_fetch(UA, base + "/"):
        return "robots_disallow", "robots.txt disallows /"
    time.sleep(GAP)
    for attempt in (1, 2):
        try:
            st, final, body = get(base + "/")
            text = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", body, flags=re.S | re.I)
            text = re.sub(r"\s+", " ", text)
            title = (re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I) or [None, ""])[1].strip()[:80]
            if PARKED.search(title + " " + text[:3000]):
                return "parked_or_for_sale", f"{final} title={title!r}"
            if len(SPAM.findall(title + " " + text[:5000])) >= 3:
                return "hijacked_spam", f"{final} title={title!r}"
            if SUSP.search(title + " " + text[:2000] + " " + body[:1000]):
                return "suspended_or_expired", f"{final} title={title!r}"
            return ("ok" if len(text) > 1500 else "ok_thin"), f"{st} {final} title={title!r} chars={len(text)}"
        except urllib.error.HTTPError as e:
            return ("http_4xx" if e.code < 500 else "http_5xx"), f"HTTP {e.code}"
        except (socket.timeout, TimeoutError) as e:
            err = ("timeout", str(e))
        except ssl.SSLError as e:
            err = ("tls_error", str(e)[:80])
        except urllib.error.URLError as e:
            r = str(e.reason)
            err = ("timeout" if "timed out" in r else "tls_error" if "SSL" in r or "CERTIFICATE" in r else "connect_error", r[:80])
        except Exception as e:  # report, never swallow
            err = ("connect_error", f"{type(e).__name__}: {e}"[:80])
        if attempt == 1:
            time.sleep(3)
    return err


def main() -> None:
    s = pd.read_parquet(f"{ROOT}/kb/crawl/sites.parquet")
    s = s[s.kind == "site"].drop_duplicates("site")
    pick = pd.concat([s[s.site_status == k].sample(n, random_state=7171) for k, n in ALLOC.items()])
    rows = []
    for r in pick.itertuples():
        home = r.site_home_final_url if isinstance(r.site_home_final_url, str) else None
        cls, detail = classify(r.site, home)
        if cls == "tls_error":  # the crawler fell back to plain http on a bad certificate (site_http_fallback); do the same
            time.sleep(GAP)
            cls, d2 = classify(r.site, f"http://{r.site}")
            detail = f"https fails ({detail[:40]}); http: {d2}"
        g_now, g_then = GROUP.get(cls, cls), GROUP.get(r.site_status, r.site_status)
        rows.append({"target_id": r.target_id, "site": r.site, "stored": r.site_status, "live_class": cls, "live_detail": detail,
                     "stored_group": g_then, "live_group": g_now, "agree": g_now == g_then})
        print(rows[-1], flush=True)
        time.sleep(GAP)
    os.makedirs(OUT, exist_ok=True)
    json.dump(rows, open(os.path.join(OUT, "liveness.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
