"""Axe-core check, mobile screenshots and page weight for every skeleton state (issue #5).

Run from the repo root with a venv that has fastapi, uvicorn, playwright, axe-playwright-python:
    .venv-app/bin/python app/checks/a11y_check.py
Writes app/checks/a11y_results.json and app/checks/screens/<state>-<scheme>.png.
"""
from __future__ import annotations

import gzip
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

import axe_playwright_python
from playwright.sync_api import Page, sync_playwright

APP = Path(__file__).resolve().parents[1]
OUT = APP / "checks"
SCREENS = OUT / "screens"
PORT = int(os.environ.get("A11Y_PORT", "8765"))  # override when another check runs in parallel
BASE = f"http://127.0.0.1:{PORT}"
AXE_JS = (Path(axe_playwright_python.__file__).parent / "axe.min.js").read_text()
AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"]  # spec section 7
SITAMARHI = {"latitude": 26.5951, "longitude": 85.4808, "accuracy": 40}
VIEWPORT = {"width": 360, "height": 780}


def wait_up(timeout: float = 20) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with socket.create_connection(("127.0.0.1", PORT), 0.5):
                urllib.request.urlopen(BASE + "/api/ping", timeout=2).read()
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("server did not start")


def gz_size(path: str) -> tuple[int, int]:
    raw = urllib.request.urlopen(BASE + path).read()
    return len(raw), len(gzip.compress(raw, 9))


def axe(page: Page) -> list[dict]:
    page.add_script_tag(content=AXE_JS)
    res = page.evaluate("tags => axe.run(document, {runOnly: {type: 'tag', values: tags}})", AXE_TAGS)
    return [{"id": v["id"], "impact": v["impact"], "nodes": len(v["nodes"]),
             "targets": [n["target"] for n in v["nodes"]][:5]} for v in res["violations"]]


def go(page: Page, hash_: str) -> None:
    page.evaluate("h => { location.hash = h; }", hash_)
    page.wait_for_timeout(150)


def first_visit(page: Page) -> None:
    pass


def home_located(page: Page) -> None:
    gps = page.get_by_role("button", name="Use my location (GPS)")
    page.wait_for_function("document.querySelector('#gps') || document.body.innerText.includes('GPS 40 m')")
    if gps.count():
        gps.click()
    page.get_by_text("GPS 40 m").wait_for()


def danger_ticked(page: Page) -> None:
    home_located(page)
    page.get_by_text("Danger signs now?").click()
    page.get_by_label("Heavy bleeding").check()


def search(page: Page) -> None:
    home_located(page)
    page.get_by_label("Search a service").fill("kidney")


def change_error(page: Page) -> None:
    go(page, "#/change")
    page.get_by_label("PIN, village, town, district, or 'lat, lon'").fill("843317")
    page.get_by_role("button", name="Use this place").click()


def plan_for(service_label: str) -> Callable[[Page], None]:
    def run(page: Page) -> None:
        home_located(page)
        page.locator(".tile", has_text=service_label).click()
        page.locator("article.card").first.wait_for()
    return run


def why(page: Page) -> None:
    plan_for("Dialysis")(page)
    go(page, "#/why/1")
    page.get_by_text("How we decided").wait_for()


def website_check(page: Page) -> None:
    """Why page after "Check website now" (#37), with a recorded 'found' answer so quotes and links render."""
    import json
    import time
    why(page)
    body = json.dumps({"status": "found", "status_text": "website lists", "checked_at_ms": int(time.time() * 1000),
                       "quotes": [{"text": "Dialysis unit with 10 machines, open 24 hours.",
                                   "url": "https://example.org/dialysis", "says": "yes"}]})
    page.route("**/api/verify", lambda r: r.fulfill(status=200, content_type="application/json", body=body))
    page.get_by_role("button", name="Check website now").click()
    page.locator("#verify-out blockquote").wait_for()


def call_ahead(page: Page) -> None:
    plan_for("Accident")(page)
    page.get_by_role("link", name="Call ahead").first.click()
    page.get_by_role("button", name="Said yes").wait_for()


