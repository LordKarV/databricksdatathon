"""Axe-core check, mobile screenshots and page weight for every skeleton state (issue #5).

Run from the repo root with a venv that has fastapi, uvicorn, playwright, axe-playwright-python:
    .venv-app/bin/python app/checks/a11y_check.py
Writes app/checks/a11y_results.json and app/checks/screens/<state>-<scheme>.png.
"""
from __future__ import annotations

import gzip
import json
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
PORT = 8765
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
    page.get_by_role("button", name="Use my location (GPS)").click()
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


def call_ahead(page: Page) -> None:
    plan_for("Accident")(page)
    page.get_by_role("link", name="Call ahead").first.click()
    page.get_by_role("button", name="Said yes").wait_for()


STATES: dict[str, Callable[[Page], None]] = {
    "start_first_visit": first_visit,
    "start_located": home_located,
    "start_danger_ticked": danger_ticked,
    "search": search,
    "change_location_error": change_error,
    "results_dialysis": plan_for("Dialysis"),
    "abstention_csection": plan_for("Emergency C-section"),
    "why_and_how": why,
    "call_ahead_trauma": call_ahead,
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
