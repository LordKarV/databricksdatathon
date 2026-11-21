"""Step 3 (Goal 3): bounded source-page check. Does the record's claim text appear on the page it cites?

Sample: at most 400 source URLs, stratified by class/kind (official about pages, government pages,
research papers, aggregator about pages, list pages), seed 20261121, at most 3 URLs per registrable domain,
only records that carry at least one service sentence. Social, maps and docs-repo hosts are skipped (login
walls or no text).
Politeness: robots.txt is fetched first for every host and obeyed for User-Agent "datathon-source-check/0.1";
at most 1 request per second per registrable domain (robots fetch included); 15 s timeout; a 401/403/429 or
a login redirect stops that domain (no retries, no bypass). Indian government portals that time out from
this machine are recorded as 'unreachable', never as evidence against the claim.
Stored: per URL the fetch status, and per (URL, claim sentence) the match scores and a <= 160 character
snippet around the best match. Page bodies are never written to disk.
Matching (rapidfuzz on lower-cased alphanumeric text): exact = the normalised sentence is a substring;
fuzzy = partial_ratio >= 90; token = >= 70% of the sentence's content words (4+ letters) occur on the page.
'supported' = exact or fuzzy.

Writes derived/v1/source_page_checks.parquet (one row per URL x sentence; URLs with no usable page get one
row with claim_id null) and derived/v1/_work/s3_stats.json. Re-fetching is opt-in: run_all.sh calls this
only when FETCH=1 or the table is missing. Run with .venv-sources (needs pypdf).
"""
from __future__ import annotations

import html
import io
import json
import random
import re
import threading
import time
import urllib.error
import urllib.request
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import pandas as pd
from rapidfuzz import fuzz

from ss_common import OUT, ROOT, WORK

UA = "datathon-source-check/0.1"
TIMEOUT = 15
MIN_GAP_S = 1.05
MAX_BYTES = 4_000_000
MAX_PAGE_CHARS = 200_000
SEED = 20261121
PER_DOMAIN_CAP = 3
SENTENCES_PER_URL = 25
STRATA = [  # (name, filter, n)
    ("official_about", lambda d: d.source_class.isin(["official", "official_like"]) & (d.url_kind == "about"), 150),
    ("government", lambda d: d.source_class == "government", 90),
    ("research", lambda d: d.source_class == "research", 80),
    ("aggregator_about", lambda d: (d.source_class == "health_aggregator") & (d.url_kind == "about"), 40),
    ("list_page", lambda d: (d.url_kind == "list") & d.source_class.isin(["insurance_scheme", "business_dir", "health_aggregator", "other"]), 40),
]
SKIP_HOSTS = re.compile(r"(?:facebook|instagram|linkedin|twitter|x\.com|youtube|youtu\.be|google\.|goo\.gl|mappls|"
                        r"scribd|slideshare|justdial)")  # login walls / anti-bot pages: never fetched
LOGIN = re.compile(r"(/login|/signin|/sign-in|/sign_in|/accounts/login|captcha)", re.I)
STOP = {"with", "from", "that", "this", "have", "provides", "provide", "offers", "offer", "available", "services",
        "service", "facility", "facilities", "hospital", "patients", "care", "including", "also", "their", "which"}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (s or "").lower())).strip()


def html_text(raw: bytes, charset: str | None) -> str:
    t = raw.decode(charset or "utf-8", errors="replace")
    t = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", t)
    return html.unescape(re.sub(r"(?s)<[^>]+>", " ", t))


def pdf_text(raw: bytes) -> str:
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(raw))
    return " ".join((p.extract_text() or "") for p in r.pages[:40])


def sample_urls() -> pd.DataFrame:
    u = pd.read_parquet(WORK / "record_urls.parquet")
    c = pd.read_parquet(ROOT / "cleaning/claims/out/claims.parquet", columns=["unique_id", "services", "dup_in_record"])
    has_svc = set(c[(c.services != "") & ~c.dup_in_record].unique_id)
    u = u[u.unique_id.isin(has_svc) & ~u.host.str.contains(SKIP_HOSTS) & u.url.str.match(r"^https?://")]
    u = u.drop_duplicates(["unique_id", "url"])
    rng = random.Random(SEED)
    picked, per_dom = [], {}
    for name, f, n in STRATA:
        cand = u[f(u)].sample(frac=1.0, random_state=SEED).itertuples(index=False)
        k = 0
        for r in cand:
            if k >= n:
                break
            if per_dom.get(r.domain, 0) >= PER_DOMAIN_CAP or any(p["url"] == r.url for p in picked[-50:]):
                continue
            per_dom[r.domain] = per_dom.get(r.domain, 0) + 1
            picked.append({**r._asdict(), "stratum": name})
            k += 1
    rng.shuffle(picked)
    return pd.DataFrame(picked)


