"""Offline behaviour: GPS-first page with a service worker vs Streamlit, in Chromium.

Checks: (1) first online visit installs the SW and caches page + pack, (2) offline reload
still renders, (3) GPS offline ranks the cached snapshot, (4) GPS denied offline falls back
to PIN code, (5) GPS denied with a saved location reuses it, (6) Streamlit offline reload.
Run: ../../../.venv-a11y/bin/python offline_test.py   Writes outputs/offline_results.json.
"""
import json
import subprocess
import time

from playwright.sync_api import sync_playwright

from measure import AXE_JS, AXE_TAGS, BENGALURU, HERE, OUT, TARGETS, wait_port

URL = "http://localhost:8000/pwa"
STATUS = "#out"


def online_install(ctx):
    page = ctx.new_page()
    page.goto(URL)
    page.evaluate("navigator.serviceWorker.ready")
    page.reload()  # second load is controlled by the SW
    controlled = page.evaluate("!!navigator.serviceWorker.controller")
    cached = page.evaluate("caches.open('care-v1').then(c => c.keys()).then(k => k.map(r => r.url))")
    return page, {"sw_controls_page": controlled, "cached": cached}


def offline_reload(ctx, page):
    ctx.set_offline(True)
    t0 = time.time()
    try:
        page.reload(timeout=15000)
        page.get_by_role("heading", name="Find care near you").wait_for(timeout=5000)
        return {"renders_offline": True, "reload_s": round(time.time() - t0, 2),
                "offline_banner_visible": page.locator("#net").is_visible()}
    except Exception as e:
        return {"renders_offline": False, "error": str(e).splitlines()[0][:160]}


def status_after(page, action, timeout=15000):
    action()
    page.wait_for_function(f"document.querySelector('{STATUS}').textContent.startsWith('Offline')", timeout=timeout)
    return {"status": page.locator(STATUS).inner_text(), "results": page.locator("#list li").all_inner_texts()}


def gps_offline(browser):
    ctx = browser.new_context(geolocation=BENGALURU, permissions=["geolocation"])
    page, res = online_install(ctx)
    res |= offline_reload(ctx, page)
    res["gps"] = status_after(page, lambda: page.get_by_role("button", name="Use my location").click())
    res["call_link"] = page.locator("a.call").first.get_attribute("href")
    page.add_script_tag(path=str(AXE_JS))
    axe = page.evaluate("t => axe.run(document, {runOnly: {type: 'tag', values: t}})", AXE_TAGS)
    res["axe_violations_offline_results"] = [f"{v['id']} ({v['impact']} x{len(v['nodes'])})" for v in axe["violations"]]
    ctx.close()
    return res


def denied_offline(browser):
    ctx = browser.new_context()  # no geolocation permission: getCurrentPosition errors
    page, res = online_install(ctx)
    res |= offline_reload(ctx, page)
    page.get_by_role("button", name="Use my location").click()
    page.wait_for_function(f"document.querySelector('{STATUS}').textContent.includes('PIN')", timeout=15000)
    res["denied_message"] = page.locator(STATUS).inner_text()
    res["focus_moved_to_pin"] = page.evaluate("document.activeElement.id") == "pin"
    page.keyboard.type("560001")
    res["pin"] = status_after(page, lambda: page.get_by_role("button", name="Search by PIN code").click())
    # now a saved location exists: a later GPS failure reuses it instead of asking again
    page.locator("#list").evaluate("e => e.replaceChildren()")
    res["denied_with_saved"] = status_after(page, lambda: page.get_by_role("button", name="Use my location").click())
    ctx.close()
    return res


def streamlit_offline(browser):
    t = TARGETS["streamlit_bare"]
    proc = subprocess.Popen(t["cmd"], cwd=HERE / "apps", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_port(t["port"], t["url"])
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(t["url"])
        page.get_by_role("heading", name="Find care near you").wait_for(timeout=30000)
        ctx.set_offline(True)
        try:
            page.reload(timeout=15000)
            ok = page.get_by_role("heading", name="Find care near you").is_visible()
            return {"renders_offline": ok}
        except Exception as e:
            return {"renders_offline": False, "error": str(e).splitlines()[0][:160]}
    finally:
        proc.terminate()
        proc.wait(10)


def main():
    t = TARGETS["fastapi_probe"]
    proc = subprocess.Popen(t["cmd"], cwd=HERE / "apps", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert wait_port(t["port"], URL), "fastapi did not start"
        with sync_playwright() as p:
            b = p.chromium.launch()
            res = {"fastapi_gps_offline": gps_offline(b), "fastapi_gps_denied_offline": denied_offline(b)}
            proc.terminate()
            proc.wait(10)
            res["streamlit_offline"] = streamlit_offline(b)
            b.close()
    finally:
        proc.terminate()
    (OUT / "offline_results.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(json.dumps(res, indent=1, ensure_ascii=False))
    g, d = res["fastapi_gps_offline"], res["fastapi_gps_denied_offline"]
    assert g["renders_offline"] and len(g["gps"]["results"]) == 3 and "GPS" in g["gps"]["status"]
    assert d["focus_moved_to_pin"] and len(d["pin"]["results"]) == 3
    assert "last saved location" in d["denied_with_saved"]["status"]
    print("ALL ASSERTIONS PASSED")


if __name__ == "__main__":
    main()
