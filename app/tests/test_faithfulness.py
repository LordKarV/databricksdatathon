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
from facts.redact import redact_names  # noqa: E402, RUF100
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
                "sitamarhi_dialysis": ("dialysis", 26.6, 85.48),  # verified option far, nearer ones not verified
                "maharashtra_csection": ("emergency_csection", 19.88, 75.34),
                "nh19_trauma_mohania": ("trauma_emergency", 25.15, 83.68),
                # #86 demo QA: the audit's trauma probe, a quote naming a doctor, quotes with source warnings
                "pusa_trauma": ("trauma_emergency", 25.6, 85.95),
                "pune_cardiac_named_doctor": ("cardiac_surgery", 18.52, 73.86),
                "nagpur_mri_flagged_sources": ("mri", 21.15, 79.09)}


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
    from itinerary import attach
    eng = Engine.load()
    if eng is not None:
        for name, (svc, lat, lon) in REAL_QUERIES.items():
            plan = attach(eng.plan(svc, lat, lon, 40, "gps"), eng)  # with the planner's route (#47) when built
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
    shown = shown.strip().replace(",", "")  # digit grouping, e.g. 9,959 or 1,58,444
    m = re.fullmatch(r"[+-]?\d+(?:\.\d+)?", shown)
    assert m, f"not a number: {shown!r}"
    return float(shown)


def within_precision(shown: str, stored: float) -> bool:
    return abs(number(shown) - float(stored)) <= 0.5 * 10 ** -decimals(shown.strip().replace(",", "")) + 1e-9


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
    elif kind == "dur":  # minutes shown as 'N min', 'N h' or 'N day(s)', rounded to that unit
        m = re.fullmatch(r"(\d+) (min|h|days?)", shown.strip())
        unit = {"min": 1, "h": 60, "day": 1440, "days": 1440}[m[2]] if m else 0
        ok = bool(m) and abs(int(m[1]) * unit - stored) <= unit / 2
    elif kind == "delta":  # minutes against the first choice: 'N min closer', 'N min farther', 'about the same time'
        m = re.fullmatch(r"(\d+) min (closer|farther)", shown.strip())
        ok = (stored == 0 and shown.strip() == "about the same time") or (
            bool(m) and int(m[1]) == abs(stored) and (m[2] == "closer") == (stored < 0) and stored != 0)
    elif kind == "met":
        ok = shown == ("met" if stored is True else "not met" if stored is False else None)
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
            text, q = redact_names(claims[cid]), it["text"]  # a doctor's name is never shown (#86)
            ok = q == text or (q.endswith("...") and text.startswith(q[:-3]))
            report["quotes_matched_to_claims"] += ok
            if not ok:
                errs.append(f"{name}: quote {it['path']} differs from claim {cid}: {q!r} vs {text!r}")
        else:
            report["quotes_without_claim_row"] += 1
    return errs


# ---------- #86: why not the nearest, flagged citations, data gap vs care gap ----------
WHY_NOT_CODES = {"contradicted", "no_quote", "weak_quotes", "outside_window", "farther", "missing", "evidence_kind",
                 "location", "shared_phone", "not_confirmed", "weaker"}


