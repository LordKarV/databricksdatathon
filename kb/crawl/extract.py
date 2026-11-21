"""Page text extraction, redaction and site-liveness heuristics. Pure functions, run in worker
processes by crawl.py so parsing never blocks the fetch loop."""
import re
from urllib.parse import urljoin, urlparse

import trafilatura
from selectolax.lexbor import LexborHTMLParser as HTMLParser

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Indian mobiles (10 digits from 6-9, optional +91/0) and landlines with an STD code separator.
# Redacted everywhere: doctors' numbers must not be stored, and the KB does not need any phone.
# lookarounds reject digits and decimal points ("1.5"), not a sentence-ending period
PHONE = re.compile(r"(?<!\d)(?<!\d\.)(?:\+?91[\s.-]?|0)?(?:[6-9]\d{4}[\s.-]?\d{5}|\d{2,5}[\s.-]\d{6,8})(?!\d)(?!\.\d)")
CHROME_SEL = ("header", "footer", "[class*=top-bar]", "[class*=topbar]", "[class*=header-top]",
              "[class*=footer]", "[id*=footer]", "[class*=timing]", "[id*=timing]")
PARKED = re.compile(r"(domain (name )?(is |may be )?for sale|buy this domain|parked (free|domain|by)|domain parking|"
                    r"sedoparking|hugedomains|afternic|this domain is available|inquire about this domain|"
                    r"get this domain|(?<![a-z])dan\.com|expireddomains\.com|dropcatch)", re.I)
# expired hospital domains re-registered for Indonesian gambling spam (hand check: 13 of 25 redirect_other_org)
SPAM = re.compile(r"(slot\s?gacor|situs\s+(slot|judi|toto|togel|poker)|\btogel\b|judi\s+online|bandar\s+(toto|togel|judi)|"
                  r"slot\s?online|slot\s?777|slot88|maxwin|live\s+draw\s+hk|poker\s+online|link\s+alternatif|"
                  r"sattamatka|satta\s+matka|casino|sports\s+betting|online\s+betting|betting\s+app|sbobet|judi\s+bola|"
                  r"game\s+online|nh\u00e0\s+c\u00e1i|phim\s+sex|live\s+draw|\b1win\b|dafabet|bc\.game|bc\s+game|"
                  r"\bgacor\b|\bslot\d{2,3}\b|\b(toto|togel)\s?\d*\b)", re.I)
SUSPENDED = re.compile(r"(account (has been )?suspended|this (site|website|domain) (has )?expired|"
                       r"website (is )?(expired|suspended)|renew (your|this) (domain|hosting)|"
                       r"hosting (account )?(has )?expired|default web site page|index of /)", re.I)
# title-only: words that are normal in page bodies of hacked-but-real sites are decisive in a title
TITLE_SPAM = re.compile(r"(aviator|crash\s+game|real\s+money|betting|bookmaker|baccarat|mostbet|vavada|1xbet|"
                        r"starx|vortex\s+game|tower\s+rush|jackpot|\bbonus\b)", re.I)


def spam_verdict(title: str, text: str) -> str | None:
    """'hijacked_spam' when the title is gambling/adult spam (the domain now serves someone else);
    'spam_injected' when only the body carries spam (real facility site with injected links)."""
    if SPAM.search(title) or TITLE_SPAM.search(title):
        return "hijacked_spam"
    return "spam_injected" if SPAM.search(text[:3000]) else None


CONSTRUCTION = re.compile(r"(under construction|coming soon|site is under maintenance)", re.I)
PARKING_HOSTS = re.compile(r"(dropcatch|expireddomains|dynadot|sedo|parkingcrew|bodis|afternic|hugedomains|dan\.com|above\.com|parklogic|"
                           r"godaddy\.com|domainmarket|undeveloped)")
SCRIPTS = [("hi_mr", 0x0900, 0x097F), ("bn_as", 0x0980, 0x09FF), ("pa", 0x0A00, 0x0A7F), ("gu", 0x0A80, 0x0AFF),
           ("or", 0x0B00, 0x0B7F), ("ta", 0x0B80, 0x0BFF), ("te", 0x0C00, 0x0C7F), ("kn", 0x0C80, 0x0CFF),
           ("ml", 0x0D00, 0x0D7F)]
