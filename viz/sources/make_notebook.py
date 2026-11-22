"""Build notebook.py (Databricks source format) from _common.py and the six story scripts.

The story scripts stay the single source of truth; lines tagged NOTEBOOK-SKIP are dropped because the
config cell already defines everything they import. Run: .venv-viz/bin/python make_notebook.py
"""
from pathlib import Path

HERE = Path(__file__).parent
STORIES = ["s1_composition", "s2_simpson", "s3_paraphrase", "s4_vectors", "s5_reachability", "s6_shrinkage"]
SEP = "\n\n# COMMAND ----------\n\n"

cells = ["# MAGIC %md\n# MAGIC # Who said so? Source stories\n# MAGIC Six charts on where the facility records' "
         "evidence comes from. Each cell writes a PNG, SVG, alt-text TXT and tidy CSV to `OUT`. "
         "Story notes: `viz/sources/STORIES.md`.",
         "# Config: inputs come from local parquet unless UC_SCHEMA is set.\n" + (HERE / "_common.py").read_text()]
for s in STORIES:
    body = [l for l in (HERE / f"{s}.py").read_text().splitlines() if "NOTEBOOK-SKIP" not in l]
    cells.append("\n".join(body).strip())
(HERE / "notebook.py").write_text("# Databricks notebook source\n" + SEP.join(cells) + "\n")
print(f"wrote notebook.py with {len(cells)} cells")