def sw_ready(ctx, page: Page, grant_gps: bool = True) -> None:
    """Load online until the service worker controls the page (shell and offline.js cached)."""
    if grant_gps:
        ctx.grant_permissions(["geolocation"], origin=BASE)
    page.goto(BASE + "/")
    page.wait_for_function("navigator.serviceWorker.ready.then(() => true)")
    page.reload()
    page.wait_for_function("!!navigator.serviceWorker.controller")


def online_plan_then_offline(ctx, page: Page) -> None:
    sw_ready(ctx, page)
    home_located(page)
    page.locator(".tile", has_text="Dialysis").click()
    page.locator("article.card").first.wait_for()
    page.wait_for_function("!!localStorage.getItem('rs.pack')", timeout=60000)  # pack saved in the background
    ctx.set_offline(True)
    go(page, "#/")


def offline_answer(ctx, page: Page) -> dict:
    online_plan_then_offline(ctx, page)
    page.locator(".tile", has_text="Dialysis").click()
    page.get_by_text("Call before you go").wait_for()
    n = page.locator("article.card").count()
    tel = page.locator("article.card a[href^='tel:+91']").count()
    return {"options": n, "tel_links": tel, "sms_links": page.locator("a[href^='sms:']").count()}


def offline_no_pack(ctx, page: Page) -> dict:
    sw_ready(ctx, page)
    home_located(page)
    ctx.set_offline(True)
    page.locator(".tile", has_text="Burns").click()
    page.get_by_text("No saved facility data on this phone yet").wait_for()
    return {}


def offline_old_fix(ctx, page: Page) -> dict:
    online_plan_then_offline(ctx, page)
    ctx.clear_permissions()  # no satellite fix arrives, so the old fix must be confirmed
    page.evaluate("() => { const l = JSON.parse(localStorage.getItem('rs.loc')); l.t -= 7 * 3600e3;"
                  " localStorage.setItem('rs.loc', JSON.stringify(l)); }")
    page.reload()
    page.locator(".tile", has_text="Dialysis").click()
    page.get_by_role("button", name="Patient is here").wait_for()
    return {}


def offline_pin_picker(ctx, page: Page) -> dict:
    online_plan_then_offline(ctx, page)
    go(page, "#/change")
    page.get_by_label("PIN, village, town, district, or 'lat, lon'").fill("843302")
    page.get_by_role("button", name="Use this place").click()
    page.get_by_text("PIN 843302").wait_for()
    return {"district_select": page.evaluate("location.hash")}


OFFLINE_STATES = {
    "offline_answer_dialysis": offline_answer,
    "offline_no_saved_pack": offline_no_pack,
    "offline_old_fix_confirm": offline_old_fix,
    "offline_pin_picker": offline_pin_picker,
}


def slip_for(lang: str) -> Callable[[Page], None]:
    def run(page: Page) -> None:
        plan_for("Emergency C-section")(page)
        go(page, "#/why/1")
        page.get_by_role("button", name="Said yes").click()
        page.get_by_role("link", name="Make referral slip").click()
        page.locator(".slip").wait_for()
        if lang == "hi":
            page.locator("[data-slip-lang=hi]").click()
            page.locator(".slip[lang=hi]").wait_for()
    return run


def compare(desk: bool) -> Callable[[Page], None]:
    def run(page: Page) -> None:
        if desk:
            page.set_viewport_size({"width": 1280, "height": 900})
        plan_for("Dialysis")(page)
        page.locator("[data-depth=compare]").click()
        page.get_by_role("radio", name="Yes").click()
        page.locator(".compare-cards").wait_for(state="attached")
    return run


def area(page: Page) -> None:
    plan_for("Accident")(page)
    page.locator("[data-depth=area]").click()
    page.locator("#ten-calls").wait_for()


def route_all_open(page: Page) -> None:
    """Multi-stop route (#47) with the other routes expanded."""
    plan_for("Accident")(page)
    page.get_by_text("Suggested route").first.wait_for()
    page.evaluate("document.querySelectorAll('#main details').forEach(d => d.open = true)")


def how_page(page: Page) -> None:
    """'How this works' (#45) with every expandable section open, so axe sees the tables too."""
    go(page, "#/how")
    page.get_by_text("Page data built").wait_for()
    page.evaluate("document.querySelectorAll('#main details').forEach(d => d.open = true)")