def check_why_not(payload: dict, shown: set[str]) -> list[str]:
    """Every why-not row and the change line are shown, and each reason agrees with the fields it names."""
    errs, opts = [], payload["options"]
    first = opts[0]["travel"]["minutes"] if opts else None
    for k, w in enumerate(payload.get("why_not") or []):
        for f in ("name", "reason", "travel.km"):
            if f"why_not.{k}.{f}" not in shown:
                errs.append(f"why_not.{k}.{f} not shown")
        if "minutes_vs_first" not in w:
            continue  # an older export without the structured fields: the shown text is still checked verbatim
        if f"why_not.{k}.minutes_vs_first" not in shown:
            errs.append(f"why_not.{k}.minutes_vs_first not shown")
        if w["minutes_vs_first"] != w["travel"]["minutes"] - first:
            errs.append(f"why_not.{k}: minutes_vs_first {w['minutes_vs_first']} is not its travel minus option 1's")
        if w["facility_id"] == opts[0]["facility_id"]:
            errs.append(f"why_not.{k}: lists the first choice")
        if (w["option_rank"] is not None) != any(o["facility_id"] == w["facility_id"] for o in opts):
            errs.append(f"why_not.{k}: option_rank disagrees with the options list")
        for b in w["basis"]:
            code = b["code"]
            bad = (code not in WHY_NOT_CODES
                   or (code == "farther" and not (b["value"] == w["minutes_vs_first"] > 0))
                   or (code == "outside_window" and not (b["value"] == w["travel"]["minutes"] > b["window_min"]))
                   or (code == "contradicted" and w["band"] != "unlikely")
                   or (code == "not_confirmed" and not (w["band"] == "not_verified" and opts[0]["band"] == "likely")))
            if bad:
                errs.append(f"why_not.{k}: reason {code} does not match its fields {b} / band {w['band']}")
        if w["reason_code"] != w["basis"][0]["code"]:
            errs.append(f"why_not.{k}: reason_code is not the first basis")
    c = payload.get("what_would_change")
    if c:
        for f in ("name", "minutes_vs_first"):
            if f"what_would_change.{f}" not in shown:
                errs.append(f"what_would_change.{f} not shown")
        if c["kind"] == "confirm_nearer" and not c["minutes_vs_first"] < 0:
            errs.append("what_would_change: confirm_nearer is not nearer than option 1")
        if c["kind"] == "first_says_no" and (len(opts) < 2 or c["facility_id"] != opts[1]["facility_id"]):
            errs.append("what_would_change: first_says_no does not point at option 2")
    tw = payload.get("time_window")
    if tw and opts and tw["first_outside"] != (first > tw["window_min"]):
        errs.append("time_window.first_outside disagrees with option 1's travel time")
    if tw and tw["first_outside"] and "time_window.window_min" not in shown:
        errs.append("time_window: first choice is outside the window but the page does not say so")
    return errs


def check_quote_flags(o: dict, i: int, shown: set[str]) -> list[str]:
    """Every warning on a quote is shown next to it; weak quotes come after clean ones (demoted, not hidden)."""
    errs = []
    weak = [sum(f["weak"] for f in e.get("flags", [])) for e in o["evidence"]]
    if weak != sorted(weak):
        errs.append(f"evidence of option {i} is not ordered clean first: {weak}")
    for j, e in enumerate(o["evidence"]):
        for m, f in enumerate(e.get("flags", [])):
            P = f"options.{i}.evidence.{j}.flags.{m}"
            need = [P + ".text"] + ([P + ".place"] if f.get("place") else []) + ([P + ".km"] if f.get("km") else [])
            errs += [f"{x} not shown" for x in need if x not in shown]
    return errs


def check_gap(area: dict, shown: set[str]) -> list[str]:
    g = area.get("gap")
    if not g:
        return []
    errs = [f"area.gap.{k} not shown" for k in ("district_claiming", "district_confirmed", "covered",
                                                 "not_confirmed", "far", "no_claim", "pins_sampled", "pins_in_district")
            if f"area.gap.{k}" not in shown]
    split = g["covered"] + g["not_confirmed"] + g["far"] + g["no_claim"]
    if not split == g["pins_sampled"] == len(area["pins"]):
        errs.append(f"area.gap: the split does not add up to the sampled PINs {g}")
    for k in ("covered", "not_confirmed", "far", "no_claim"):
        if g[k] != sum(r.get("gap") == k for r in area["pins"]):
            errs.append(f"area.gap.{k} is not the count of PIN rows with that gap")
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
        got = page.evaluate(COLLECT_JS)
        errs += check_screen("plan", payload, got, report)
        opts = payload["options"]
        far = (opts and opts[0]["band"] != "likely" and any(o["band"] == "likely" for o in opts)
               and any(o["band"] != "likely" and o["travel"]["minutes"] < min(
                   x["travel"]["minutes"] for x in opts if x["band"] == "likely") for o in opts))
        errs += [f"plan: {e}" for e in check_why_not(payload, {it["path"] for it in got["items"]})]
        shown_note = "The nearest verified" in page.inner_text("#main")
        if bool(far) != shown_note:
            errs.append(f"plan: far-verified note shown={shown_note}, expected={bool(far)}")
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
            errs += [f"why/{o['rank']}: {e}" for e in check_quote_flags(o, i, shown)]
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
        errs += [f"area: {e}" for e in check_gap(area, shown)]
    finally:
        ctx.close()
    print(f"{name}: {report}")
    assert report["values_checked"] > 0
    assert not errs, "\n".join(errs[:40]) + (f"\n... {len(errs) - 40} more" if len(errs) > 40 else "")


# ---------- 'How this works' page (#45): every number comes from how.json, every source is a repo file ----------
HOW_JSON = APP / "howto" / "out" / "how.json"


