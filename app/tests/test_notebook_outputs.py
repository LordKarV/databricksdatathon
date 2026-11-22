"""The committed submission notebooks never show a placeholder to a judge (WS5 5e, #140)."""
import json
import re
from pathlib import Path

import pytest

NOTEBOOKS = sorted((Path(__file__).resolve().parents[2] / "submission").glob("*.ipynb"))
PLACEHOLDER = re.compile(r"pending|not in this version", re.I)


def output_text(nb: dict) -> list[tuple[int, str]]:
    """(cell index, text) for every stream, result and error output of every code cell."""
    out = []
    for i, cell in enumerate(nb["cells"]):
        for o in cell.get("outputs", []):
            parts = [o.get("text", ""), o.get("evalue", ""), *o.get("traceback", [])]
            for mime, v in o.get("data", {}).items():
                if mime.startswith("text/"):
                    parts.append(v)
            out.append((i, "".join("".join(p) if isinstance(p, list) else p for p in parts)))
    return out


def test_notebooks_exist():
    assert NOTEBOOKS, "no submission notebooks found"


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.name)
def test_no_placeholder_in_outputs(path):
    hits = [(i, PLACEHOLDER.search(t).group(0)) for i, t in output_text(json.loads(path.read_text()))
            if PLACEHOLDER.search(t)]
    assert not hits, f"{path.name}: placeholder text in outputs of cells {hits}"