SKIP_EXT = re.compile(r"\.(pdf|jpe?g|png|gif|webp|svg|zip|rar|docx?|xlsx?|pptx?|mp4|mp3|avi|css|js|ico|xml)$", re.I)
# keyword groups in order of value to the KB (services and hours before about/contact/doctors)
KEYWORDS = [
    ("specialty", r"special|specialit|department|centres?-of-excellence|centers?-of-excellence|\bcoe\b|clinical-?services"),
    ("services", r"service"),
    ("facilities", r"facilit|infrastructure|amenit"),
    ("emergency", r"emergenc|casualty|trauma|24x7|24-7|ambulance"),
    ("timing", r"timing|\bopd\b|hours|schedule|visiting"),
    ("dialysis", r"dialysis|nephro|kidney"),
    ("maternity", r"maternity|obstetric|gyna?ec|labou?r|delivery|ivf|fertility"),
    ("icu", r"\bn?icu\b|critical|neonat|intensive"),
    ("radiology", r"radiolog|imaging|\bscan|\bmri\b|ct-scan|diagnost|patholog|laborator"),
    ("about", r"about|overview|who-we-are|profile|accredit|nabh|insurance|tpa|cashless"),
    ("contact", r"contact|reach-us|location|find-us|address"),
    ("doctors", r"doctors|our-doctors|consultants|our-team|medical-team|our-experts|faculty"),
]
KW = [(g, re.compile(p, re.I)) for g, p in KEYWORDS]
DOCTOR_PROFILE = re.compile(r"/(dr|doctor)[-_.][a-z]|/doctors?/[a-z0-9-]{6,}/?$|^dr\.?\s", re.I)


def redact(s: str) -> str:
    return PHONE.sub("[phone]", EMAIL.sub("[email]", s))


def lang_of(text: str) -> str:
    """Script-based guess: an Indic script holding 30%+ of letters wins, else 'en'.
    ponytail: Latin script is assumed English (Hinglish counts as en); add a real detector if needed."""
    counts = {k: 0 for k, _, _ in SCRIPTS}
    latin = 0
    for ch in text[:20000]:
        o = ord(ch)
        if ch.isascii():
            latin += ch.isalpha()
            continue
        for k, lo, hi in SCRIPTS:
            if lo <= o <= hi:
                counts[k] += 1
                break
    total = latin + sum(counts.values())
    if total == 0:
        return "none"
    k, v = max(counts.items(), key=lambda kv: kv[1])
    return k if v / total >= 0.3 else "en"


def clean_lines(s: str) -> str:
    lines = [re.sub(r"[ \t\u00a0]+", " ", x).strip() for x in s.splitlines()]
    return "\n".join(dict.fromkeys(x for x in lines if x))


def extract(html: str, base_url: str) -> dict:
    """HTML -> title, boilerplate-stripped main text, header/footer text (hours and 24x7 banners
    often live there), outgoing links, language and site-status hints. All stored text is redacted."""
    tree = HTMLParser(html)
    t = tree.css_first("title")
    title = t.text(strip=True)[:300] if t else ""
    links = []
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if href and not href.startswith(("mailto:", "tel:", "javascript:", "#", "whatsapp:")):
            try:
                links.append((urljoin(base_url, href).split("#")[0], a.text(strip=True)[:120]))
            except ValueError:  # malformed hrefs such as '//[elementor-template]' raise in urljoin
                continue
    for n in tree.css("script, style, noscript, svg, iframe, template"):
        n.decompose()
    chrome = []
    for sel in CHROME_SEL:
        for n in tree.css(sel)[:4]:
            chrome.append(n.text(separator="\n", strip=True))
    main = trafilatura.extract(html, url=base_url, include_tables=True, favor_recall=True,
                               include_comments=False, deduplicate=True) or ""
    fallback = False
    if len(main) < 300:  # trafilatura finds no article on many link-heavy homepages
        body = tree.body
        full = body.text(separator="\n", strip=True) if body else ""
        if len(full) > len(main):
            main, fallback = full, True
    main = clean_lines(main)
    main_set = set(main.splitlines())
    chrome_txt = "\n".join(x for x in clean_lines("\n".join(chrome)).splitlines() if x not in main_set)[:5000]
    probe = f"{title}\n{main[:3000]}"
    spam = spam_verdict(title, main)
    status_hint = ("hijacked_spam" if spam == "hijacked_spam" else
                   "parked_or_for_sale" if PARKED.search(probe) else
                   "suspended_or_expired" if SUSPENDED.search(probe) else
                   "under_construction" if CONSTRUCTION.search(probe) and len(main) < 1500 else None)
    return {"title": redact(title), "text": redact(main), "chrome_text": redact(chrome_txt), "links": links,
            "lang": lang_of(main), "fallback_text": fallback, "status_hint": status_hint,
            "spam_injected": spam == "spam_injected"}


