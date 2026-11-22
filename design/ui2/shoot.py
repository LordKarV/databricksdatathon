"""Screenshots and axe for the UI2 prototype. Serve design/ui2/prototype, then: python shoot.py <base_url> <out_dir> <axe.min.js>"""
import json, sys
from playwright.sync_api import sync_playwright

BASE, OUT, AXE = sys.argv[1], sys.argv[2], open(sys.argv[3]).read()
SCREENS = [("chooser", "#/lang"), ("home", "#/"), ("answer_trauma", "#/plan/trauma"), ("answer_dialysis", "#/plan/dialysis"),
           ("why_trauma", "#/why/trauma/1"), ("settings", "#/settings"), ("offline_trauma", "#/offline/trauma")]
RUNS = [(n, h, l, "light", 100, 360) for n, h in SCREENS for l in ("en", "hi")]
RUNS += [(n, h, l, "dark", 100, 360) for n, h in SCREENS for l in ("en", "hi")]
RUNS += [("answer_trauma", "#/plan/trauma", l, "light", 150, 360) for l in ("en", "hi")]
RUNS += [("why_trauma", "#/why/trauma/1", l, "light", 150, 360) for l in ("en", "hi")]
RUNS += [(n, h, "en", "light", 100, 1280) for n, h in SCREENS if n in ("home", "answer_trauma", "why_trauma")]
RUNS += [(n, h, "hi", "light", 100, 1280) for n, h in SCREENS if n in ("answer_trauma",)]
report = []
with sync_playwright() as p:
    b = p.chromium.launch()
    for name, hash_, lang, theme, size, w in RUNS:
        ctx = b.new_context(viewport={"width": w, "height": 800}, device_scale_factor=1, reduced_motion="reduce",
                            color_scheme=theme, locale="hi-IN" if lang == "hi" else "en-IN")
        pg = ctx.new_page()
        q = f"?lang={lang}&size={size}&theme={theme}" if name != "chooser" else f"?size={size}&theme={theme}"
        if name == "chooser":
            pg.add_init_script(f"Object.defineProperty(navigator, 'language', {{get: () => '{'hi-IN' if lang == 'hi' else 'en-IN'}'}})")
        pg.goto(f"{BASE}/index.html{q}{hash_}")
        pg.on("pageerror", lambda e: print("PAGEERROR", name, e)); pg.wait_for_selector("#main h1", state="attached")
        pg.evaluate("document.fonts.ready")
        pg.wait_for_timeout(250)
        height = pg.evaluate("document.documentElement.scrollHeight")
        hscroll = pg.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
        fname = f"{name}-{lang}-{theme}-{w}" + (f"-text{size}" if size != 100 else "") + ".png"
        pg.screenshot(path=f"{OUT}/{fname}", full_page=True)
        pg.add_script_tag(content=AXE)
        res = pg.evaluate("""async () => { const r = await axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa','best-practice']}, rules: {'color-contrast-enhanced': {enabled: true}}});
            return r.violations.map(v => ({id: v.id, impact: v.impact, n: v.nodes.length, t: v.nodes.slice(0,3).map(x => x.target.join(' ') + ' :: ' + (x.failureSummary||'').slice(0,160))})); }""")
        # small targets: interactive elements under 48 px in either direction
        small = pg.evaluate("""() => [...document.querySelectorAll('a[href], button, input, select, summary, label:has(input)')].filter(e => {
            const r = e.getBoundingClientRect(); if (!r.width || e.closest('.vh') || e.matches('input[type=radio], input[type=checkbox]') && e.closest('label')) return false;
            if (e.matches('.seg input')) return false; return r.height < 47.5 || r.width < 47.5; }).map(e => e.tagName + '.' + e.className + ' ' + e.textContent.trim().slice(0,30) + ' ' + Math.round(e.getBoundingClientRect().width) + 'x' + Math.round(e.getBoundingClientRect().height))""")
        report.append({"file": fname, "height": height, "hscroll": hscroll, "axe": res, "small_targets": small})
        print(fname, height, "HSCROLL" if hscroll else "", [(v["id"], v["n"]) for v in res], small[:4])
        ctx.close()
    b.close()
json.dump(report, open(f"{OUT}/axe_report.json", "w"), indent=1, ensure_ascii=False)
