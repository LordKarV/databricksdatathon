"""Drive the app through the demo shots at phone size and record clean captures (issue #12).

    .venv-app/bin/python demo/capture.py --local          # starts the app on localhost (no login), for rehearsal
    .venv-app/bin/python demo/capture.py                  # the deployed Databricks App (log in once by hand)
    .venv-app/bin/python demo/capture.py --only route,how # a subset of shots

Writes demo/out/ (git-ignored): demo.webm (one continuous take, 360x780 at 2x), shots/NN-<id>.png (one still per
shot, for the editor), and shots.json (each shot's start and end in seconds within the video, so cuts line up with
demo/SCRIPT.md).

Login: the deployed app sits behind the Databricks workspace login. The browser keeps its session in a profile
folder outside the repo (default ~/.cache/referral-saathi-demo-profile). The first time, the window stops on the
login page; log in there by hand and press Enter in this terminal. This script never reads, types or stores a
credential, and the profile folder is never inside the repo.

Location: the recording sets the browser's GPS to the demo point (Singwahini, Sitamarhi, as in
APP_EXPERIENCE 10.5); the narration says so. Nothing in the app is switched into a demo mode.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, sync_playwright
from playwright.sync_api import TimeoutError as PwTimeout

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "out"
LIVE = "https://referral-saathi-7474649134616784.aws.databricksapps.com"
PROFILE = Path.home() / ".cache" / "referral-saathi-demo-profile"
APP_NAME = re.compile(r"Bharosa|Referral Saathi")  # the live app shows the old name until it is redeployed
SITAMARHI = {"latitude": 26.5951, "longitude": 85.4808, "accuracy": 40}
MOHANIA = "25.15, 83.68"  # NH-19 near Mohania, benchmark q29 (APP_EXPERIENCE 10.5)
VIEWPORT = {"width": 360, "height": 780}


@dataclass
class Shot:
    id: str
    title: str
    hold_s: float  # how long the final frame stays on screen, for the narration over it
    run: Callable[[Page, BrowserContext, str], None]


# ---------- helpers ----------
def go(page: Page, hash_: str) -> None:
    page.evaluate("h => { location.hash = h; }", hash_)
    page.wait_for_timeout(300)


def glide(page: Page, selector: str | None = None, to_bottom: bool = False, ms: int = 1500) -> None:
    """Smooth scroll so the video shows the page moving instead of jumping."""
    if to_bottom:
        page.evaluate("window.scrollTo({top: document.body.scrollHeight, behavior: 'smooth'})")
    elif selector:
        page.locator(selector).first.evaluate("el => el.scrollIntoView({behavior: 'smooth', block: 'start'})")
    else:
        page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
    page.wait_for_timeout(ms)


def tile(page: Page, label: str) -> None:
    go(page, "#/")
    page.locator(".tile", has_text=label).first.click()


# ---------- shots (ids match demo/STORYBOARD.md) ----------
def s_open(page: Page, ctx: BrowserContext, base: str) -> None:
    go(page, "#/")
    gps = page.get_by_role("button", name="Use my location (GPS)")
    page.wait_for_function("document.querySelector('#gps') || document.body.innerText.includes('GPS')")
    if gps.count():
        gps.click()
    page.get_by_text("GPS 40 m").wait_for()


def s_plan(page: Page, ctx: BrowserContext, base: str) -> None:
    tile(page, "Dialysis")
    page.locator("article.card").first.wait_for()
    glide(page, "article.card")


def s_why_not(page: Page, ctx: BrowserContext, base: str) -> None:
    summary = page.get_by_text("Why not the nearer ones?")
    if summary.count():
        summary.click()
        glide(page, "details[open]")


def s_why(page: Page, ctx: BrowserContext, base: str) -> None:
    go(page, "#/why/1")
    page.get_by_text("How we decided").wait_for()
    page.wait_for_timeout(1200)
    glide(page, "#how")


def s_call(page: Page, ctx: BrowserContext, base: str) -> None:
    go(page, "#/plan")
    page.locator("article.card").first.wait_for()
    page.get_by_role("link", name="Call ahead").first.click()
    page.get_by_role("button", name="Said no").wait_for()
    page.wait_for_timeout(1200)
    page.get_by_role("button", name="Said no").click()


def s_slip(page: Page, ctx: BrowserContext, base: str) -> None:
    go(page, "#/plan")
    page.locator("article.card").nth(1).wait_for()
    go(page, "#/why/2")  # the backup, after option 1 said no
    page.get_by_role("button", name="Said yes").click()
    page.get_by_role("link", name="Make referral slip").click()
    page.locator(".slip").wait_for()
    glide(page, ".slip")


def s_route(page: Page, ctx: BrowserContext, base: str) -> None:
    tile(page, "Accident")
    page.get_by_text("Suggested route").first.wait_for(timeout=8000)  # needs #56 deployed
    glide(page, ".route")
    glide(page, ".route .stops > li:nth-child(2)", ms=2000)


def s_offline(page: Page, ctx: BrowserContext, base: str) -> None:
    tile(page, "Dialysis")
    page.locator("article.card").first.wait_for()
    page.wait_for_function("!!localStorage.getItem('rs.pack')", timeout=90_000)  # state pack saved in background
    ctx.set_offline(True)
    page.reload()
    page.wait_for_selector("#offline:not([hidden])")
    page.wait_for_timeout(1500)
    tile(page, "Dialysis")
    page.get_by_text("Call before you go").wait_for()
    glide(page, "article.card")


def s_area(page: Page, ctx: BrowserContext, base: str) -> None:
    ctx.set_offline(False)
    go(page, "#/change")
    page.get_by_label("PIN, village, town, district, or 'lat, lon'").fill(MOHANIA)
    page.get_by_role("button", name="Use this place").click()
    page.wait_for_timeout(800)
    tile(page, "Accident")
    page.locator("article.card").first.wait_for()
    page.locator("[data-depth=area]").click()
    page.locator("#ten-calls").wait_for()
    page.wait_for_timeout(1200)
    glide(page, "#ten-calls", ms=2000)


def s_how(page: Page, ctx: BrowserContext, base: str) -> None:
    go(page, "#/how")
    page.get_by_text("Page data built").wait_for()
    for sel in ["h2:has-text('The data problem')", "h2:has-text('How good it is')", "h2:has-text('Limits')"]:
        glide(page, sel, ms=2200)


def s_stories(page: Page, ctx: BrowserContext, base: str) -> None:
    go(page, "#/stories")  # data stories (#53)
    page.locator("h1", has_text="stor").first.wait_for(timeout=8000)
    glide(page, to_bottom=True, ms=2500)


SHOTS = [
    Shot("open", "GPS fills the place by itself", 3, s_open),
    Shot("plan", "Plan: first choice, backups, CALL FIRST", 4, s_plan),
    Shot("why_not", "Why not the nearer ones", 4, s_why_not),
    Shot("why", "WHY card: quotes, track record, points", 6, s_why),
    Shot("call", "Call ahead: said no", 3, s_call),
    Shot("slip", "Referral slip for the backup", 4, s_slip),
    Shot("route", "Multi-stop route for an accident", 6, s_route),
    Shot("offline", "No internet: same answer from the saved pack", 5, s_offline),
    Shot("area", "Area depth near Mohania: gap and ten calls", 6, s_area),
    Shot("how", "How this works", 4, s_how),
    Shot("stories", "Data stories", 4, s_stories),
]


# ---------- runner ----------
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_local() -> tuple[subprocess.Popen, str]:
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "app:app", "--port", str(port), "--no-access-log"],
                           cwd=ROOT / "app", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            urllib.request.urlopen(base + "/api/ping", timeout=1)
            return srv, base
        except OSError:
            time.sleep(0.2)
    srv.terminate()
    raise SystemExit("local app did not start (build app/facts and planner/out first)")


def wait_for_login(page: Page, base: str) -> None:
    page.goto(base + "/")
    if page.get_by_text(APP_NAME).count() and base in page.url:
        return
    print("\nThe app is behind the workspace login. Log in in the browser window (by hand), wait until the app's "
          "start screen shows, then press Enter here.")
    input()
    page.goto(base + "/")
    page.get_by_text(APP_NAME).first.wait_for(timeout=60_000)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--local", action="store_true", help="start the app on localhost instead of the live URL")
    ap.add_argument("--base", default=os.environ.get("DEMO_BASE", LIVE), help="app URL (default: deployed app)")
    ap.add_argument("--only", default="", help="comma-separated shot ids")
    ap.add_argument("--profile", type=Path, default=PROFILE, help="browser profile folder (outside the repo)")
    ap.add_argument("--headless", action="store_true", help="no window (only with --local; login needs a window)")
    args = ap.parse_args()
    if ROOT in args.profile.resolve().parents:
        raise SystemExit("keep the browser profile outside the repo: it holds the login session")
    shots = [s for s in SHOTS if not args.only or s.id in args.only.split(",")]
    srv, base = start_local() if args.local else (None, args.base.rstrip("/"))
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "shots").mkdir(parents=True)
    profile = args.profile if not args.local else OUT / ".profile"  # rehearsal: throwaway profile, no login
    marks = []
    try:
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                str(profile), headless=args.headless and args.local, viewport=VIEWPORT, device_scale_factor=2,
                is_mobile=True, has_touch=True, locale="en-IN", timezone_id="Asia/Kolkata",
                geolocation=SITAMARHI, permissions=["geolocation"], service_workers="allow",
                record_video_dir=str(OUT / "video"), record_video_size={"width": 720, "height": 1560})
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            t0 = time.monotonic()
            wait_for_login(page, base) if not args.local else page.goto(base + "/")
            page.wait_for_function("navigator.serviceWorker.ready.then(() => true)")
            page.reload()  # the service worker now controls the page, so the offline shot works
            for n, shot in enumerate(shots, 1):
                start = time.monotonic() - t0
                try:
                    shot.run(page, ctx, base)
                except PwTimeout as e:  # feature not in this build yet: note it and keep the take going
                    ctx.set_offline(False)
                    marks.append({"n": n, "id": shot.id, "title": shot.title, "skipped": str(e).splitlines()[0]})
                    print(f"{n:02d} {shot.id:8s} SKIPPED  {marks[-1]['skipped']}")
                    continue
                page.screenshot(path=str(OUT / "shots" / f"{n:02d}-{shot.id}.png"))
                page.wait_for_timeout(int(shot.hold_s * 1000))
                marks.append({"n": n, "id": shot.id, "title": shot.title, "start_s": round(start, 1),
                              "end_s": round(time.monotonic() - t0, 1)})
                print(f"{n:02d} {shot.id:8s} {marks[-1]['start_s']:6.1f}-{marks[-1]['end_s']:6.1f} s  {shot.title}")
            video = page.video.path() if page.video else None
            ctx.close()
            if video:
                shutil.move(video, OUT / "demo.webm")
                shutil.rmtree(OUT / "video", ignore_errors=True)
    finally:
        if srv:
            srv.terminate()
        shutil.rmtree(OUT / ".profile", ignore_errors=True)
    (OUT / "shots.json").write_text(json.dumps({"base": base, "shots": marks}, indent=1))
    done = [m for m in marks if "skipped" not in m]
    print(f"wrote {OUT / 'demo.webm'}, {len(done)} stills, {len(marks) - len(done)} shots skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
