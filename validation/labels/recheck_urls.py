"""Fresh, polite re-fetch of the evidence URLs behind 30 gold labels (v2 TEST excluded to keep it sealed).

Sample: primary labels with >= 1 evidence URL from v1, v2 dev and the e2e pool; 12 confirmed, 6 contradicted,
12 no_info, drawn with random.Random(SEED). Per URL: robots.txt honoured, generic User-Agent, 20 s timeout,
2 retries with backoff on transient errors, 2 s between requests. Page text is saved under out/pages/<pair_id>/
(untrusted data, read only as text). Writes out/url_recheck.json. Judgments are made by hand afterwards in
judgments/url_judgments.csv (pair_id, agree yes|no|na, reason) after reading the saved text.
"""
from __future__ import annotations

import gzip
import html
import json
import random
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urlparse, urlsplit, urlunsplit

from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).resolve().parent))
import checks  # noqa: E402
from common import OUT, SEED, norm, pairs  # noqa: E402

UA = "Mozilla/5.0 (compatible; label-audit/1.0)"
QUOTA = {"confirmed": 12, "contradicted": 6, "no_info": 12}
SVC_RX = {
    "dialysis": r"dialys|nephrolog",
    "emergency_csection": r"caesar|cesar|c-section|lscs|obstetric|gyna?ecolog|maternity|labou?r room",
    "nicu": r"nicu|neonatal|newborn|neonat",
    "cardiac_surgery": r"cardiac surg|cardiothoracic|ctvs|bypass|cabg|heart surg|valve|open heart",
    "mri": r"\bmri\b|magnetic resonance",
    "burn_care": r"\bburns?\b|plastic surg",
    "trauma_emergency": r"trauma|emergency|casualty|accident",
}


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, a):
        self.skip += tag in ("script", "style", "noscript")

    def handle_endtag(self, tag):
        self.skip -= tag in ("script", "style", "noscript") and self.skip > 0

    def handle_data(self, d):
        if not self.skip:
            self.out.append(d)


def safe_url(u: str) -> str:
    s = urlsplit(u)
    return urlunsplit((s.scheme, s.netloc, quote(s.path, safe="/%:@&=+$,;~-._!'()*"), s.query, s.fragment))


_robots: dict = {}


def allowed(u: str) -> bool:
    p = urlparse(u)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(base + "/robots.txt", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=10) as r:
                rp.parse(r.read().decode("utf-8", "replace").splitlines())
        except Exception:
            rp.parse([])  # no robots.txt reachable: treat as allowed
        _robots[base] = rp
    return _robots[base].can_fetch(UA, u)


def fetch(u: str) -> dict:
    u = safe_url(u)
    try:
        if not allowed(u):
            return dict(url=u, status="robots_disallowed", text="")
    except Exception as e:
        return dict(url=u, status=f"robots_error:{type(e).__name__}", text="")
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "text/html,application/pdf,*/*"})
            with urllib.request.urlopen(req, timeout=20) as r:
                body, ctype, code = r.read(8_000_000), r.headers.get("Content-Type", ""), r.status
            if "pdf" in ctype or body[:4] == b"%PDF":
                with tempfile.TemporaryDirectory() as td:
                    f = Path(td) / "doc.pdf"
                    f.write_bytes(body)
                    txt = subprocess.run(["pdftotext", "-q", str(f), "-"], capture_output=True, text=True, timeout=60).stdout
            else:
                p = Text()
                p.feed(body.decode("utf-8", "replace"))
                txt = html.unescape(" ".join(p.out))
            return dict(url=u, status=f"http_{code}", text=re.sub(r"\s+", " ", txt).strip())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            return dict(url=u, status=f"http_{e.code}", text="")
        except Exception as e:  # DNS, TLS, timeout: retry, then report
            last = f"error:{type(e).__name__}:{str(e)[:80]}"
            time.sleep(3 * (attempt + 1))
    return dict(url=u, status=last, text="")


def sample():
    lab = checks._primary().merge(pairs()[["pair_id", "set", "split", "service", "name"]].rename(columns={"service": "svc"}), on="pair_id")
    pool = lab[(lab.n_urls > 0) & ~((lab.set == "v2") & (lab.split == "test"))].sort_values("pair_id")
    rng = random.Random(SEED)
    picks = []
    for v, k in QUOTA.items():
        ids = list(pool[pool.service == v].pair_id)
        picks += rng.sample(ids, min(k, len(ids)))
    return pool.set_index("pair_id").loc[picks].reset_index()


def main():
    s = sample()
    rows = []
    for r in s.assign(quote=s.quote.where(s.quote.map(lambda x: isinstance(x, str)), "")).itertuples():
        d = OUT / "pages" / r.pair_id
        d.mkdir(parents=True, exist_ok=True)
        pages = []
        for i, u in enumerate(r.evidence_urls[:3]):
            f = fetch(u)
            (d / f"{i}.txt.gz").write_bytes(gzip.compress(f["text"].encode()))
            t = f["text"]
            tl = norm(t)
            q = norm(r.quote or "")
            qscore = fuzz.partial_ratio(q, tl) if q and tl else None
            name_tok = [w for w in norm(r.name).split() if len(w) > 3]
            pages.append(dict(url=f["url"], status=f["status"], chars=len(t), quote_score=qscore,
                              svc_hits=len(re.findall(SVC_RX[r.svc], t, re.I)),
                              name_token_share=round(sum(w in tl for w in name_tok) / max(len(name_tok), 1), 2)))
            time.sleep(2)
        ok = [p for p in pages if p["chars"] > 200]
        qs = [p["quote_score"] for p in pages if p["quote_score"] is not None]
        rows.append(dict(pair_id=r.pair_id, set=r.set, svc=r.svc, name=r.name, label_service=r.service,
                         label_exists=r.exists, label_location=r.location, quote=r.quote or "", notes=r.notes,
                         any_page_ok=bool(ok), quote_checkable=bool((r.quote or "").strip()) and bool(ok),
                         quote_found=bool(qs) and max(qs) >= 90, best_quote_score=max(qs) if qs else None, pages=pages))
        print(r.pair_id, r.service, [(p["status"], p["chars"], p["svc_hits"], p["quote_score"]) for p in pages], flush=True)
    (OUT / "url_recheck.json").write_text(json.dumps(dict(seed=SEED, quota=QUOTA, ua=UA, rows=rows), indent=1))


if __name__ == "__main__":
    main()
