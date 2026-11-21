"""Parse the LaQshya master PDF (via `pdftotext -tsv` word boxes) into a flat table.

Usage: python -I parse.py <words.tsv> <out.parquet>

The PDF is an XLSX printout with fixed column x positions on every page. Cells that
wrap are bottom-aligned, so a row owns every word whose top lies between the previous
row's date line and its own date line. Text that overflows a column is either glued to
the next word (camelCase split) or sits in the neighbour column (moved back by type).
"""
import csv
import re
import sys

import pandas as pd

# Column left edges in PDF points, identical on all 70 pages (checked by value_counts).
COLS = [("sno", 0), ("state", 80), ("district", 163), ("ftype", 232), ("name", 261),
        ("dept", 421), ("certified", 488), ("conditional", 520), ("date_result", 563),
        ("date_validity", 620)]
DEPT_WORDS = {"labour", "room", "maternity", "ot"}
TYPE_WORDS = {"DH", "SDH", "CHC", "MC", "PHC", "FRU", "UPHC", "AH", "GH", "CH", "MCH", "SH",
              "WH", "DWH", "THQ", "CHC/FRU", "UCHC"}
DATE = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def col_of(x):
    name = COLS[0][0]
    for c, left in COLS:
        if x >= left - 1:
            name = c
    return name


def split_glued(text, left, width):
    """'PradeshEast' starting in one column and crossing the next column edge -> two words."""
    right = left + width
    crosses = [l for _, l in COLS if left + 2 < l - 1 < right]
    m = re.search(r"(?<=[a-z\)])(?=[A-Z])", text)
    if crosses and m:
        # The tail is the text that spilled over the first crossed edge.
        return [(text[:m.start()], left), (text[m.start():], crosses[0])]
    return [(text, left)]


def build_rows(words):
    rows = []
    for page, p in words.groupby("page_num"):
        p = p[p.top > (110 if page == 1 else 40)]
        anchors = sorted(p[(p.left > 560) & (p.left < 570) & p.text.str.match(DATE)].top)
        prev = -1.0
        for a in anchors:
            band = p[(p.top > prev + 1) & (p.top <= a + 1)].sort_values(["top", "left"])
            prev = a
            cells = {c: [] for c, _ in COLS}
            for t, l, w in zip(band.text, band.left, band.width):
                for piece, pl in split_glued(t, l, w):
                    cells[col_of(pl)].append(piece)
            # Overflow repair: name text spilling into dept, district text into type.
            spill = [x for x in cells["dept"] if x.lower() not in DEPT_WORDS]
            cells["dept"] = [x for x in cells["dept"] if x.lower() in DEPT_WORDS]
            cells["name"] += spill
            spill = [x for x in cells["ftype"] if x.upper() not in TYPE_WORDS]
            cells["ftype"] = [x for x in cells["ftype"] if x.upper() in TYPE_WORDS]
            cells["district"] += spill
            rec = {c: " ".join(v).strip() for c, v in cells.items()}
            rec["page"] = int(page)
            rows.append(rec)
    return pd.DataFrame(rows)


def main(tsv, out):
    w = pd.read_csv(tsv, sep="\t", quoting=csv.QUOTE_NONE, keep_default_na=False)
    w = w[w.level == 5]
    df = build_rows(w)
    df["sno"] = pd.to_numeric(df.sno, errors="coerce").astype("Int64")
    df["status"] = df.apply(lambda r: "Certified" if r.certified else ("Conditional" if r.conditional else None), axis=1)
    for c in ("date_result", "date_validity"):
        df[c] = pd.to_datetime(df[c], format="%d/%m/%Y", errors="coerce")
    df = df.drop(columns=["certified", "conditional"])
    assert len(df) == 2173, len(df)
    assert df.sno.tolist() == list(range(1, 2174)), "serials not contiguous"
    df.to_parquet(out, index=False)
    print(len(df), "rows ->", out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
