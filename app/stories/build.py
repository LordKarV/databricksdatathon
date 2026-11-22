"""Build the 'Data stories' page data (issue #53): app/stories/out/stories.json and its charts.

Everything on the page is copied from viz/gallery.json: headline, presenter line, caveat,
verification note, chart alt text and the data CSV paths. No number is typed here or in the page.
The build fails if a chart named by the gallery is missing. A data CSV that is not in the checkout
is kept with in_repo = false and listed under missing_data_files: the page then names the file
without linking to it, so it never links to something that is not in the repo.

Charts are copied as SVG to app/stories/out/charts/<story id>_<n>.svg and served through an
allowlist (the names in stories.json). The page shows them with <img>, so nothing inside an SVG
can run.

Run from the repo root:
    python app/stories/build.py
Standard library only.
"""
from __future__ import annotations

import ast
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GALLERY = "viz/gallery.json"
OUT = Path(__file__).resolve().parent / "out"
REPO_URL = "https://github.com/LordKarV/databricksdatathon/blob/main/"
# The model_ stories describe the v1 prototype model (its sealed test and AUROC); the v2 TEST in the notebook
# supersedes them, so the page leaves them out rather than show two contradicting results.
SUPERSEDED_PREFIX = "model_"
TEXT_FIELDS = ("id", "act", "theme", "headline", "presenter_line", "caveat", "verification")


def as_list(value) -> list[str]:
    """gallery.json stores some lists as their Python repr; accept a list, that repr, or one path."""
    if isinstance(value, list):
        return [str(x) for x in value]
    text = str(value or "").strip()
    if text.startswith("["):
        return [str(x) for x in ast.literal_eval(text)]
    return [text] if text else []


def main() -> None:
    gallery = json.loads((ROOT / GALLERY).read_text(encoding="utf-8"))
    charts_dir = OUT / "charts"
    if OUT.exists():
        shutil.rmtree(OUT)
    charts_dir.mkdir(parents=True)
    stories, problems, missing_data, total = [], [], [], 0
    for s in sorted(gallery["stories"], key=lambda x: int(x["order"])):
        if s["id"].startswith(SUPERSEDED_PREFIX):
            continue
        missing = [k for k in TEXT_FIELDS if not str(s.get(k, "")).strip()]
        if missing:
            problems.append(f"{s.get('id')}: empty field(s) {missing}")
        charts = []
        for n, c in enumerate(s["charts"], start=1):
            src = ROOT / c["svg"]
            if not src.is_file():
                problems.append(f"{s['id']}: chart not found: {c['svg']}")
                continue
            if not str(c.get("alt_text", "")).strip():
                problems.append(f"{s['id']}: chart {c['svg']} has no alt text")
            name = f"{s['id']}_{n}.svg"
            shutil.copyfile(src, charts_dir / name)
            total += src.stat().st_size
            charts.append({"file": name, "source": c["svg"], "alt_text": c["alt_text"]})
        csvs = [{"path": p, "in_repo": (ROOT / p).is_file()} for p in as_list(s.get("data_csv"))]
        missing_data += [f"{s['id']}: {c['path']}" for c in csvs if not c["in_repo"]]
        if not csvs:
            problems.append(f"{s['id']}: no data file")
        stories.append({**{k: str(s[k]) for k in TEXT_FIELDS if k in s}, "order": int(s["order"]), "charts": charts,
                        "data_csv": csvs, "script": str(s.get("script", ""))})
    if problems:
        sys.exit("stories build failed:\n  " + "\n  ".join(problems))
    acts = []
    for s in stories:
        if s["act"] not in acts:
            acts.append(s["act"])
    doc = {"built_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "source": GALLERY,
           "gallery_built": gallery.get("built"), "narrative": gallery.get("narrative"), "repo_url": REPO_URL,
           "acts": acts, "missing_data_files": missing_data, "stories": stories}
    (OUT / "stories.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    n_charts = sum(len(s["charts"]) for s in stories)
    print(f"wrote app/stories/out/stories.json: {len(stories)} stories, {n_charts} charts ({total / 1e6:.1f} MB of SVG), "
          f"{len(acts)} acts")
    if missing_data:
        print(f"warning: {len(missing_data)} data file(s) named by the gallery are not in this checkout "
              f"(shown on the page without a link):")
        for m in missing_data:
            print("  " + m)


if __name__ == "__main__":
    main()
