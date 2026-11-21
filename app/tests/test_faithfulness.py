"""Release test (spec 5.4, issue #30): every value shown equals the stored row it came from.

For each plan payload, the page is rendered in Chromium with /api/plan answered from the payload, and every
screen built from it is visited: results (or abstention), why / how / call-ahead per option, and the referral
slip in English and Hindi. The page marks each value it shows from the payload with data-f="<json path>" and
data-k="<kind>". This test then checks:

- each marked value equals its source field: text verbatim; numbers within the precision shown (so "24 km" for
  24.6 fails); totals equal the sum of their parts; band words follow the fixed mapping;
- no unmarked digit is on screen, apart from fixed template text (108, 102, 112, 24x7, "in 10 listings") and
  device-side text (location, clock times, call outcomes) marked data-device;
- every evidence quote and every contribution of an option is shown on its why page, and every quote carries
  its claim id; when the claim id exists in derived/v1/claims.parquet, the quote equals that claim's text.

Payloads: the stub by default. Set FAITH_PLANS=<dir> to run against a directory of plan JSON files (for example
the model export from #11): no test changes needed.
"""
from __future__ import annotations

import json
import math
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

import pytest

pw = pytest.importorskip("playwright.sync_api")

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
sys.path.insert(0, str(APP))
from stub_data import SERVICES, recommend_stub  # noqa: E402

BAND_WORDS = {"likely": "LIKELY", "not_verified": "NOT VERIFIED: call to confirm", "unlikely": "UNLIKELY"}
STATIC_PHRASES = [r"\b108\b", r"\b102\b", r"\b112\b", r"\b24x7\b", r"\bin 10 listings\b"]
SITAMARHI = {"latitude": 26.5951, "longitude": 85.4808, "accuracy": 40}


# ---------- payloads ----------
def load_payloads() -> list[tuple[str, dict]]:
    src = os.environ.get("FAITH_PLANS")
    if src:
        files = sorted(Path(src).glob("*.json"))
        assert files, f"FAITH_PLANS={src} has no .json files"
        return [(f.stem, json.loads(f.read_text())) for f in files]
    out = []
    for svc in sorted(SERVICES):
        for name, (lat, lon) in {"sitamarhi": (26.6, 85.48), "pune": (18.52, 73.86)}.items():
            out.append((f"stub-{svc}-{name}", recommend_stub(svc, lat, lon, 40, "gps")))
    return out


PAYLOADS = load_payloads()


def claim_texts() -> dict[str, str]:
    path = ROOT / "derived" / "v1" / "claims.parquet"
    if not path.is_file():
        return {}
    import pandas as pd
    c = pd.read_parquet(path, columns=["claim_id", "text"])
    return dict(zip(c.claim_id, c.text, strict=True))


# ---------- server and browser ----------
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def base_url():
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app:app", "--port", str(port), "--no-access-log"],
                            cwd=APP, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(url + "/api/ping", timeout=1).read()
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("server did not start")
        yield url
    finally:
        proc.terminate()


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture(scope="module")
def claims():
    return claim_texts()


COLLECT_JS = """() => {
  const main = document.querySelector('#main');
  const visible = el => { const c = el.cloneNode(true); c.querySelectorAll('[aria-hidden]').forEach(x => x.remove());
    return c.textContent.replace(/\\s+/g, ' ').trim(); };
  const items = [...main.querySelectorAll('[data-f]')].map(el => ({path: el.dataset.f, kind: el.dataset.k,
    text: visible(el)}));
  const rest = main.cloneNode(true);
  rest.querySelectorAll('[data-f], [data-device], [aria-hidden], script').forEach(x => x.remove());
  return {items, rest: rest.textContent.replace(/\\s+/g, ' ')};
}"""


# ---------- checks ----------
def resolve(obj: Any, path: str) -> Any:
    for part in path.split("."):
        obj = obj[int(part)] if isinstance(obj, list) else obj[part]
    return obj


def decimals(shown: str) -> int:
    m = re.search(r"\.(\d+)$", shown)
    return len(m.group(1)) if m else 0


def number(shown: str) -> float:
    m = re.fullmatch(r"[+-]?\d+(?:\.\d+)?", shown.strip())
    assert m, f"not a number: {shown!r}"
    return float(shown)


def within_precision(shown: str, stored: float) -> bool:
    return abs(number(shown) - float(stored)) <= 0.5 * 10 ** -decimals(shown.strip()) + 1e-9


