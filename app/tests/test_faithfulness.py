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

Payloads: three real plans from derived/v1 (#42; when app/facts/out is built) plus the stub fixtures.
Set FAITH_PLANS=<dir> to run against a directory of plan JSON files (for example
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

pw = pytest.importorskip("playwright.sync_api")

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
sys.path.insert(0, str(APP))
from stub_data import SERVICES, area_stub, recommend_stub  # noqa: E402

BAND_WORDS = {"likely": "LIKELY", "not_verified": "NOT VERIFIED: call to confirm", "unlikely": "UNLIKELY"}
STATIC_PHRASES = [r"\b108\b", r"\b102\b", r"\b112\b", r"\b24x7\b", r"\bin 10 listings\b"]
# Labels whose meaning must not drift: the gap split is a safety rule (spec Safety 19.1).
AREA_ROW_FIELDS = {
    "Access now": "area.summary.access_now",
    "If calls confirm the listings": "area.summary.access_if_confirmed",
    "Calls could close": "area.summary.calls_could_close",
    "No public evidence of care": "area.summary.no_public_evidence",
}
IST = timezone(timedelta(hours=5, minutes=30))  # the browser context runs in Asia/Kolkata


def verify_fixture(o: dict) -> dict:
    """A website-check result (#37) as /api/verify returns it; real results replace it with FAITH_PLANS runs."""
    t = int(time.time() * 1000)
    return {"facility_id": o["facility_id"], "service_id": "x", "status": "found",
            "status_text": "website lists",
            "quotes": [{"text": f"{o['name']} has a dialysis unit with 10 machines, open 24 hours.",
                        "url": "https://example.org/services/dialysis", "says": "yes"},
                       {"text": "Haemodialysis 6 days a week, 2 shifts.", "url": "https://example.org/",
                        "says": "yes"}],
            "pages_checked": ["https://example.org/"], "checked_at": "", "checked_at_ms": t, "cached": False}


def json_reply(obj: Any):
    body = json.dumps(obj)
    return lambda route: route.fulfill(status=200, content_type="application/json", body=body)


SITAMARHI = {"latitude": 26.5951, "longitude": 85.4808, "accuracy": 40}


REAL_QUERIES = {"gaya_dialysis": ("dialysis", 24.79, 85.0),
                "maharashtra_csection": ("emergency_csection", 19.88, 75.34),
                "nh19_trauma_mohania": ("trauma_emergency", 25.15, 83.68)}


# ---------- payloads ----------
def load_payloads() -> list[tuple[str, dict]]:
    src = os.environ.get("FAITH_PLANS")
    if src:
        files = sorted(Path(src).glob("*.json"))
        assert files, f"FAITH_PLANS={src} has no .json files"
        # A plan file may carry its area payload under "area_plan" (S11); otherwise the Area screen uses the stub.
        return [(f.stem, json.loads(f.read_text())) for f in files]
    out = []
    # Real rows (#42): the three release queries from derived/v1, with their real area plans.
    from facts.engine import Engine
    eng = Engine.load()
    if eng is not None:
        for name, (svc, lat, lon) in REAL_QUERIES.items():
            plan = eng.plan(svc, lat, lon, 40, "gps")
            plan["area_plan"] = eng.area(svc, lat, lon)
            out.append((f"real-{name}", plan))
    for svc in sorted(SERVICES):
        for name, (lat, lon) in {"sitamarhi": (26.6, 85.48), "pune": (18.52, 73.86)}.items():
            plan = recommend_stub(svc, lat, lon, 40, "gps")
            plan["area_plan"] = area_stub(svc, lat, lon)
            out.append((f"stub-{svc}-{name}", plan))
    return out


PAYLOADS = load_payloads()


def claim_texts() -> dict[str, str]:
    path = ROOT / "derived" / "v1" / "claims.parquet"
    if not path.is_file():
        return {}
    try:
        import pandas as pd
    except ImportError:  # claim-text check needs pandas + pyarrow (app/requirements-dev.txt); the rest still runs
        print("pandas missing: quotes not checked against derived/v1 claims")
        return {}
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
  const rows = [...main.querySelectorAll('tr')].map(tr => ({
    label: (tr.querySelector('th[scope=row]') || {}).textContent,
    paths: [...tr.querySelectorAll('td [data-f]')].map(e => e.dataset.f)}));
  return {items, rest: rest.textContent.replace(/\\s+/g, ' '), rows};
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
    elif kind == "clock":
        m = re.fullmatch(r"(\d{1,2}):(\d{2})\s*([AaPp][Mm])?", shown.strip())
        when = datetime.fromtimestamp(stored / 1000, IST)
        h = int(m[1]) % 12 + (12 if m[3] and m[3].lower() == "pm" else 0) if m and m[3] else int(m[1]) if m else -1
        ok = bool(m) and (h, int(m[2])) == (when.hour, when.minute)
    elif kind == "atleast":
        ok = within_precision(shown, 1 - math.prod(1 - o["p"] for o in stored))
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
    return None if ok else f"{path} ({kind}): shown {shown!r}, stored {repr(stored)[:120]}"


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
                              timezone_id="Asia/Kolkata", locale="en-IN",
                              permissions=["geolocation"], service_workers="block")
    page = ctx.new_page()
    page.route("**/api/plan", lambda r: r.fulfill(status=200, content_type="application/json",
                                                  body=json.dumps(payload)))
    page.add_init_script(
        "localStorage.setItem('rs.loc', JSON.stringify({lat: 26.5951, lon: 85.4808, accuracy_m: 40,"
        " source: 'gps', t: Date.now(), label: null}))")
    area = payload.get("area_plan") or area_stub(payload["query"]["service"], 26.6, 85.48)
    page.route("**/api/area", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(area)))
    full = {**payload, "area": area}  # data-f paths on the Area screen start with "area."
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
            # Live website check (#37): the dated line and its quotes must equal the /api/verify answer.
            ver = verify_fixture(o)
            page.route("**/api/verify", json_reply(ver))
            page.locator("#verify-btn").click()
            page.wait_for_selector("#verify-out blockquote")
            got = page.evaluate(COLLECT_JS)
            errs += check_screen(f"why/{o['rank']}/website", {**payload, "verify": ver}, got, report)
            vshown = {it["path"] for it in got["items"]}
            for need in ("verify.checked_at_ms", "verify.status_text", "verify.quotes.0.text", "verify.quotes.1.url"):
                if need not in vshown:
                    errs.append(f"why/{o['rank']}/website: {need} not shown")
            page.unroute("**/api/verify")
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
        # Compare (S10): asks "patient here?" with no default, then every option side by side.
        page.locator("[data-depth=compare]").click()
        page.locator("input[name=here][value=yes]").click()
        page.wait_for_selector(".compare-cards")
        got = page.evaluate(COLLECT_JS)
        errs += check_screen("compare", payload, got, report)
        errs += check_quotes("compare", payload, got["items"], claims, report)
        shown = {it["path"] for it in got["items"]}
        for i in range(len(payload["options"])):
            for f in ("p", "p_lo", "p_hi", "p_e", "p_l", "travel.km"):
                if f"options.{i}.{f}" not in shown:
                    errs.append(f"compare: options.{i}.{f} not shown")
        # Area (S11, S12): per-PIN plan, gap split and ten calls.
        page.locator("[data-depth=area]").click()
        page.wait_for_selector("#ten-calls")
        got = page.evaluate(COLLECT_JS)
        errs += check_screen("area", full, got, report)
        rows = {r["label"]: r["paths"] for r in got["rows"] if r["label"]}
        for label, path in AREA_ROW_FIELDS.items():
            if rows.get(label) != [path]:
                errs.append(f"area: row {label!r} shows {rows.get(label)}, expected [{path!r}]")
        shown = {it["path"] for it in got["items"]}
        for k in range(len(area["pins"])):
            if f"area.pins.{k}.pin" not in shown:
                errs.append(f"area: pin row {k} not shown")
        for k in range(len(area["ten_calls"])):
            if f"area.ten_calls.{k}.access_gain" not in shown:
                errs.append(f"area: call {k} not shown")
    finally:
        ctx.close()
    print(f"{name}: {report}")
    assert report["values_checked"] > 0
    assert not errs, "\n".join(errs[:40]) + (f"\n... {len(errs) - 40} more" if len(errs) > 40 else "")
