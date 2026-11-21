"""Polite, resumable crawl of facility websites (targets from targets.py).

Per target: robots.txt (cached per host, honoured, Crawl-delay up to 15 s), the seed page(s), then
up to 6 pages in total, chosen from same-site links by keyword group (extract.pick_links). Every
request, including each redirect hop and robots.txt, waits on a per-registrable-domain gate (at
least 1 s apart). 15 s per request, HTML only, 2 MB cap. Text is extracted in worker processes
and stored redacted as gzip JSON under data/crawl/pages/.

Checkpoint: data/crawl/checkpoint.jsonl, one line per finished target (site liveness + page
rows); finished targets are skipped on resume. A target cut off by --max-seconds is redone.
--index rebuilds kb/crawl/pages.parquet and kb/crawl/sites.parquet from the checkpoint.

Usage: crawl.py --max-seconds 500 [--workers 24] [--retry transient,redirect_other_org] | --index | --probe URL
"""
import argparse
import asyncio
import gzip
import hashlib
import json
import os
import re
import socket
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from protego import Protego

import httpx
import pandas as pd
from rapidfuzz import fuzz

ROOT = "/Users/karthikvattem/projects/datathon"
sys.path.insert(0, f"{ROOT}/kb/crawl")
sys.path.insert(0, f"{ROOT}/audit/provenance")
from domains import classify, name_key  # noqa: E402
from extract import PARKING_HOSTS, extract, pick_links, redact, spam_verdict  # noqa: E402
from targets import reg_domain  # noqa: E402

UA = "datathon-facility-check/0.1"
KB = f"{ROOT}/kb/crawl"
RAW = f"{ROOT}/data/crawl"
PAGES = f"{RAW}/pages"
CKPT = f"{RAW}/checkpoint.jsonl"
RUNS = f"{RAW}/runs.jsonl"
TIMEOUT_S = 15
MAX_BYTES = 2 * 1024 * 1024
MAX_PAGES = 6
TARGET_CAP_S = 150  # one target never holds a worker longer than this
MIN_DELAY_S = 1.0
MAX_CRAWL_DELAY_S = 30  # honoured up to this; TARGET_CAP_S then bounds how many pages fit
GRACE_S = 45  # stop taking new targets this long before --max-seconds
REDIRECTS = (301, 302, 303, 307, 308)


class Gate:
    """At most one request per registrable domain per delay (default 1 s)."""

    def __init__(self) -> None:
        self.locks: dict[str, asyncio.Lock] = {}
        self.last: dict[str, float] = {}
        self.delay: dict[str, float] = {}

    async def wait(self, host: str) -> None:
        d = reg_domain(host)
        lock = self.locks.setdefault(d, asyncio.Lock())
        async with lock:
            gap = self.last.get(d, 0) + self.delay.get(d, MIN_DELAY_S) - time.monotonic()
            if gap > 0:
                await asyncio.sleep(gap)
            self.last[d] = time.monotonic()


class Fetch:
    def __init__(self, status: int | None = None, final_url: str = "", body: bytes = b"", ctype: str = "",
                 last_modified: str | None = None, error: str | None = None, truncated: bool = False) -> None:
        self.status, self.final_url, self.body, self.ctype = status, final_url, body, ctype
        self.last_modified, self.error, self.truncated = last_modified, error, truncated


def err_kind(e: BaseException) -> str:
    m = str(e).lower()
    if isinstance(e, (httpx.TimeoutException, TimeoutError, asyncio.TimeoutError)):
        return "timeout"
    if "ssl" in m or "certificate" in m or "tls" in m:
        return "tls_error"
    if any(k in m for k in ("nodename nor servname", "name or service not known", "getaddrinfo", "no address associated")):
        return "dns_fail"
    if isinstance(e, httpx.ConnectError):
        return "connect_error"
    if isinstance(e, (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError)):
        return "protocol_error"
    if isinstance(e, httpx.InvalidURL) or isinstance(e, httpx.UnsupportedProtocol):
        return "bad_url"
    return f"other_error:{type(e).__name__}"