class DomainFetcher:
    """Sequential fetcher for one registrable domain: robots first, >= MIN_GAP_S between requests."""

    def __init__(self) -> None:
        self.last = 0.0
        self.robots: dict[str, urllib.robotparser.RobotFileParser | str] = {}
        self.stopped: str | None = None

    def _get(self, url: str) -> tuple[int, str, bytes, str]:
        wait = self.last + MIN_GAP_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self.last = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/pdf;q=0.9,*/*;q=0.5"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.status, resp.headers.get("Content-Type", ""), resp.read(MAX_BYTES), resp.geturl()
        except urllib.error.HTTPError as e:
            return e.code, "", b"", url

    def allowed(self, url: str) -> bool | str:
        p = urlparse(url)
        key = f"{p.scheme}://{p.netloc}"
        if key not in self.robots:
            try:
                code, _, body, _ = self._get(key + "/robots.txt")
                rp = urllib.robotparser.RobotFileParser()
                if code in (401, 403):
                    rp.disallow_all = True
                elif code >= 400:
                    rp.allow_all = True
                else:
                    rp.parse(body.decode("utf-8", errors="replace").splitlines())
                self.robots[key] = rp
            except Exception as e:  # DNS failure, refused, timeout: the host is unreachable from here
                self.robots[key] = f"unreachable:{type(e).__name__}"
        rp = self.robots[key]
        return rp if isinstance(rp, str) else rp.can_fetch(UA, url)

    def fetch(self, url: str) -> tuple[str, str]:
        """Return (status, page_text)."""
        if self.stopped:
            return f"skipped_after_{self.stopped}", ""
        ok = self.allowed(url)
        if isinstance(ok, str):
            return ok.split(":")[0], ""
        if not ok:
            return "robots_disallowed", ""
        try:
            code, ctype, body, final = self._get(url)
        except Exception:
            return "unreachable", ""
        if code in (401, 403, 429) or LOGIN.search(urlparse(final).path):
            self.stopped = "blocked" if code != 429 else "rate_limited"
            return f"blocked_http_{code}" if code != 200 else "login_redirect", ""
        if code >= 400:
            return f"http_{code}", ""
        m = re.search(r"charset=([\w-]+)", ctype)
        try:
            if "pdf" in ctype or body[:5] == b"%PDF-":
                return "ok_pdf", pdf_text(body)
            if "html" in ctype or "text" in ctype or not ctype:
                return "ok_html", html_text(body, m.group(1) if m else None)
        except Exception:
            return "parse_error", ""
        return "non_text", ""


def match(sentence: str, page_norm: str, page_tokens: set[str]) -> dict:
    s = norm(sentence)
    exact = len(s) >= 8 and s in page_norm
    al = fuzz.partial_ratio_alignment(s, page_norm) if s else None
    pr = float(al.score) if al else 0.0
    toks = [t for t in s.split() if len(t) >= 4 and t not in STOP]
    cov = (sum(t in page_tokens for t in toks) / len(toks)) if toks else 0.0
    snip = page_norm[max(0, al.dest_start - 20): al.dest_start + 140] if al and pr >= 60 else ""
    return dict(exact=exact, partial_ratio=round(pr, 1), token_coverage=round(cov, 3),
                supported=bool(exact or pr >= 90), token_supported=bool(cov >= 0.7), snippet=snip[:160])


def sentences_for(c: pd.DataFrame, uid: str, rng: random.Random) -> pd.DataFrame:
    g = c[c.unique_id == uid]
    svc = g[g.services != ""]
    other = g[g.services == ""]
    k = max(0, SENTENCES_PER_URL - len(svc))
    return pd.concat([svc.head(SENTENCES_PER_URL), other.sample(min(k, len(other)), random_state=rng.randint(0, 10**6))])


def run_domain(rows: list[dict], c: pd.DataFrame) -> list[dict]:
    f, out, rng = DomainFetcher(), [], random.Random(SEED)
    for r in rows:
        status, text = f.fetch(r["url"])
        base = dict(unique_id=r["unique_id"], url=r["url"], domain=r["domain"], source_class=r["source_class"],
                    url_kind=r["url_kind"], stratum=r["stratum"], fetch_status=status, page_chars=len(text))
        pn = norm(text)[:MAX_PAGE_CHARS]
        if len(pn) < 200:
            out.append({**base, "fetch_status": "ok_empty" if status.startswith("ok") else status,
                        "claim_id": None})
            continue
        toks = set(pn.split())
        for s in sentences_for(c, r["unique_id"], rng).itertuples(index=False):
            out.append({**base, "claim_id": s.claim_id, "field": s.field, "is_service_sentence": s.services != "",
                        "attribution": s.attribution, **match(s.text, pn, toks)})
    return out


def main() -> None:
    s = sample_urls()
    c = pd.read_parquet(ROOT / "cleaning/claims/out/claims.parquet",
                        columns=["claim_id", "unique_id", "field", "text", "services", "attribution", "dup_in_record"])
    c = c[c.unique_id.isin(set(s.unique_id)) & ~c.dup_in_record & (c.text.str.len() >= 12)]
    groups = [g.to_dict("records") for _, g in s.groupby("domain")]
    t0 = time.time()
    lock, done = threading.Lock(), [0]

    def work(rows: list[dict]) -> list[dict]:
        res = run_domain(rows, c)
        with lock:
            done[0] += len(rows)
            if done[0] % 50 < len(rows):
                print(f"{done[0]} urls, {time.time() - t0:.0f}s", flush=True)
        return res

    with ThreadPoolExecutor(max_workers=24) as ex:
        res = [x for part in ex.map(work, groups) for x in part]
    d = pd.DataFrame(res)
    d.to_parquet(OUT / "source_page_checks.parquet", index=False)
    per_url = d.drop_duplicates("url")
    st = {"urls_sampled": len(s), "by_stratum": s.stratum.value_counts().to_dict(),
          "fetch_status_by_stratum": per_url.groupby("stratum").fetch_status.value_counts().unstack(fill_value=0).to_dict("index"),
          "seconds": round(time.time() - t0)}
    (WORK / "s3_stats.json").write_text(json.dumps(st, indent=1, default=int))
    print(json.dumps(st, indent=1, default=int))


if __name__ == "__main__":
    assert norm("Provides 24/7 Dialysis!") == "provides 24 7 dialysis"
    m = match("Provides dialysis services", norm("we provide many things. provides dialysis services daily " * 10), set())
    assert m["exact"] and m["supported"]
    main()