@pytest.mark.skipif(not HOW_JSON.is_file(), reason="how.json not built (app/howto/build.py)")
def test_how_page_every_number_is_from_how_json(base_url, browser):
    how = json.loads(HOW_JSON.read_text())
    report = {"values_checked": 0}
    ctx = browser.new_context(viewport={"width": 360, "height": 780}, service_workers="block")
    page = ctx.new_page()
    try:
        page.goto(base_url + "/#/how")
        page.wait_for_selector("text=Page data built")
        got = page.evaluate(COLLECT_JS)
        links = page.eval_on_selector_all("#main a[href^='http']", "as => as.map(a => a.href)")
    finally:
        ctx.close()
    errs = check_screen("how", how, got, report)
    shown = {it["path"] for it in got["items"]}
    errs += [f"how: fact {k} not shown" for k, f in how["facts"].items() if f"facts.{k}.value" not in shown]
    for k, t in how["tables"].items():
        errs += [f"how: table {k} cell {i}.{j} not shown" for i, r in enumerate(t["rows"]) for j in range(len(r))
                 if f"tables.{k}.rows.{i}.{j}" not in shown]
    for href in links:
        rel = href.removeprefix(how["repo_url"])
        if rel == href or not (ROOT / rel).exists():
            errs.append(f"how: link {href} is not a file in this repo")
    print(f"how: {report}, {len(links)} source links")
    assert not errs, "\n".join(errs[:40])


# ---------- multi-stop route (#47): every itinerary field is shown, or listed here as deliberately not shown ----------
ROUTE_NOT_SHOWN = {"facility_id", "purpose", "type", "pathway", "urgency", "shared_listings"}


def route_leaves(obj: Any, path: str) -> list[str]:
    if isinstance(obj, dict):
        return [p for k, v in obj.items() if k not in ROUTE_NOT_SHOWN for p in route_leaves(v, f"{path}.{k}")]
    if isinstance(obj, list):
        return [p for i, v in enumerate(obj) for p in route_leaves(v, f"{path}.{i}")]
    return [] if obj is None else [path]


def route_expected(it: dict) -> set[str]:
    """Leaf paths the plan screen must show. A stage at the same hospital as the stop before it shares that stop's
    name, place, arrival time and phone, so those are shown once per hospital."""
    want = set()
    for k, r in enumerate(it["plans"]):
        P = f"itinerary.plans.{k}"
        for j, s in enumerate(r["stops"]):
            S, cont = f"{P}.stops.{j}", j > 0 and r["stops"][j - 1]["facility_id"] == s["facility_id"]
            for leaf in route_leaves(s, S):
                key = leaf[len(S) + 1:]
                if cont and key.split(".")[0] in ("name", "place", "eta_low", "eta_high", "phone"):
                    continue
                if key == "phone.e164" and s["phone"].get("display"):
                    continue  # the listing's own spelling of the number is shown, and dialled as e164
                if key == "place" and not s["place"]:
                    continue
                want.add(leaf)
        for key in ("rank", "type_word", "totals", "window_checks", "vs_direct"):
            want |= set(route_leaves(r.get(key), f"{P}.{key}"))
    want |= {"itinerary.pathway_name"} | ({"itinerary.abstain"} if it.get("abstain") else set())
    return want


ROUTED = [(n, p) for n, p in PAYLOADS if p.get("itinerary")]


@pytest.mark.skipif(not ROUTED, reason="no payload with a route (planner/out or app/facts/out not built)")
@pytest.mark.parametrize("name, payload", ROUTED, ids=[n for n, _ in ROUTED])
def test_every_route_field_is_shown(name, payload, base_url, browser):
    ctx = browser.new_context(viewport={"width": 360, "height": 780}, service_workers="block")
    page = ctx.new_page()
    page.route("**/api/plan", json_reply(payload))
    page.add_init_script(
        "localStorage.setItem('rs.loc', JSON.stringify({lat: 26.5951, lon: 85.4808, accuracy_m: 40,"
        " source: 'gps', t: Date.now(), label: null}))")
    try:
        page.goto(base_url + "/#/")
        page.locator(f"[data-svc={payload['query']['service']}]").first.click()
        page.wait_for_selector("text=Suggested route")
        got = page.evaluate(COLLECT_JS)
    finally:
        ctx.close()
    shown = {it["path"] for it in got["items"]}
    missing = sorted(route_expected(payload["itinerary"]) - shown)
    assert not missing, f"{name}: route fields not shown: {missing[:20]}"
    assert not check_screen("route", payload, got, {"values_checked": 0})