class Crawler:
    def __init__(self, workers: int) -> None:
        self.gate = Gate()
        self.robots: dict[str, Protego | str] = {}
        self.robot_locks: dict[str, asyncio.Lock] = {}
        limits = httpx.Limits(max_connections=workers + 8, max_keepalive_connections=workers)
        kw = dict(headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
                           "Accept-Language": "en-IN,en;q=0.9"}, timeout=TIMEOUT_S, limits=limits,
                  follow_redirects=False)
        self.client = httpx.AsyncClient(**kw)
        # fallback for sites with expired or self-signed certificates: public pages, no login involved
        self.lax = httpx.AsyncClient(verify=False, **kw)
        self.pool = ProcessPoolExecutor(max_workers=4)
        self.dns: dict[str, bool] = {}

    async def close(self) -> None:
        await self.client.aclose()
        await self.lax.aclose()
        self.pool.shutdown(cancel_futures=True)

    async def resolves(self, host: str) -> bool:
        if host not in self.dns:
            try:
                await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM), 10)
                self.dns[host] = True
            except (OSError, asyncio.TimeoutError):
                self.dns[host] = False
        return self.dns[host]

    async def get(self, url: str, check_robots: bool = True, lax: bool = False, max_bytes: int = MAX_BYTES) -> Fetch:
        """GET with manual redirects (each hop gated and robots-checked)."""
        for _ in range(6):
            host = urlparse(url).hostname or ""
            if check_robots:
                ok = await self.allowed(url)
                if ok is not True:
                    return Fetch(final_url=url, error=ok)
            await self.gate.wait(host)
            try:
                async with asyncio.timeout(TIMEOUT_S):
                    async with (self.lax if lax else self.client).stream("GET", url) as r:
                        if r.status_code in REDIRECTS and r.headers.get("location"):
                            url = urljoin(url, r.headers["location"]).split("#")[0]
                            continue
                        ctype = r.headers.get("content-type", "").lower()
                        lm = r.headers.get("last-modified")
                        if check_robots and r.status_code < 400 and ctype and "html" not in ctype:
                            return Fetch(r.status_code, url, ctype=ctype, last_modified=lm, error="non_html")
                        buf, trunc = bytearray(), False
                        async for chunk in r.aiter_bytes():
                            buf += chunk
                            if len(buf) >= max_bytes:
                                trunc = True
                                break
                        return Fetch(r.status_code, url, bytes(buf[:max_bytes]), ctype, lm, None, trunc)
            except Exception as e:  # noqa: BLE001 - every failure becomes a recorded error kind
                return Fetch(final_url=url, error=err_kind(e))
        return Fetch(final_url=url, error="too_many_redirects")

    async def allowed(self, url: str) -> bool | str:
        """True, or an error string: robots_disallow / crawl_delay_too_long / a network error kind."""
        p = urlparse(url)
        key = f"{p.scheme}://{p.hostname}"
        lock = self.robot_locks.setdefault(key, asyncio.Lock())
        async with lock:
            if key not in self.robots:
                self.robots[key] = await self.fetch_robots(key)
        rp = self.robots[key]
        if isinstance(rp, str):
            return rp
        if not rp.can_fetch(url, UA):
            return "robots_disallow"
        cd = rp.crawl_delay(UA)
        if cd:
            if float(cd) > MAX_CRAWL_DELAY_S:
                return "crawl_delay_too_long"
            d = reg_domain(p.hostname or "")
            self.gate.delay[d] = max(self.gate.delay.get(d, MIN_DELAY_S), float(cd))
        return True

    async def fetch_robots(self, base: str) -> Protego | str:
        """Parsed robots.txt, or a reason string that blocks the host. RFC 9309: 4xx = no rules;
        5xx or unreachable = disallow all. 401/403 is treated as disallow too (conservative)."""
        host = urlparse(base).hostname or ""
        if not await self.resolves(host):
            return "dns_fail"
        f = await self.get(base + "/robots.txt", check_robots=False, max_bytes=512 * 1024)
        if f.error == "tls_error":
            f = await self.get(base + "/robots.txt", check_robots=False, lax=True, max_bytes=512 * 1024)
        if f.error:
            return f.error
        if f.status in (401, 403):
            return "robots_txt_forbidden"
        if f.status >= 500:
            return "robots_txt_5xx"
        if f.status >= 400 or "html" in f.ctype:
            return Protego.parse("")  # no robots.txt (404, or a soft-404 HTML page): allow all
        return Protego.parse(f.body.decode("utf-8", "replace"))

    async def page(self, url: str, lax: bool) -> tuple[Fetch, dict | None]:
        f = await self.get(url, lax=lax)
        if f.error or not f.body:
            return f, None
        m = re.search(r"charset=([\w-]+)", f.ctype) or re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", f.body[:4096])
        enc = (m.group(1).decode() if isinstance(m.group(1), bytes) else m.group(1)) if m else "utf-8"
        try:
            html = f.body.decode(enc, "replace")
        except LookupError:
            html = f.body.decode("utf-8", "replace")
        ex = await asyncio.get_running_loop().run_in_executor(self.pool, extract, html, f.final_url)
        return f, ex


