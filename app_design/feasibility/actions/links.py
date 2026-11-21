"""Deep-link builders for the "getting there" actions, plus the tap-test page.

Every builder returns a plain URL string, so the app can drop it into an <a href>
(Streamlit st.link_button / markdown, Dash html.A). Nothing here books a ride or
places a call: each link only opens another app with fields prefilled, and the
user still has to press Call / Book. Formats and their sources are in REPORT.md.

Run `python links.py` to run the self-check and regenerate tap_test.html.
"""
import html
import json
import re
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit, parse_qs

EMERGENCY = {
    "108": "Emergency ambulance (accident, trauma, labour complication, unconscious, breathing)",
    "102": "Free patient transport for pregnant women and sick infants (JSSK), home to public facility and drop back",
    "112": "Single emergency number (ERSS); routes to police, fire or ambulance",
}

# A dialable Indian number in the dataset is +91 then 10 digits (mobile starts 6-9,
# landline with STD code starts 1-5). Anything else ('100', shifted text, dates) is
# refused, because a wrong tel: link on a "call first" button is worse than none.
_E164_IN = re.compile(r"\+91[1-9]\d{9}")


def e164_india(raw):
    """Return '+91XXXXXXXXXX' or None. Accepts spaces, dashes, a leading 0 or 91."""
    if not isinstance(raw, str):
        return None
    digits = re.sub(r"[\s\-().]", "", raw)
    if re.fullmatch(r"0[1-9]\d{9}", digits):
        digits = "+91" + digits[1:]
    elif re.fullmatch(r"91[1-9]\d{9}", digits):
        digits = "+" + digits
    elif re.fullmatch(r"[6-9]\d{9}", digits):
        digits = "+91" + digits
    return digits if _E164_IN.fullmatch(digits) else None


def tel(number):
    """tel: link. Emergency short codes pass through; other numbers must validate."""
    if number in EMERGENCY:
        return f"tel:{number}"
    n = e164_india(number)
    if n is None:
        raise ValueError(f"not a dialable Indian number: {number!r}")
    return f"tel:{n}"


def sms(body, number=None):
    """RFC 5724 sms: link. Without a number, Android opens the composer with no recipient (tap-test)."""
    to = e164_india(number) if number else ""
    return f"sms:{to}?body={quote(body)}"


def whatsapp(text, number=None):
    """wa.me click-to-chat. Number is digits only, no '+'. No number: user picks a contact."""
    n = (e164_india(number) or "")[1:] if number else ""
    return f"https://wa.me/{n}?text={quote(text)}"


def gmaps_directions(dest_lat=None, dest_lng=None, dest_text=None, mode="driving", navigate=False):
    """Google Maps URLs directions. No API key. Origin omitted = device location.

    Pass coordinates only when the location layer trusts them; otherwise pass the
    facility name and town as dest_text and let Google resolve it.
    """
    dest = f"{dest_lat},{dest_lng}" if dest_lat is not None else dest_text
    q = {"api": "1", "destination": dest, "travelmode": mode}
    if navigate:
        q["dir_action"] = "navigate"
    return "https://www.google.com/maps/dir/?" + urlencode(q)


def gmaps_search(query):
    return "https://www.google.com/maps/search/?" + urlencode({"api": "1", "query": query})


def geo_uri(lat, lng, label):
    """Android geo: URI. Opens a chooser of installed map apps (works with offline maps)."""
    return f"geo:0,0?q={lat},{lng}({quote(label)})"


def uber_ul(lat, lng, nickname, address=None):
    """Legacy universal link, still redirected by m.uber.com on 2026-11-21 (probes/)."""
    q = {
        "action": "setPickup",
        "pickup": "my_location",
        "dropoff[latitude]": lat,
        "dropoff[longitude]": lng,
        "dropoff[nickname]": nickname,
    }
    if address:
        q["dropoff[formatted_address]"] = address
    return "https://m.uber.com/ul/?" + urlencode(q)