def pick_links(links: list[tuple[str, str]], site: str, n: int, slug: str | None = None) -> list[tuple[str, str]]:
    """Choose up to n same-site links whose URL or anchor matches a keyword group: first one per
    group in KEYWORDS order, then fill by group order. slug (branch targets) restricts to URLs
    containing the branch slug. Individual doctor profile pages are skipped."""
    seen, scored = set(), []
    for url, anchor in links:
        try:
            p = urlparse(url)
            host = re.sub(r"^(www\d?|m)\.", "", (p.hostname or "").lower())
        except ValueError:
            continue
        if p.scheme not in ("http", "https") or host != site or SKIP_EXT.search(p.path) or url in seen:
            continue
        if p.path in ("", "/") or DOCTOR_PROFILE.search(p.path) or DOCTOR_PROFILE.search(anchor):
            continue
        if slug and slug not in url.lower():
            continue
        hay = f"{p.path} {p.query} {anchor}".lower()
        for gi, (g, rx) in enumerate(KW):
            if rx.search(hay):
                seen.add(url)
                scored.append((gi, g, url))
                break
    scored.sort(key=lambda x: x[0])
    first, rest, groups = [], [], set()
    for gi, g, url in scored:
        (rest if g in groups else first).append((url, g))
        groups.add(g)
    return (first + rest)[:n]


if __name__ == "__main__":
    assert redact("Call 98765 43210 or 080-23456789, mail a.b@x.co.in") == "Call [phone] or [phone], mail [email]"
    assert redact("100 beds since 1998, 24x7") == "100 beds since 1998, 24x7"
    assert redact("WhatsApp +91 8447366000.\nCall 9620396203.") == "WhatsApp [phone].\nCall [phone]."
    assert lang_of("Hospital services") == "en" and lang_of("\u0905\u0938\u094d\u092a\u0924\u093e\u0932 hospital") == "hi_mr"
    ls = [("https://[elementor-template id=1]/x", "services"), ("https://www.x.com/about-us", "About"), ("https://x.com/dr-ravi-kumar", "Dr Ravi"),
          ("https://x.com/departments", "Departments"), ("https://y.com/services", "S"),
          ("https://x.com/contact", "Contact"), ("https://x.com/brochure.pdf", "services")]
    assert [u for u, _ in pick_links(ls, "x.com", 5)] == ["https://x.com/departments", "https://www.x.com/about-us",
                                                          "https://x.com/contact"]
    h = "<html><head><title>X Hospital</title></head><body><header>OPD 9am-5pm</header><p>Dialysis unit.</p>" \
        "<a href='//[elementor x]'>Services</a><a href='/departments'>Departments</a><footer>24x7 Emergency 9876543210</footer></body></html>"
    e = extract(h.replace("<header>", "<header><script>var a=1;</script>"), "https://x.com/")
    assert "var a" not in e["chrome_text"]
    assert e["title"] == "X Hospital" and "Dialysis" in e["text"] and "[phone]" in (e["text"] + e["chrome_text"])
    assert e["links"][0][0] == "https://x.com/departments" and e["status_hint"] is None
    assert extract("<title>This domain is for sale</title>", "https://z.com/")["status_hint"] == "parked_or_for_sale"
    assert extract("<title>Netra Nidan Eye Hospital</title><p>netranidan.com</p>", "https://z.com/")["status_hint"] is None
    assert extract("<title>API777: Login Situs Slot777 & Link Slot Gacor</title>", "https://z.com/")["status_hint"] == "hijacked_spam"
    assert spam_verdict("Aviator Game - Play for Real Money", "") == "hijacked_spam"
    assert spam_verdict("JSS Ayurveda Hospital", "Panchakarma ... best casino sites") == "spam_injected"
    assert spam_verdict("Casino Road Hospital Kochi", "")  # ponytail: known false positive class, title-level
    print("extract.py self-check ok")