def store(target_id: str, f: Fetch, ex: dict, fetched_at: str) -> dict:
    text = ex["text"]
    h = hashlib.sha1(f.final_url.encode()).hexdigest()[:20]
    path = f"{PAGES}/{h}.json.gz"
    rec = {"target_id": target_id, "url_final": f.final_url, "fetched_at": fetched_at, "title": ex["title"],
           "text": text, "chrome_text": ex["chrome_text"]}
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(rec, fh, ensure_ascii=False)
    return {"text_hash": hashlib.sha1(text.encode()).hexdigest(), "text_len": len(text),
            "chrome_len": len(ex["chrome_text"]), "lang": ex["lang"], "title": ex["title"],
            "fallback_text": ex["fallback_text"], "path": os.path.relpath(path, ROOT)}


def names_in_page(names: list[str], ex: dict) -> bool:
    """A redirect landing page that names the facility is the same organisation under a new domain."""
    page = re.sub(r"[^a-z0-9]", "", f"{ex['title']} {ex['text'][:5000]} {ex['chrome_text'][:2000]}".lower())
    return any(len(k) >= 5 and fuzz.partial_ratio(k, page) >= 90 for k in map(name_key, names))


def same_org(final_host: str, start_host: str, names: list[str]) -> bool:
    lab = re.sub(r"[^a-z0-9]", "", reg_domain(final_host).split(".")[0])
    start = re.sub(r"[^a-z0-9]", "", reg_domain(start_host).split(".")[0])
    if fuzz.partial_ratio(start, lab) >= 85:
        return True
    return any(len(k) >= 4 and fuzz.partial_ratio(k, lab) >= 85 for k in map(name_key, names))