def uber_looking(lat, lng, name):
    """Format shown in Uber's current deep-link docs: drop[0] is an encoded JSON Location."""
    drop = json.dumps({"latitude": lat, "longitude": lng, "addressLine1": name}, separators=(",", ":"))
    return "https://m.uber.com/looking?" + urlencode({"drop[0]": drop})


def ola(lat, lng, name, category="auto", later=False, app_scheme=False, utm_source=None):
    """Ola affiliate deep link. Docs mark utm_source (an affiliate token) as mandatory;
    without one the link may still open the app (tap-test). category: auto, bike, mini..."""
    q = {"drop_lat": lat, "drop_lng": lng, "drop_address": name, "category": category, "landing_page": "bk"}
    if later:
        q["bk_act"] = "rl"  # opens the Ride Later date-time picker
    if utm_source:
        q["utm_source"] = utm_source
    base = "olacabs://app/launch?" if app_scheme else "https://olawebcdn.com/assets/ola-universal-link.html?"
    return base + urlencode(q)


def app_link(domain, package):
    """Open an app through its verified https App Link, Play Store as fallback.
    Used for Rapido and Namma Yatri, which document no destination parameters."""
    play = f"https://play.google.com/store/apps/details?id={package}"
    return f"intent://{domain}/#Intent;scheme=https;package={package};S.browser_fallback_url={quote(play, safe='')};end"


SERVICE_QUESTIONS = {
    "dialysis": ["Is the dialysis unit running today, and is there a slot today or tomorrow?",
                 "Do you take new patients, and what is the cost per session? Is PM-JAY accepted?"],
    "emergency c-section": ["Is an obstetrician AND an anaesthetist on duty right now?",
                            "Is the operation theatre free, and is blood available?"],
    "nicu": ["Is a NICU bed free right now? Is there a ventilator for a newborn if needed?"],
    "trauma": ["Is a surgeon on duty now, and is the CT scan working?"],
    "burn care": ["Do you have a burns unit with a free bed? Do you treat burns over large areas?"],
    "mri": ["Is the MRI machine working, when is the next slot, and what does it cost?"],
    "cardiac surgery": ["Is the cardiac surgeon available this week, and is the cath lab working?"],
}


def call_script(service, facility, town, caller="a health worker"):
    """The script read aloud before travelling. Question 1 checks the number reaches
    this facility (the dataset has shared and mislabelled phone numbers)."""
    lines = [
        f"Hello, I am {caller}. Is this {facility} in {town}?",
        f"I have a patient who needs {service}.",
        *SERVICE_QUESTIONS.get(service.lower(), ["Can you provide this today?"]),
        "If you cannot, which hospital nearby can?",
        "Whom should we ask for when we arrive? Thank you.",
    ]
    return "\n".join(f"{i}. {s}" for i, s in enumerate(lines, 1))


# ---- tap-test page ---------------------------------------------------------

DEST = (28.5645, 77.2100, "AIIMS New Delhi", "Ansari Nagar, New Delhi")  # probes/nominatim_aiims.txt
FAKE_FACILITY_PHONE = "+911100000000"  # not a real line; only exercises the tel: path