STATES: dict[str, Callable[[Page], None]] = {
    "start_first_visit": first_visit,
    "start_located": home_located,
    "start_danger_ticked": danger_ticked,
    "search": search,
    "change_location_error": change_error,
    "results_dialysis": plan_for("Dialysis"),
    "abstention_csection": plan_for("Emergency C-section"),
    "why_and_how": why,
    "website_check": website_check,
    "call_ahead_trauma": call_ahead,
    "slip_english": slip_for("en"),
    "slip_hindi": slip_for("hi"),
    "compare_dialysis": compare(desk=False),
    "compare_desk": compare(desk=True),
    "area_trauma": area,
    "route_trauma": route_all_open,
    "how_this_works": how_page,
}


def main() -> int:
    SCREENS.mkdir(parents=True, exist_ok=True)
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app:app", "--port", str(PORT), "--no-access-log"],
                              cwd=APP, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    results: dict = {"axe_tags": AXE_TAGS, "viewport": VIEWPORT, "states": {}}
    try:
        wait_up()
        weight = {p: gz_size(p) for p in ["/", "/app.css", "/app.js", "/manifest.webmanifest"]}
        results["critical_path"] = {
            "requests": len(weight), "files": {p: {"raw": r, "gzip": g} for p, (r, g) in weight.items()},
            "gzip_total": sum(g for _, g in weight.values()), "budget_gzip": 50_000, "budget_requests": 5}
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for scheme in ["light", "dark"]:
                for name, steps in STATES.items():
                    ctx = browser.new_context(viewport=VIEWPORT, geolocation=SITAMARHI, permissions=[],
                                              color_scheme=scheme, device_scale_factor=1, is_mobile=True)
                    page = ctx.new_page()
                    page.goto(BASE + "/")
                    page.wait_for_load_state("networkidle")
                    if name != "start_first_visit":
                        ctx.grant_permissions(["geolocation"], origin=BASE)
                    steps(page)
                    page.wait_for_timeout(200)
                    page.screenshot(path=str(SCREENS / f"{name}-{scheme}.png"), full_page=True)
                    overflow = page.evaluate("document.documentElement.scrollWidth > innerWidth")
                    results["states"][f"{name}-{scheme}"] = {"violations": axe(page), "horizontal_scroll": overflow}
                    ctx.close()
            # Offline: load once so the service worker caches the shell, then reload with the network off.
            ctx = browser.new_context(viewport=VIEWPORT, is_mobile=True, service_workers="allow")
            page = ctx.new_page()
            page.goto(BASE + "/")
            page.wait_for_function("navigator.serviceWorker.ready.then(() => true)")
            page.reload()
            page.wait_for_function("!!navigator.serviceWorker.controller")
            ctx.set_offline(True)
            page.reload()
            page.wait_for_selector("#offline:not([hidden])")
            page.screenshot(path=str(SCREENS / "offline_reload-light.png"), full_page=True)
            results["states"]["offline_reload-light"] = {"violations": axe(page), "shell_served_offline": True}
            ctx.close()
            for name, run in OFFLINE_STATES.items():
                ctx = browser.new_context(viewport=VIEWPORT, is_mobile=True, service_workers="allow",
                                          geolocation=SITAMARHI)
                page = ctx.new_page()
                facts = run(ctx, page)
                page.wait_for_timeout(200)
                page.screenshot(path=str(SCREENS / f"{name}-light.png"), full_page=True)
                overflow = page.evaluate("document.documentElement.scrollWidth > innerWidth")
                results["states"][f"{name}-light"] = {"violations": axe(page), "horizontal_scroll": overflow, **facts}
                ctx.close()
            browser.close()
    finally:
        server.terminate()
    (OUT / "a11y_results.json").write_text(json.dumps(results, indent=1) + "\n")
    bad = {k: v["violations"] for k, v in results["states"].items() if v["violations"]}
    scroll = [k for k, v in results["states"].items() if v.get("horizontal_scroll")]
    cp = results["critical_path"]
    print(f"states checked: {len(results['states'])}; with axe violations: {len(bad)}; horizontal scroll: {scroll}")
    print(f"critical path: {cp['requests']} requests, {cp['gzip_total']} B gzip (budget 50000 B, 5 requests)")
    for k, v in bad.items():
        print(k, json.dumps(v))
    return 1 if bad or scroll else 0


if __name__ == "__main__":
    raise SystemExit(main())
