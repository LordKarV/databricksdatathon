"""Single-file offline referral page for one state: data embedded, no network, GPS or PIN lookup.

The file can be shared as a WhatsApp/Bluetooth document and opened from the phone's Files app.
Then checks in Chromium that it works from file:// with no network: isSecureContext, GPS lookup,
PIN fallback when location is denied, and that no request leaves the page.
Run: ../../../.venv-offline/bin/python make_offline_html.py   Writes out/referral_bihar.html.
"""
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
LABELS = {"dialysis": "Dialysis", "emergency_csection": "Emergency C-section", "nicu": "NICU (newborn intensive care)",
          "cardiac_surgery": "Cardiac surgery", "mri": "MRI", "burn_care": "Burn care", "trauma_emergency": "Trauma / accident"}

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Referral pack: Bihar</title>
<style>body{font:17px/1.5 system-ui,"Noto Sans",sans-serif;margin:0 auto;max-width:40rem;padding:16px}
button,select,input{font:inherit;min-height:48px;width:100%;margin:6px 0;box-sizing:border-box}
li{margin:12px 0}.q{color:#444}@media (prefers-color-scheme:dark){body{background:#121212;color:#eee}.q{color:#bbb}}</style>
</head><body><h1>Referral pack: Bihar</h1>
<p>Saved data from __SNAP__. Works without internet. Call ahead before travelling: listings can be wrong.</p>
<label for="svc">Service</label><select id="svc">__OPTS__</select>
<button id="gps" type="button">Use my GPS location</button>
<label for="pin">Or PIN code</label><input id="pin" inputmode="numeric" maxlength="6">
<button id="go" type="button">Search by PIN code</button>
<p id="out" role="status"></p><ol id="list"></ol>
<script id="pack" type="application/json">__PACK__</script>
<script id="picker" type="application/json">__PICKER__</script>
<script>
const pack = JSON.parse(document.getElementById('pack').textContent);
const picker = JSON.parse(document.getElementById('picker').textContent);
const $ = id => document.getElementById(id);
function km(a, b, c, d) { const r = Math.PI / 180, x = Math.sin((c - a) * r / 2) ** 2 +
  Math.cos(a * r) * Math.cos(c * r) * Math.sin((d - b) * r / 2) ** 2; return 12742 * Math.asin(Math.sqrt(x)); }
function show(pin, lat, lon, how) {
  const svc = $('svc').value, ids = pack.index[pin][svc];
  $('out').textContent = 'Nearest 3 for PIN ' + pin + ' (' + how + '), data of ' + pack.snapshot + '.';
  $('list').replaceChildren(...ids.map(i => {
    const [name, phones, la, lo] = pack.facilities[i], [conf, q1, q2] = pack.evidence[i + '|' + svc];
    const li = document.createElement('li');
    li.innerHTML = '<b></b> - ' + km(lat, lon, la, lo).toFixed(0) + ' km straight line, confidence ' +
      (conf == null ? 'unknown' : Math.round(conf * 100) + '%') + '<br><span class=q></span><br>';
    li.querySelector('b').textContent = name;
    li.querySelector('.q').textContent = '"' + q1[0] + '" [' + q1[1] + ']' + (q2 ? ' "' + q2[0] + '" [' + q2[1] + ']' : '');
    if (phones[0]) { const a = document.createElement('a'); a.href = 'tel:' + phones[0];
      a.textContent = 'Call ' + phones[0]; li.append(a); }
    return li; }));
}
function nearestPin(lat, lon) { let best, bd = 1e9;
  for (const [p, [la, lo]] of Object.entries(picker)) { const d = km(lat, lon, la, lo); if (d < bd) { bd = d; best = p; } }
  return best; }
$('gps').onclick = () => { $('out').textContent = 'Waiting for GPS (outdoors can take a minute without internet)...';
  navigator.geolocation.getCurrentPosition(p => {
      const {latitude: a, longitude: b} = p.coords; localStorage.setItem('fix', JSON.stringify([a, b, Date.now()]));
      show(nearestPin(a, b), a, b, 'GPS'); },
    e => { const f = JSON.parse(localStorage.getItem('fix') || 'null');
      if (f) return show(nearestPin(f[0], f[1]), f[0], f[1], 'last GPS fix ' + new Date(f[2]).toLocaleString());
      $('out').textContent = 'No GPS fix (' + e.message + '). Type the PIN code.'; $('pin').focus(); },
    {enableHighAccuracy: true, timeout: 60000, maximumAge: 600000}); };
$('go').onclick = () => { const p = $('pin').value.trim(), c = picker[p];
  if (!c) { $('out').textContent = 'PIN ' + p + ' is not in the Bihar pack.'; return; } show(p, c[0], c[1], 'PIN'); };
</script></body></html>"""


def build() -> Path:
    pack = (OUT / "pack_bihar_pin_norm.json").read_text()
    picker = (OUT / "picker_bihar.json").read_text()
    snap = json.loads(pack)["snapshot"]
    opts = "".join(f'<option value="{k}">{v}</option>' for k, v in LABELS.items())
    # "</" inside embedded JSON would close the script element; escape it
    html = (PAGE.replace("__SNAP__", snap).replace("__OPTS__", opts)
            .replace("__PACK__", pack.replace("</", "<\\/")).replace("__PICKER__", picker.replace("</", "<\\/")))
    p = OUT / "referral_bihar.html"
    p.write_text(html, encoding="utf-8")
    return p


def check(p: Path) -> dict:
    res = {"bytes": p.stat().st_size}
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        for name, kw in [("gps", {"geolocation": {"latitude": 25.6093, "longitude": 85.1376}, "permissions": ["geolocation"]}),
                         ("denied", {})]:
            ctx = b.new_context(offline=True, **kw)
            page = ctx.new_page()
            reqs = []
            page.on("request", lambda r: reqs.append(r.url))
            page.goto(p.as_uri())
            res[name] = {"secure_context": page.evaluate("isSecureContext"), "has_geolocation": page.evaluate("'geolocation' in navigator")}
            page.select_option("#svc", "emergency_csection")
            page.click("#gps")
            if name == "denied":
                page.wait_for_function("document.querySelector('#out').textContent.includes('PIN code')")
                res[name]["message"] = page.inner_text("#out")
                page.fill("#pin", "800001")
                page.click("#go")
            page.wait_for_function("document.querySelectorAll('#list li').length === 3", timeout=15000)
            res[name] |= {"status": page.inner_text("#out"), "first": page.locator("#list li").first.inner_text(),
                          "non_file_requests": [u for u in reqs if not u.startswith("file:")]}
            ctx.close()
        b.close()
    return res


if __name__ == "__main__":
    r = check(build())
    (OUT / "offline_html_results.json").write_text(json.dumps(r, indent=1, ensure_ascii=False))
    print(json.dumps(r, indent=1, ensure_ascii=False))
    assert r["gps"]["secure_context"] and "GPS" in r["gps"]["status"] and not r["gps"]["non_file_requests"]
    assert "PIN 800001" in r["denied"]["status"]
    print("ASSERTIONS PASSED")
