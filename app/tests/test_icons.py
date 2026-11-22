"""ICON-1: the manifest lists the three home-screen icons, each file exists at its declared size, and the server
serves every icon file with the right type. Kept off the sw.js SHELL so the icons never weigh on first paint."""
import json
import struct
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import STATIC, app

client = TestClient(app)


def png_size(path: Path) -> tuple[int, int]:
    """Width and height from the IHDR chunk, so the test needs no image library."""
    head = path.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR", path.name
    return struct.unpack(">II", head[16:24])


def test_manifest_lists_three_icons_at_declared_sizes():
    icons = json.loads((STATIC / "manifest.webmanifest").read_text())["icons"]
    assert [(i["src"], i["sizes"], i["purpose"]) for i in icons] == [
        ("/icon-192.png", "192x192", "any"), ("/icon-512.png", "512x512", "any"),
        ("/icon-512-maskable.png", "512x512", "maskable")]
    for i in icons:
        assert i["type"] == "image/png"
        w, h = png_size(STATIC / i["src"].lstrip("/"))
        assert f"{w}x{h}" == i["sizes"], i["src"]


def test_apple_touch_icon_link_and_file():
    html = (STATIC / "index.html").read_text()
    assert html.count('<link rel="apple-touch-icon" href="/icon-180.png">') == 1
    assert png_size(STATIC / "icon-180.png") == (180, 180)


def test_icons_served_with_types_and_not_in_shell():
    for path, ctype in [("/icon.svg", "image/svg+xml"), ("/icon-180.png", "image/png"), ("/icon-192.png", "image/png"),
                        ("/icon-512.png", "image/png"), ("/icon-512-maskable.png", "image/png")]:
        r = client.get(path)
        assert r.status_code == 200 and r.headers["content-type"].startswith(ctype), path
    assert "'/icon" not in (STATIC / "sw.js").read_text().split("const SHELL", 1)[1].split("];", 1)[0]