def check_item(payload: dict, it: dict) -> str | None:
    """None if the shown value is faithful, else a message."""
    path, kind, shown = it["path"], it["kind"], it["text"]
    try:
        stored = resolve(payload, path)
    except (KeyError, IndexError, ValueError, TypeError):
        return f"{path}: path not in payload (shown {shown!r})"
    if kind == "text":
        ok = shown == re.sub(r"\s+", " ", str(stored)).strip()
    elif kind == "num":
        ok = isinstance(stored, (int, float)) and within_precision(shown, stored)
    elif kind == "sum":
        ok = int(number(shown)) == sum(c["points"] for c in stored)
    elif kind == "tenths":
        ok = int(number(shown)) == round(10 * stored["k_confirmed"] / stored["n"])
    elif kind == "band":
        ok = shown == BAND_WORDS.get(stored)
    elif kind == "method":
        ok = shown == ("road route" if stored == "osrm" else "rough")
    elif kind == "mapsurl":
        m = re.search(r"destination=(-?[\d.]+),(-?[\d.]+)", shown)
        ok = bool(m) and math.isclose(float(m[1]), stored["lat"]) and math.isclose(float(m[2]), stored["lon"])
    else:
        return f"{path}: unknown kind {kind!r}"
    return None if ok else f"{path} ({kind}): shown {shown!r}, stored {stored!r}"


def stray_digits(rest: str) -> list[str]:
    for pat in STATIC_PHRASES:
        rest = re.sub(pat, " ", rest)
    return re.findall(r"\S*\d\S*", rest)


def check_screen(name: str, payload: dict, got: dict, report: dict) -> list[str]:
    errs = [f"{name}: {e}" for it in got["items"] if (e := check_item(payload, it))]
    errs += [f"{name}: unmarked number {tok!r} on screen" for tok in stray_digits(got["rest"])]
    report["values_checked"] += len(got["items"])
    return errs


def check_quotes(name: str, payload: dict, items: list[dict], claims: dict[str, str], report: dict) -> list[str]:
    errs = []
    shown = {it["path"] for it in items}
    for it in items:
        if not it["path"].endswith(".quote"):
            continue
        base = it["path"][: -len(".quote")]
        if base + ".claim_id" not in shown:
            errs.append(f"{name}: quote {it['path']} shown without its claim id")
        cid = resolve(payload, base + ".claim_id")
        if cid in claims:
            text, q = claims[cid], it["text"]
            ok = q == text or (q.endswith("...") and text.startswith(q[:-3]))
            report["quotes_matched_to_claims"] += ok
            if not ok:
                errs.append(f"{name}: quote {it['path']} differs from claim {cid}: {q!r} vs {text!r}")
        else:
            report["quotes_without_claim_row"] += 1
    return errs


# ---------- the test ----------
@pytest.mark.parametrize("name, payload", PAYLOADS, ids=[n for n, _ in PAYLOADS])
def test_every_shown_value_equals_its_stored_row(name, payload, base_url, browser, claims):
    report = {"values_checked": 0, "quotes_matched_to_claims": 0, "quotes_without_claim_row": 0}
    ctx = browser.new_context(viewport={"width": 360, "height": 780}, geolocation=SITAMARHI,
                              permissions=["geolocation"], service_workers="block")
    page = ctx.new_page()
    page.route("**/api/plan", lambda r: r.fulfill(status=200, content_type="application/json",
                                                  body=json.dumps(payload)))
    page.add_init_script(
        "localStorage.setItem('rs.loc', JSON.stringify({lat: 26.5951, lon: 85.4808, accuracy_m: 40,"
        " source: 'gps', t: Date.now(), label: null}))")
    errs: list[str] = []
    try:
        page.goto(base_url + "/#/")
        page.locator(f"[data-svc={payload['query']['service']}]").first.click()
        page.wait_for_selector("article.card")
        errs += check_screen("plan", payload, page.evaluate(COLLECT_JS), report)
        for i, o in enumerate(payload["options"]):
            page.evaluate("h => { location.hash = h; }", f"#/why/{o['rank']}")
            page.wait_for_selector("#how")
            got = page.evaluate(COLLECT_JS)
            errs += check_screen(f"why/{o['rank']}", payload, got, report)
            errs += check_quotes(f"why/{o['rank']}", payload, got["items"], claims, report)
            shown = {it["path"] for it in got["items"]}
            for j in range(len(o["evidence"])):
                if f"options.{i}.evidence.{j}.quote" not in shown:
                    errs.append(f"why/{o['rank']}: evidence {j} not shown")
            for j in range(len(o["contributions"])):
                if f"options.{i}.contributions.{j}.points" not in shown:
                    errs.append(f"why/{o['rank']}: contribution {j} not shown")
            for lang in ("en", "hi"):
                page.evaluate("h => { location.hash = h; }", f"#/slip/{o['rank']}")
                page.wait_for_selector(".slip")
                if lang == "hi":
                    page.locator("[data-slip-lang=hi]").click()
                    page.wait_for_selector(".slip[lang=hi]")
                got = page.evaluate(COLLECT_JS)
                errs += check_screen(f"slip/{o['rank']}/{lang}", payload, got, report)
                errs += check_quotes(f"slip/{o['rank']}/{lang}", payload, got["items"], claims, report)
                if lang == "hi":
                    page.locator("[data-slip-lang=en]").click()  # reset for the next option
            page.evaluate("h => { location.hash = h; }", "#/plan")
            page.wait_for_selector("article.card")
    finally:
        ctx.close()
    print(f"{name}: {report}")
    assert report["values_checked"] > 0
    assert not errs, "\n".join(errs[:40]) + (f"\n... {len(errs) - 40} more" if len(errs) > 40 else "")
