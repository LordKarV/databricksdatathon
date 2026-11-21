# Debug helper: Gradio writes the js= result into a textarea value, which get_by_text cannot see.
import subprocess
from playwright.sync_api import sync_playwright
from measure import TARGETS, wait_port, BENGALURU
t = TARGETS["gradio_probe"]
p = subprocess.Popen(t["cmd"], cwd="apps", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    wait_port(7860, t["url"])
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_context(geolocation=BENGALURU, permissions=["geolocation"]).new_page()
        page.goto(t["url"])
        page.get_by_role("button", name="Use my location").click()
        page.wait_for_timeout(3000)
        print("textarea value:", page.get_by_label("Location").input_value())
        print("html lang:", page.evaluate("document.documentElement.lang"))
        b.close()
finally:
    p.terminate()