def test_rows():
    lat, lng, name, addr = DEST
    script = call_script("dialysis", name, "New Delhi")
    share = (f"Plan: go to {name}, {addr}.\nMap: {gmaps_directions(lat, lng)}\n"
             f"Call first: {FAKE_FACILITY_PHONE}\n\nQuestions to ask:\n{script}")
    return [
        ("Phone", "Call 108 (dialer only)", tel("108"), "Dialer opens with 108. DO NOT press call."),
        ("Phone", "Call 102 (dialer only)", tel("102"), "Dialer opens with 102. DO NOT press call."),
        ("Phone", "Call 112 (dialer only)", tel("112"), "Dialer opens with 112. DO NOT press call."),
        ("Phone", "Call facility (fake number)", tel(FAKE_FACILITY_PHONE), "Dialer opens with +91 11 0000 0000."),
        ("Maps", "Google Maps directions, car", gmaps_directions(lat, lng), "Maps app opens a route from your location."),
        ("Maps", "Google Maps directions, two-wheeler", gmaps_directions(lat, lng, mode="two-wheeler"), "Two-wheeler route (India)."),
        ("Maps", "Google Maps start navigation", gmaps_directions(lat, lng, navigate=True), "Turn-by-turn starts. Stop it after."),
        ("Maps", "Google Maps by name (low-trust coords)", gmaps_directions(dest_text=f"{name}, {addr}"), "Route to the named place."),
        ("Maps", "geo: chooser", geo_uri(lat, lng, name), "Chooser of map apps, pin labelled AIIMS."),
        ("Ride", "Uber universal link /ul/", uber_ul(lat, lng, name, addr), "Uber opens, drop-off AIIMS. DO NOT confirm."),
        ("Ride", "Uber /looking (current docs)", uber_looking(lat, lng, name), "Uber opens, drop-off AIIMS. DO NOT confirm."),
        ("Ride", "Uber uber:// scheme", "uber://?" + urlsplit(uber_ul(lat, lng, name, addr)).query, "Only if Uber installed."),
        ("Ride", "Ola auto, universal link", ola(lat, lng, name), "Ola opens on auto, drop AIIMS, or web after 5 s. DO NOT confirm."),
        ("Ride", "Ola bike, universal link", ola(lat, lng, name, category="bike"), "Ola bike, drop AIIMS."),
        ("Ride", "Ola auto, ride later", ola(lat, lng, name, later=True), "Ola date-time picker (for dialysis)."),
        ("Ride", "Ola auto, olacabs:// scheme", ola(lat, lng, name, app_scheme=True), "Only if Ola installed."),
        ("Ride", "Rapido (open app only)", app_link("rapido.bike", "com.rapido.passenger"), "Rapido opens, or Play Store. Destination NOT prefilled."),
        ("Ride", "Namma Yatri (open app only)", app_link("nammayatri.in", "in.juspay.nammayatri"), "Namma Yatri opens, or Play Store. Destination NOT prefilled."),
        ("Share", "WhatsApp, pick a contact", whatsapp(share), "WhatsApp contact picker, message prefilled."),
        ("Share", "SMS, no recipient", sms(share), "Messages composer with the plan text."),
        ("Share", "SMS to fake number", sms("Test from datathon tap-test", FAKE_FACILITY_PHONE), "Composer to +91 11 0000 0000. DO NOT send."),
    ]


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Getting there tap test</title>
<style>
*{{box-sizing:border-box}}
:root{{--bg:#fff;--fg:#111;--muted:#555;--line:#ccc;--btn:#0b57d0;--btnfg:#fff;--warn:#8a1c00}}
@media (prefers-color-scheme:dark){{:root{{--bg:#121212;--fg:#eee;--muted:#aaa;--line:#444;--btn:#8ab4f8;--btnfg:#000;--warn:#ffb4a0}}}}
body{{background:var(--bg);color:var(--fg);font:17px/1.45 system-ui,sans-serif;margin:0;padding:16px;max-width:720px}}
h1{{font-size:1.4rem}} h2{{font-size:1.1rem;margin-top:1.6rem}} .warn{{color:var(--warn);font-weight:600}}
.row{{border-top:1px solid var(--line);padding:12px 0}}
a.btn{{display:block;min-height:48px;padding:12px 16px;border-radius:8px;background:var(--btn);color:var(--btnfg);text-decoration:none;font-weight:600}}
a.btn:focus-visible{{outline:3px solid var(--fg);outline-offset:2px}}
.exp{{color:var(--muted);margin:6px 0}} code{{word-break:break-all;font-size:.75rem;color:var(--muted)}}
select,textarea,button{{font:inherit;min-height:44px}} textarea{{width:100%;box-sizing:border-box}}
</style></head><body>
<h1>Getting there: tap test</h1>
<p class="warn">Nothing on this page books a ride or places a call by itself, but the apps it opens can. Do not press Call, Book, Confirm or Send.</p>
<p>Test destination: {dest}. Open this page in Chrome on an Android phone (not inside another app). For each link, tap it, come back, and record what happened.</p>
<label>Phone and Android version <input id="device" style="width:100%"></label>
{rows}
<h2>Results</h2>
<textarea id="out" rows="8" readonly aria-label="Results text"></textarea>
<p><button type="button" id="mk">Build results text</button> <a id="wa" class="btn" href="#">Send results on WhatsApp</a></p>
<script>
document.getElementById('mk').onclick=function(){{
  var t='Tap test '+new Date().toISOString().slice(0,10)+' | '+document.getElementById('device').value+'\\n';
  document.querySelectorAll('select[data-id]').forEach(function(s){{t+=s.dataset.id+': '+s.value+'\\n';}});
  document.getElementById('out').value=t;
  document.getElementById('wa').href='https://wa.me/?text='+encodeURIComponent(t);
}};
</script></body></html>"""

ROW = """<div class="row"><a class="btn" href="{href}">{label}</a>
<p class="exp">Expect: {exp}</p><code>{href}</code>
<p><label>Result <select data-id="{label}"><option>not tried</option><option>works as expected</option>
<option>opens app, destination missing</option><option>opens web or store instead</option><option>nothing happens</option></select></label></p></div>"""


def build_page():
    parts, section = [], None
    for sec, label, href, exp in test_rows():
        if sec != section:
            parts.append(f"<h2>{sec}</h2>")
            section = sec
        parts.append(ROW.format(href=html.escape(href), label=html.escape(label), exp=html.escape(exp)))
    return PAGE.format(dest=html.escape(f"{DEST[2]}, {DEST[3]} ({DEST[0]}, {DEST[1]})"), rows="\n".join(parts))


def _self_check():
    assert e164_india("+917001985950") == "+917001985950"
    assert e164_india("070019 85950") == "+917001985950"
    assert e164_india("9876543210") == "+919876543210"
    for bad in ("100", "2025-08-25", " Laparoscopy", None, "+44123", "+910000000000"):
        assert e164_india(bad) is None, bad
    assert tel("108") == "tel:108"
    try:
        tel("100")
        raise AssertionError("tel('100') must refuse")
    except ValueError:
        pass
    q = parse_qs(urlsplit(uber_ul(12.97, 77.59, "City Hospital & Co")).query)
    assert q["pickup"] == ["my_location"] and q["dropoff[nickname]"] == ["City Hospital & Co"]
    drop = json.loads(parse_qs(urlsplit(uber_looking(12.97, 77.59, "X")).query)["drop[0]"][0])
    assert drop == {"latitude": 12.97, "longitude": 77.59, "addressLine1": "X"}
    q = parse_qs(urlsplit(ola(12.97, 77.59, "X", later=True)).query)
    assert q["bk_act"] == ["rl"] and q["category"] == ["auto"] and "utm_source" not in q
    assert parse_qs(urlsplit(gmaps_directions(1, 2)).query)["destination"] == ["1,2"]
    assert whatsapp("a b&c").endswith("?text=a%20b%26c")
    assert whatsapp("hi", "+917001985950").startswith("https://wa.me/917001985950?")
    assert sms("a&b") == "sms:?body=a%26b"
    assert "Is this X in Y?" in call_script("NICU", "X", "Y") and "NICU bed" in call_script("NICU", "X", "Y")
    assert all(len(h) <= 2048 for _, _, h, _ in test_rows())  # Google Maps URL limit
    print("self-check ok")


if __name__ == "__main__":
    _self_check()
    out = Path(__file__).with_name("tap_test.html")
    out.write_text(build_page(), encoding="utf-8")
    print("wrote", out)