async def crawl_target(c: Crawler, t: dict, names: list[str], out: dict) -> None:
    """Fill out['site'] and out['pages'] in place so a cut-off target still reports what it did."""
    seeds = list(t["seeds"])
    site, start_host = t["site"], urlparse(seeds[0]).hostname
    s = out["site"]
    if not await c.resolves(start_host):
        alt = start_host[4:] if start_host.startswith("www.") else "www." + start_host
        if not await c.resolves(alt):
            s["status"] = "dns_fail"
            return
        seeds = [u.replace(f"//{start_host}", f"//{alt}", 1) for u in seeds]
    queue = [(u, "home" if i == 0 and t["kind"] != "branch" else "seed") for i, u in enumerate(seeds)]
    done, lax, first = set(), False, True
    while queue and len(out["pages"]) < MAX_PAGES:
        url, role = queue.pop(0)
        if url in done:
            continue
        done.add(url)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        f, ex = await c.page(url, lax)
        if first and f.error == "tls_error":
            f, ex = await c.page(url, lax=True)
            lax = s["tls_invalid"] = f.error is None
        if first and f.error in ("connect_error", "tls_error", "timeout", "protocol_error") and url.startswith("https://"):
            f2, ex2 = await c.page("http://" + url[8:], lax)
            if f2.error is None or f2.status:
                f, ex, s["http_fallback"] = f2, ex2, True
        row = {"target_id": t["target_id"], "unique_ids": t["unique_ids"], "url": url, "final_url": f.final_url,
               "role": role, "http_status": f.status, "fetched_at": now, "last_modified": f.last_modified,
               "content_type": f.ctype, "truncated": f.truncated, "error": f.error}
        if ex is not None and f.status and f.status < 400:
            row.update(store(t["target_id"], f, ex, now))
        elif f.status and f.status >= 400 and not f.error:
            row["error"] = f"http_{f.status}"
        out["pages"].append(row)
        if first:
            s["home_final_url"] = f.final_url
            fh = (urlparse(f.final_url).hostname or "").lower()
            if f.error or not ex or (f.status or 0) >= 400:
                err = row["error"] or "empty"
                if f.status and f.status >= 400:
                    err = "http_4xx" if f.status < 500 else "http_5xx"
                if queue and err not in ("dns_fail", "robots_disallow", "crawl_delay_too_long", "robots_txt_forbidden", "robots_txt_5xx"):
                    s["first_page_error"] = err
                    continue  # first page failed; the record's own deep URLs may still work
                s["status"] = s.get("first_page_error") or err
                return
            first = False
            if ex["spam_injected"]:
                s["spam_injected"] = True
            if ex["status_hint"] == "hijacked_spam":
                s["status"] = "hijacked_spam"
                return
            if PARKING_HOSTS.search(fh) or ex["status_hint"] in ("parked_or_for_sale", "suspended_or_expired"):
                s["status"] = "parked_or_for_sale" if PARKING_HOSTS.search(fh) else ex["status_hint"]
                return
            if reg_domain(fh) != reg_domain(start_host):
                cls = classify(re.sub(r"^www\.", "", fh), set(), names[0] if names else "")
                if cls in ("social", "health_aggregator", "business_dir", "maps_geo", "news", "insurance_scheme"):
                    s["status"] = "redirect_third_party"
                    s["redirect_class"] = cls
                    return
                if not (same_org(fh, start_host, names) or names_in_page(names, ex)):
                    s["status"] = "redirect_unverified"  # new domain, landing page does not name the facility
                    return
                s["redirect_same_org"] = True
                site = re.sub(r"^(www\d?|m)\.", "", fh)
            s["status"] = "ok"
            if ex["status_hint"] == "under_construction":
                s["under_construction"] = True
            if len(ex["text"]) < 50:
                s["status"] = "ok_thin"
            slug = None
            if t["kind"] == "branch":
                seg = [x for x in urlparse(url).path.split("/") if x]
                slug = seg[-1].lower() if seg and len(seg[-1]) >= 5 else None
            room = MAX_PAGES - len(out["pages"]) - len(queue)
            for u, g in pick_links(ex["links"], site, max(room, 0), slug):
                if u not in done:
                    queue.append((u, f"link:{g}"))
    if s.get("status") is None:
        s["status"] = "no_page"


TRANSIENT = {"timeout", "connect_error", "http_5xx", "robots_txt_5xx", "protocol_error", "target_timeout"}


