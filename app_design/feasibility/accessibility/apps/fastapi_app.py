# FastAPI + one hand-written HTML page. Everything the probe needs is a native
# browser API: navigator.geolocation, <input type=file capture>, speechSynthesis.
from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from pathlib import Path

from fastapi.responses import FileResponse, HTMLResponse

app = FastAPI()
app.add_middleware(GZipMiddleware, minimum_size=500)

BARE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Find care</title></head><body><main><h1>Find care near you</h1>
<p>Hello world.</p></main></body></html>"""

PROBE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Find care near you</title>
<style>
:root{--fg:#111;--bg:#fff;--accent:#0b57d0;--muted:#444}
@media (prefers-color-scheme:dark){:root{--fg:#f2f2f2;--bg:#121212;--accent:#8ab4f8;--muted:#ccc}}
body{margin:0;font:18px/1.5 system-ui,"Noto Sans","Noto Sans Devanagari",sans-serif;color:var(--fg);background:var(--bg)}
main{max-width:40rem;margin:0 auto;padding:16px}
.btn{display:flex;align-items:center;gap:12px;width:100%;min-height:56px;margin:12px 0;padding:8px 16px;
 font:inherit;font-weight:600;color:#fff;background:#0b57d0;border:0;border-radius:12px;cursor:pointer;box-sizing:border-box}
.btn svg{width:28px;height:28px;flex:none}
.btn small{display:block;font-weight:400}
.btn:focus-visible,input:focus-visible{outline:3px solid #e8710a;outline-offset:2px}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
label.txt{display:block;margin-top:16px;color:var(--muted)}
input[type=text]{width:100%;min-height:48px;font:inherit;padding:8px;box-sizing:border-box}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
</style></head>
<body><main>
<h1>Find care near you</h1>
<button class="btn" id="geo" type="button">
 <svg aria-hidden="true" viewBox="0 0 24 24"><path fill="currentColor" d="M12 2a7 7 0 0 0-7 7c0 5 7 13 7 13s7-8 7-13a7 7 0 0 0-7-7zm0 9.5A2.5 2.5 0 1 1 12 6a2.5 2.5 0 0 1 0 5.5z"/></svg>
 <span>Use my location <small lang="hi">&#x92E;&#x947;&#x930;&#x940; &#x91C;&#x917;&#x939;</small></span></button>
<label class="txt" for="place">Or type a town or PIN code</label>
<input id="place" type="text" inputmode="text" autocomplete="postal-code">
<label class="btn" for="photo">
 <svg aria-hidden="true" viewBox="0 0 24 24"><path fill="currentColor" d="M9 3 7.2 5H4a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-3.2L15 3H9zm3 5a5 5 0 1 1 0 10 5 5 0 0 1 0-10z"/></svg>
 <span>Take a photo (optional)</span></label>
<input class="sr" id="photo" type="file" accept="image/*" capture="environment">
<button class="btn" id="say" type="button">
 <svg aria-hidden="true" viewBox="0 0 24 24"><path fill="currentColor" d="M3 9v6h4l5 5V4L7 9H3zm13.5 3A4.5 4.5 0 0 0 14 8v8a4.5 4.5 0 0 0 2.5-4z"/></svg>
 <span>Read aloud</span></button>
<p id="out" role="status" aria-live="polite"></p>
</main>
<script>
const out = document.getElementById('out');
document.getElementById('geo').onclick = () => {
  if (!navigator.geolocation) { out.textContent = 'Location is not available. Type a town or PIN code.'; return; }
  out.textContent = 'Finding your location...';
  navigator.geolocation.getCurrentPosition(
    p => out.textContent = 'Got location ' + p.coords.latitude.toFixed(4) + ',' + p.coords.longitude.toFixed(4),
    e => out.textContent = 'Could not get location (' + e.message + '). Type a town or PIN code.',
    {enableHighAccuracy: true, timeout: 10000, maximumAge: 60000});
};
document.getElementById('photo').onchange = e => out.textContent = 'Photo selected: ' + (e.target.files[0] || {}).name;
document.getElementById('say').onclick = () => {
  if (!('speechSynthesis' in window)) { out.textContent = 'Read aloud is not supported on this phone.'; return; }
  const u = new SpeechSynthesisUtterance(out.textContent || document.querySelector('h1').textContent);
  u.lang = document.documentElement.lang; speechSynthesis.speak(u);
};
</script></body></html>"""


@app.get("/bare", response_class=HTMLResponse)
def bare():
    return BARE


@app.get("/", response_class=HTMLResponse)
def probe():
    return PROBE


# Offline test: page + service worker + cached facility snapshot (see offline_test.py).
HERE = Path(__file__).resolve().parent


@app.get("/pwa")
def pwa():
    return FileResponse(HERE / "pwa.html")


@app.get("/sw.js")
def sw():
    return FileResponse(HERE / "sw.js", media_type="text/javascript")


@app.get("/pack.json")
def pack():
    return FileResponse(HERE / "static" / "pack.json")
