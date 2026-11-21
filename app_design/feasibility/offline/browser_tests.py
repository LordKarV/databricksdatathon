"""Chromium tests: service worker behind a simulated cookie-auth proxy, and IndexedDB pack size.

1. First online visit goes through the cross-origin login redirect, gets the cookie, installs the SW
   and precaches the shell, picker and pack.
2. Offline reload renders the cached shell; an offline GPS lookup answers from IndexedDB.
3. Online with the cookie gone (session expired): the page can tell "expired" from "offline".
4. SW update check with no session fails without removing the installed SW.
5. A new SW registration with no session fails (script fetch is redirected).
6. Manifest request carries the cookie only with crossorigin=use-credentials.
7. IndexedDB: on-disk size of the Bihar pack, normalized (one record) vs denormalized (one record
   per PIN), from navigator.storage.estimate() and from the LevelDB folder on disk.
Run: ../../../.venv-offline/bin/python browser_tests.py   Writes out/browser_results.json.
"""
import json
import shutil
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from sim.server import APP, LOG, OUT, serve

GPS = {"latitude": 26.1209, "longitude": 85.3647}  # Muzaffarpur town, Bihar (public place)


def logged(path):
    return [json.loads(x) for x in LOG.read_text().splitlines() if json.loads(x)["path"] == path]


def dir_bytes(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def sw_tests(pw):
    res = {}
    ctx = pw.chromium.launch().new_context(geolocation=GPS, permissions=["geolocation"])
    page = ctx.new_page()
    page.goto(APP + "/")
    res["landed_after_login"] = page.url
    page.evaluate("navigator.serviceWorker.ready")
    page.reload()
    res["sw_controls_page"] = page.evaluate("!!navigator.serviceWorker.controller")
    res["cached"] = page.evaluate("caches.open('shell-v1').then(c => c.keys()).then(k => k.map(r => new URL(r.url).pathname))")
    res["precache_requests_had_cookie"] = all(r["cookie"] for p in ["/picker.json", "/pack_norm.json"] for r in logged(p))
    res["sw_script_fetch_header"] = [r["sw"] for r in logged("/sw.js")][:1]
    page.evaluate("""Promise.all([fetch('/pack_norm.json').then(r => r.json()), fetch('/picker.json').then(r => r.json())])
                     .then(([p, k]) => put([['pack', p], ['picker', k]]))""")
    res["session_online"] = page.evaluate("session()")

    ctx.set_offline(True)
    try:
        page.reload(timeout=15000)
        res["offline_reload_title"] = page.title()
        res["offline_banner"] = page.locator("#net").inner_text()
    except Exception as e:
        res["offline_reload_error"] = str(e).splitlines()[0][:200]
    res["session_offline"] = page.evaluate("session()")
    res["offline_gps_lookup"] = page.evaluate("""new Promise(ok => navigator.geolocation.getCurrentPosition(
        p => lookup(p.coords.latitude, p.coords.longitude, 'dialysis').then(ok), e => ok({error: e.message})))""")

    ctx.set_offline(False)
    page.goto(APP + "/?stopped=1")  # app stopped: proxy answers 503, SW should show the cached shell
    res["stopped_app_503_title"] = page.title()
    ctx.clear_cookies()
    res["session_expired_online"] = page.evaluate("session()")
    page.reload()
    res["expired_online_navigation_ends_at"] = page.url  # network-first: proxy re-login round trip
    ctx.clear_cookies()
    res["update_without_session"] = page.evaluate(
        "navigator.serviceWorker.getRegistration().then(r => r.update().then(() => 'ok', e => 'rejected: ' + e.name))")
    res["sw_still_active_after_failed_update"] = page.evaluate(
        "navigator.serviceWorker.getRegistration().then(r => !!(r && r.active))")
    res["new_register_without_session"] = page.evaluate(
        "navigator.serviceWorker.register('/sw.js?v=2').then(() => 'ok', e => 'rejected: ' + e.name + ': ' + e.message)")

    # manifest: ask Chromium to fetch it, once with and once without credentials
    for tag in ["cred", "nocred"]:
        page.goto(APP + "/" + ("#nocred" if tag == "nocred" else ""))
        page.reload()
        before = len(logged("/manifest.webmanifest"))
        cdp = ctx.new_cdp_session(page)
        m = cdp.send("Page.getAppManifest")
        hits = logged("/manifest.webmanifest")[before:]
        res[f"manifest_{tag}"] = {"cookie_sent": [h["cookie"] for h in hits],
                                  "parsed_name": json.loads(m.get("data") or "{}").get("name"),
                                  "errors": [x.get("message") for x in m.get("errors", [])][:2]}
    ctx.close()
    return res


IDB_JS = """async (layout) => {
  const before = (await navigator.storage.estimate()).usage;
  if (layout === 'norm') {
    const [p, k] = await Promise.all([fetch('/pack_norm.json').then(r => r.json()), fetch('/picker.json').then(r => r.json())]);
    await put([['pack', p], ['picker', k]]);
  } else {
    const d = await fetch('/pack_denorm.json').then(r => r.json());
    await put(Object.entries(d.packs));
  }
  await new Promise(r => setTimeout(r, 1500));
  const e = await navigator.storage.estimate();
  return {before, after: e.usage, details: e.usageDetails};  // usageDetails is Chromium-only
}"""


def idb_tests(pw):
    out = {}
    for layout in ["norm", "denorm"]:
        d = Path(tempfile.mkdtemp(prefix="idb_"))
        ctx = pw.chromium.launch_persistent_context(str(d))
        page = ctx.new_page()
        page.goto(APP + "/")
        est = page.evaluate(IDB_JS, layout)
        ctx.close()  # flush LevelDB
        idb = [p for p in (d / "Default" / "IndexedDB").glob("*localhost*")]
        out[layout] = {"estimate_usage_delta_bytes": est["after"] - est["before"], "usage_details": est["details"],
                       "leveldb_dir_bytes": sum(dir_bytes(p) for p in idb), "dirs": [p.name for p in idb]}
        shutil.rmtree(d, ignore_errors=True)
    return out


def main():
    serve()
    with sync_playwright() as pw:
        res = {"sw": sw_tests(pw), "indexeddb": idb_tests(pw)}
    (OUT / "browser_results.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(json.dumps(res, indent=1, ensure_ascii=False))
    s = res["sw"]
    assert s["sw_controls_page"] and s["precache_requests_had_cookie"]
    assert s["offline_reload_title"] == "Referral finder" and len(s["offline_gps_lookup"]["rows"]) == 3
    assert s["stopped_app_503_title"] == "Referral finder"
    assert s["session_offline"] == "offline" and s["session_expired_online"] == "expired"
    print("ASSERTIONS PASSED")


if __name__ == "__main__":
    main()