def load_done(retry: set[str] | None = None) -> set[str]:
    """Finished target ids; targets whose last status is in retry count as not done."""
    if not os.path.exists(CKPT):
        return set()
    last = {}
    with open(CKPT) as fh:
        for x in fh:
            if x.strip():
                r = json.loads(x)
                last[r["target_id"]] = r.get("site_status")
    retry = retry or set()
    return {k for k, v in last.items() if not (v in retry or ("crawler_error" in retry and str(v).startswith("crawler_error")))}


async def run(max_seconds: float, workers: int, retry: set[str] | None = None) -> None:
    t0 = time.monotonic()
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tg = pd.read_parquet(f"{KB}/targets.parquet")
    names = pd.read_parquet(f"{ROOT}/cleaning/geo_identity/facility_location.parquet",
                            columns=["unique_id", "name"]).drop_duplicates("unique_id").set_index("unique_id").name
    done = load_done(retry)
    todo = [r for r in tg.to_dict("records") if r["target_id"] not in done]
    print(f"targets {len(tg)}, done {len(done)}, todo {len(todo)}", flush=True)
    c = Crawler(workers)
    q: asyncio.Queue = asyncio.Queue()
    for r in todo:
        q.put_nowait(r)
    ck = open(CKPT, "a")
    n_done = {"n": 0}

    async def worker() -> None:
        while not q.empty() and time.monotonic() - t0 < max_seconds - GRACE_S:
            t = q.get_nowait()
            t["seeds"], t["unique_ids"] = list(t["seeds"]), list(t["unique_ids"])
            out = {"site": {"status": None}, "pages": []}
            try:
                await asyncio.wait_for(crawl_target(c, t, [names.get(u, "") for u in t["unique_ids"]], out),
                                       TARGET_CAP_S)
            except asyncio.TimeoutError:
                out["site"]["status"] = out["site"]["status"] or "target_timeout"
                out["site"]["capped"] = True
            except asyncio.CancelledError:
                return  # cut off by the run deadline: not checkpointed, redone next run
            except Exception as e:  # noqa: BLE001 - one bad page must not kill a worker
                out["site"]["status"] = out["site"]["status"] or f"crawler_error:{type(e).__name__}"
                out["site"]["crawler_error"] = str(e)[:200]
            rec = {"target_id": t["target_id"], "site": t["site"], "domain": t["domain"], "kind": t["kind"],
                   "shared": bool(t["shared"]), "unique_ids": t["unique_ids"], **{f"site_{k}": v for k, v in out["site"].items()},
                   "pages": out["pages"], "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            ck.write(json.dumps(rec, default=str) + "\n")
            ck.flush()
            n_done["n"] += 1
            if n_done["n"] % 100 == 0:
                print(f"{n_done['n']} targets in {time.monotonic() - t0:.0f}s", flush=True)

    tasks = [asyncio.create_task(worker()) for _ in range(workers)]
    _, pending = await asyncio.wait(tasks, timeout=max(max_seconds - (time.monotonic() - t0), 1))
    for p in pending:
        p.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    ck.close()
    await c.close()
    secs = time.monotonic() - t0
    with open(RUNS, "a") as fh:
        fh.write(json.dumps({"started": started, "seconds": round(secs, 1), "targets_done": n_done["n"],
                             "cut_off": len(pending), "workers": workers, "retry": sorted(retry or [])}) + "\n")
    print(f"run done: {n_done['n']} targets in {secs:.0f}s, {len(pending)} workers cut off, "
          f"{q.qsize()} targets never started", flush=True)


def reredact() -> None:
    """Re-apply extract.redact to every stored page and patch text_hash/text_len in the checkpoint
    (used once after the phone regex missed numbers before a sentence-ending period)."""
    rows = [json.loads(x) for x in open(CKPT) if x.strip()]
    fixed = {}
    for r in rows:
        for p in r["pages"]:
            if not p.get("path"):
                continue
            if p["path"] not in fixed:
                f = f"{ROOT}/{p['path']}"
                d = json.load(gzip.open(f, "rt"))
                d = d | {k: redact(d[k]) for k in ("title", "text", "chrome_text")}
                with gzip.open(f, "wt", encoding="utf-8") as fh:
                    json.dump(d, fh, ensure_ascii=False)
                fixed[p["path"]] = (hashlib.sha1(d["text"].encode()).hexdigest(), len(d["text"]), len(d["chrome_text"]), d["title"])
            p["text_hash"], p["text_len"], p["chrome_len"], p["title"] = fixed[p["path"]]
    with open(CKPT + ".tmp", "w") as fh:
        fh.writelines(json.dumps(r, default=str) + "\n" for r in rows)
    os.replace(CKPT + ".tmp", CKPT)
    print(f"re-redacted {len(fixed)} files")


def index() -> None:
    """Checkpoint -> kb/crawl/pages.parquet (one row per page attempt) and sites.parquet (one per target).
    A target can appear twice only if a run was killed between write and flush; last line wins."""
    recs = {}
    with open(CKPT) as fh:
        for x in fh:
            if x.strip():
                r = json.loads(x)
                recs[r["target_id"]] = r
    for r in recs.values():
        first = next((p for p in r["pages"] if p.get("path")), None)
        if first and str(r.get("site_status", "")).startswith(("ok", "redirect")):
            d = json.load(gzip.open(f"{ROOT}/{first['path']}", "rt"))
            v = spam_verdict(d["title"], d["text"])
            if PARKING_HOSTS.search(urlparse(first["final_url"]).hostname or ""):
                r["site_status"], r["site_relabelled"] = "parked_or_for_sale", True
            elif v == "hijacked_spam":
                r["site_status"], r["site_relabelled"] = "hijacked_spam", True
            elif v == "spam_injected" and r.get("site_status") == "redirect_unverified":
                r["site_status"], r["site_relabelled"] = "hijacked_spam", True  # spam on a foreign landing page
            elif v == "spam_injected":
                r["site_spam_injected"] = True
    pages = pd.DataFrame([p for r in recs.values() for p in r["pages"]])
    sites = pd.DataFrame([{k: v for k, v in r.items() if k != "pages"} | {
        "n_pages_stored": sum(1 for p in r["pages"] if p.get("path")),
        "n_page_attempts": len(r["pages"])} for r in recs.values()])
    pages.to_parquet(f"{KB}/pages.parquet", index=False)
    sites.to_parquet(f"{KB}/sites.parquet", index=False)
    print(f"indexed {len(sites)} targets, {len(pages)} page attempts, {int(pages.path.notna().sum())} stored")


async def probe(url: str) -> None:
    c = Crawler(1)
    t = time.monotonic()
    host = urlparse(url).hostname or ""
    res = {"url": url, "dns": await c.resolves(host)}
    f = await c.get(url)
    res |= {"status": f.status, "error": f.error, "final_url": f.final_url, "bytes": len(f.body),
            "seconds": round(time.monotonic() - t, 1), "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    await c.close()
    print(json.dumps(res))
    with open(f"{KB}/gov_probe.jsonl", "a") as fh:
        fh.write(json.dumps(res) + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-seconds", type=float, default=500)
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--index", action="store_true")
    ap.add_argument("--reredact", action="store_true")
    ap.add_argument("--probe")
    ap.add_argument("--retry", default="", help="comma list of site statuses to redo; 'transient' = timeouts, 5xx...")
    a = ap.parse_args()
    os.makedirs(PAGES, exist_ok=True)
    if a.reredact:
        reredact()
        index()
    elif a.index:
        index()
    elif a.probe:
        asyncio.run(probe(a.probe))
    else:
        assert a.max_seconds <= 540, "keep each chunk under 9 minutes"
        retry = {x for x in a.retry.split(",") if x}
        retry = (retry - {"transient"}) | (TRANSIENT | {"crawler_error"} if "transient" in retry else set())
        asyncio.run(run(a.max_seconds, a.workers, retry))
        index()
