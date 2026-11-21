"""Offline packs live in IndexedDB (issue #32): save, offline answer, migration from Cache Storage, persist().

Runs in Chromium against a real server. Skips when app/packs/out is not built or Playwright is missing.
"""
from __future__ import annotations

import gzip
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")

APP = Path(__file__).resolve().parents[1]
OUT = APP / "packs" / "out"
pytestmark = pytest.mark.skipif(not (OUT / "index.json").is_file(), reason="packs not built")

READ_IDB = """slug => new Promise((ok, fail) => {
  const r = indexedDB.open('rs-packs', 1);
  r.onupgradeneeded = () => r.result.createObjectStore('packs', {keyPath: 'slug'});
  r.onerror = () => fail(r.error);
  r.onsuccess = () => {
    const g = r.result.transaction('packs').objectStore('packs').get(slug);
    g.onsuccess = () => { const v = g.result; r.result.close();
      ok(v ? {sha256: v.sha256, built: v.built, bytes: v.body.byteLength} : null); };
  };
})"""
CACHE_PACK = """slug => navigator.serviceWorker.ready.then(reg => new Promise(ok => {
  const ch = new MessageChannel();
  ch.port1.onmessage = e => ok(e.data);
  reg.active.postMessage({type: 'cache-pack', slug}, [ch.port2]);
}))"""
FETCH_PACK = """slug => fetch('/api/pack/' + slug).then(async r => ({status: r.status,
  sha: r.headers.get('X-Pack-Sha256'), keys: r.ok ? Object.keys(await r.json()).length : 0}))"""


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
def pack() -> tuple[str, str]:
    idx = json.loads((OUT / "index.json").read_text())
    slug = min(idx["packs"], key=lambda s: idx["packs"][s]["gzip_bytes"])  # smallest built pack
    return slug, idx["packs"][slug]["sha256"]


def _ready(page) -> None:
    page.wait_for_function("navigator.serviceWorker.ready.then(() => true)")
    page.reload()
    page.wait_for_function("!!navigator.serviceWorker.controller")


def test_pack_saved_in_indexeddb_and_served_offline(base_url, browser, pack):
    slug, sha = pack
    ctx = browser.new_context(service_workers="allow")
    page = ctx.new_page()
    try:
        page.goto(base_url + "/")
        _ready(page)
        assert page.evaluate(CACHE_PACK, slug)["status"] == "saved"
        rec = page.evaluate(READ_IDB, slug)
        assert rec and rec["sha256"] == sha and rec["bytes"] > 0
        assert page.evaluate("caches.has('rs-packs-v1')") is False  # nothing left in Cache Storage
        assert page.evaluate(CACHE_PACK, slug)["status"] == "unchanged"  # sha match skips the download
        ctx.set_offline(True)
        got = page.evaluate(FETCH_PACK, slug)
        assert got["status"] == 200 and got["sha"] == sha and got["keys"] > 0
        assert page.evaluate(FETCH_PACK, "not_a_state")["status"] == 504
    finally:
        ctx.close()


def test_old_cache_storage_pack_moves_to_indexeddb(base_url, browser, pack):
    slug, sha = pack
    ctx = browser.new_context(service_workers="allow")
    page = ctx.new_page()
    try:
        # A phone from before #32: the pack sits in Cache Storage and no service worker of this version runs yet.
        page.goto(base_url + "/api/ping")
        raw = urllib.request.urlopen(f"{base_url}/api/pack/{slug}").read()
        body = (gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw).decode()
        page.evaluate("""([slug, sha, body]) => caches.open('rs-packs-v1').then(c => c.put('/api/pack/' + slug,
          new Response(body, {headers: {'Content-Type': 'application/json', 'X-Pack-Sha256': sha}})))""",
                      [slug, sha, body])
        page.goto(base_url + "/")
        _ready(page)
        page.wait_for_function("caches.has('rs-packs-v1').then(h => !h)")
        rec = page.evaluate(READ_IDB, slug)
        assert rec and rec["sha256"] == sha and rec["bytes"] == len(body.encode())
    finally:
        ctx.close()


def test_persist_requested_after_save(base_url, browser, pack):
    slug, _ = pack
    ctx = browser.new_context(service_workers="allow")
    page = ctx.new_page()
    try:
        page.add_init_script("""(() => { window.__persistCalls = 0;
          if (navigator.storage) { navigator.storage.persisted = async () => false;
            navigator.storage.persist = async () => { window.__persistCalls++; return true; }; } })()""")
        page.route("**/api/pack/locate", lambda r: r.fulfill(
            status=200, content_type="application/json", body=json.dumps({"slug": slug, "state": slug})))
        page.goto(base_url + "/")
        _ready(page)
        page.evaluate("""() => new Promise((ok, fail) => { const s = document.createElement('script');
          s.src = '/pack.js'; s.onload = () => { const t = document.createElement('script'); t.src = '/offline.js';
          t.onload = ok; t.onerror = fail; document.head.appendChild(t); }; document.head.appendChild(s); })""")
        res = page.evaluate("RSOffline.savePack(25.6, 85.1)")
        assert res["status"] in ("saved", "unchanged")
        meta = page.evaluate("RSOffline.meta()")
        assert meta["persisted"] is True and page.evaluate("window.__persistCalls") == 1
        page.evaluate("RSOffline.savePack(25.6, 85.1)")
        assert page.evaluate("window.__persistCalls") == 1  # asked once, not on every save
    finally:
        ctx.close()
