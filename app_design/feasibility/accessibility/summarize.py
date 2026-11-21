"""Print a markdown summary of outputs/results.json (pasted into REPORT.md)."""
import json
from pathlib import Path

r = json.loads((Path(__file__).resolve().parent / "outputs" / "results.json").read_text())


def kb(b):
    return f"{b / 1024:,.0f}" if b >= 10240 else f"{b / 1024:,.1f}"


print("| page | requests | transfer KB | decoded KB | repeat-visit KB | ready no throttle s | ready slow 4G s | ready 2G s | external hosts |")
print("|---|---|---|---|---|---|---|---|---|")
for n, v in r.items():
    a = v["none"]
    fv = a["first_visit"]
    ext = [h for h in fv["hosts"] if not h.startswith("localhost") and h != "data:"]
    cell = lambda p: str(v[p].get("main_action_visible_s", v[p].get("error", "?")))  # noqa: E731
    print(f"| {n} | {fv['requests']} | {kb(fv['transfer_bytes'])} | {kb(fv['decoded_bytes'])} | "
          f"{kb(a['repeat_visit']['transfer_bytes'])} | {a['main_action_visible_s']} | {cell('slow4g')} | "
          f"{cell('2g')} | {', '.join(ext) or '-'} |")

print()
print("| page | lang | geolocation | camera | axe violations (impact x nodes) | targets < 24 px | targets < 44 px |")
print("|---|---|---|---|---|---|---|")
for n, v in r.items():
    f = v["none"]["features"]
    viol = "; ".join(f"{x['id']} ({x['impact']} x{x['nodes']})" for x in f["axe_violations"]) or "none"
    cam = "-"
    if "video_elements" in f:
        cam = f"video={f['video_elements']} file-image={f['image_file_inputs']} capture={f['file_inputs_with_capture']}"
    geo = f.get("geolocation", "-")
    small = lambda key: ", ".join(f"{t['tag']}:{t['name'] or t['type'] or '?'} {t['w']}x{t['h']}" for t in f[key]) or "none"  # noqa: E731
    print(f"| {n} | {f['html_lang']} | {geo} | {cam} | {viol} | {small('targets_under_24px')} | {small('targets_under_44px')} |")
