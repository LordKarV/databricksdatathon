"""Measure page weight, load time under throttling, axe-core violations, target sizes,
and geolocation/camera feasibility for hello-world pages of four frameworks.

Run: ../../../.venv-a11y/bin/python measure.py [name ...]
Writes outputs/results.json and outputs/screens/<name>.png.
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
APPS = HERE / "apps"
OUT = HERE / "outputs"
PY = str(HERE.parents[2] / ".venv-a11y" / "bin" / "python")
AXE_JS = next((HERE.parents[2] / ".venv-a11y" / "lib").glob("python3.11/site-packages/axe_playwright_python/axe.min.js"))
AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"]
BENGALURU = {"latitude": 12.9716, "longitude": 77.5946}

# Throttling profiles. "slow4g" is Lighthouse's default mobile profile (150 ms RTT,
# 1.6 Mbps down, 750 kbps up, 4x CPU). "2g" is the old Chrome DevTools "Regular 2G"
# preset (300 ms, 250 kbps down, 50 kbps up), with the same 4x CPU slowdown as a
# stand-in for a low-end Android Go phone.
PROFILES = {
    "none": None,
    "slow4g": {"latency": 150, "down_kbps": 1600, "up_kbps": 750, "cpu": 4},
    "2g": {"latency": 300, "down_kbps": 250, "up_kbps": 50, "cpu": 4},
}


def st(f):
    return [PY, "-m", "streamlit", "run", str(APPS / f), "--server.port", "8501", "--server.headless", "true",
            # match Databricks Apps (it sets gatherUsageStats=false) and a non-localhost viewer
            "--browser.gatherUsageStats", "false", "--client.toolbarMode", "viewer"]


TARGETS = {
    "streamlit_bare": dict(cmd=st("st_bare.py"), port=8501, url="http://localhost:8501/"),
    "streamlit_probe": dict(cmd=st("st_probe.py"), port=8501, url="http://localhost:8501/", geo="iframe"),
    "dash_bare": dict(cmd=[PY, str(APPS / "dash_bare.py")], port=8050, url="http://localhost:8050/"),
    "dash_probe": dict(cmd=[PY, str(APPS / "dash_probe.py")], port=8050, url="http://localhost:8050/", geo="page"),
    "dash_probe_gzip": dict(cmd=[PY, str(APPS / "dash_probe.py")], port=8050, url="http://localhost:8050/",
                            geo="page", env={"DASH_COMPRESS": "1"}),
    "gradio_bare": dict(cmd=[PY, str(APPS / "gr_bare.py")], port=7860, url="http://localhost:7860/"),
    "gradio_probe": dict(cmd=[PY, str(APPS / "gr_probe.py")], port=7860, url="http://localhost:7860/", geo="page"),
    "fastapi_bare": dict(cmd=[PY, "-m", "uvicorn", "fastapi_app:app", "--port", "8000", "--app-dir", str(APPS)],
                         port=8000, url="http://localhost:8000/bare"),
    "fastapi_probe": dict(cmd=[PY, "-m", "uvicorn", "fastapi_app:app", "--port", "8000", "--app-dir", str(APPS)],
                          port=8000, url="http://localhost:8000/", geo="page"),
}

FIND_GOT_JS = """() => {
  const vals = [document.body.innerText, ...[...document.querySelectorAll('input,textarea')].map(e => e.value)];
  const hit = vals.find(v => v && v.includes('Got location'));
  return hit ? hit.slice(hit.indexOf('Got location'), hit.indexOf('Got location') + 40).split('\\n')[0] : false;
}"""

TARGET_SIZE_JS = """() => {
  const sel = 'button,a[href],input:not([type=hidden]),select,textarea,[role=button],label[for]';
  return [...document.querySelectorAll(sel)].map(e => {
    const r = e.getBoundingClientRect();
    return {tag: e.tagName.toLowerCase(), type: e.type || null,
            name: (e.getAttribute('aria-label') || e.innerText || e.title || '').trim().slice(0, 40),
            w: Math.round(r.width), h: Math.round(r.height)};
  }).filter(x => x.w > 0 && x.h > 0);
}"""


def wait_port(port, url, timeout=90):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with socket.create_connection(("localhost", port), 1):
                urllib.request.urlopen(url, timeout=5).read()
                return True
        except OSError:
            time.sleep(0.5)
    return False


class Net:
    """Collects CDP network events: request count, bytes on the wire, decoded bytes, hosts."""

    def __init__(self, cdp):
        self.reqs, self.encoded, self.decoded, self.ws, self.hosts, self.cached = 0, 0, 0, 0, set(), 0
        cdp.on("Network.requestWillBeSent", self._req)
        cdp.on("Network.loadingFinished", lambda e: setattr(self, "encoded", self.encoded + e["encodedDataLength"]))
        cdp.on("Network.dataReceived", lambda e: setattr(self, "decoded", self.decoded + e["dataLength"]))
        cdp.on("Network.requestServedFromCache", lambda e: setattr(self, "cached", self.cached + 1))
        for ev in ("Network.webSocketFrameReceived", "Network.webSocketFrameSent"):
            cdp.on(ev, lambda e: setattr(self, "ws", self.ws + len(e["response"]["payloadData"])))

    def _req(self, e):
        self.reqs += 1
        self.hosts.add(e["request"]["url"].split("/")[2] if "//" in e["request"]["url"] else "data:")

    def snapshot(self):
        return {"requests": self.reqs, "transfer_bytes": self.encoded, "decoded_bytes": self.decoded,
                "websocket_payload_chars": self.ws, "served_from_cache": self.cached, "hosts": sorted(self.hosts)}


def geo_button(page, kind):
    root = page.frame_locator("iframe").first if kind == "iframe" else page
    return root.get_by_role("button", name="Use my location")


def load(browser, t, prof, timeout_s):
    ctx = browser.new_context(viewport={"width": 360, "height": 740}, device_scale_factor=2, is_mobile=True,
                              has_touch=True, geolocation=BENGALURU, permissions=["geolocation", "camera"])
    page = ctx.new_page()
    cdp = ctx.new_cdp_session(page)
    cdp.send("Network.enable")
    if prof:
        cdp.send("Network.emulateNetworkConditions", {
            "offline": False, "latency": prof["latency"],
            "downloadThroughput": prof["down_kbps"] * 1000 / 8, "uploadThroughput": prof["up_kbps"] * 1000 / 8})
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": prof["cpu"]})
    net = Net(cdp)
    t0 = time.time()
    page.goto(t["url"], timeout=timeout_s * 1000, wait_until="commit")
    page.get_by_role("heading", name="Find care near you").first.wait_for(timeout=timeout_s * 1000)
    t_heading = time.time() - t0
    t_ready = t_heading
    if t.get("geo"):
        geo_button(page, t["geo"]).wait_for(timeout=timeout_s * 1000)
        t_ready = time.time() - t0
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(1500)
    first = net.snapshot()
    res = {"first_visit": first, "heading_visible_s": round(t_heading, 2), "main_action_visible_s": round(t_ready, 2)}
    return ctx, page, net, res


def features(page, t):
    out = {"html_lang": page.evaluate("document.documentElement.lang")}
    if t.get("geo"):
        try:
            geo_button(page, t["geo"]).click(timeout=10000)
            # Gradio puts the result in a textarea value, invisible to get_by_text, so check values too
            out["geolocation"] = "works: " + page.wait_for_function(FIND_GOT_JS, timeout=15000).json_value()
        except Exception as e:
            out["geolocation"] = "failed: " + str(e).splitlines()[0][:160]
        page.wait_for_timeout(2500)  # let Streamlit/Gradio camera widgets start the fake stream
        out["video_elements"] = page.locator("video").count()
        out["image_file_inputs"] = page.locator("input[type=file][accept*=image]").count()
        out["file_inputs_with_capture"] = page.locator("input[type=file][capture]").count()
    page.add_script_tag(path=str(AXE_JS))
    axe = page.evaluate("t => axe.run(document, {runOnly: {type: 'tag', values: t}})", AXE_TAGS)
    out["axe_version"] = axe["testEngine"]["version"]
    out["axe_violations"] = [{"id": v["id"], "impact": v["impact"], "nodes": len(v["nodes"]), "help": v["help"],
                              "tags": [x for x in v["tags"] if x.startswith("wcag")]} for v in axe["violations"]]
    out["axe_passes"] = len(axe["passes"])
    out["axe_incomplete"] = [v["id"] for v in axe["incomplete"]]
    sizes = page.evaluate(TARGET_SIZE_JS)
    out["targets"] = sizes
    out["targets_under_24px"] = [s for s in sizes if min(s["w"], s["h"]) < 24]
    out["targets_under_44px"] = [s for s in sizes if min(s["w"], s["h"]) < 44]
    return out


def run(name, t, browser):
    proc = subprocess.Popen(t["cmd"], cwd=APPS, env={**os.environ, **t.get("env", {})}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_port(t["port"], t["url"]):
            return {"error": "server did not start"}
        result = {}
        for pname, prof in PROFILES.items():
            try:
                ctx, page, net, res = load(browser, t, prof, 180)
            except Exception as e:
                result[pname] = {"error": str(e).splitlines()[0][:200]}
                continue
            if pname == "none":
                before = net.snapshot()
                page.screenshot(path=str(OUT / "screens" / f"{name}.png"), full_page=True)
                res["features"] = features(page, t)
                # repeat visit in the same context: what a returning user pays with a warm cache
                b0 = net.snapshot()
                page.goto(t["url"], wait_until="commit")
                page.get_by_role("heading", name="Find care near you").first.wait_for(timeout=60000)
                page.wait_for_timeout(2500)
                b1 = net.snapshot()
                res["repeat_visit"] = {k: b1[k] - b0[k] for k in ("requests", "transfer_bytes", "decoded_bytes",
                                                                  "served_from_cache")}
                res["first_visit"] = before
            ctx.close()
            result[pname] = res
            print(name, pname, res.get("first_visit", {}).get("transfer_bytes"), res.get("main_action_visible_s"),
                  flush=True)
        return result
    finally:
        proc.terminate()
        proc.wait(10)
        time.sleep(1)


def main():
    names = sys.argv[1:] or list(TARGETS)
    path = OUT / "results.json"
    results = json.loads(path.read_text()) if path.exists() else {}
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
        for n in names:
            results[n] = run(n, TARGETS[n], browser)
            path.write_text(json.dumps(results, indent=1))
        browser.close()


if __name__ == "__main__":
    main()
