"""Parse the MoHFW 196 trauma care facility (TCF) list into a table.

Usage: python -I parse.py SOURCE_PDF BRIEF_PDF OUT_CSV

SOURCE_PDF is "List of Trauma Care.pdf" (Annexure-I, 196 rows: state, name, Rs crore).
BRIEF_PDF is the 2019 NPPMTBI programme brief; its Annexures 2 and 3 give the level and
functionality status per TCF. The state column in SOURCE_PDF is a vertically merged
cell, so the state for each serial-number range is hand-coded below from reading the
PDF and cross-checked against the brief's state headings.
"""
import re
import subprocess
import sys

import pandas as pd
from rapidfuzz import fuzz

# Serial-number ranges per state, read off the PDF (merged cells).
STATE_RANGES = [
    (1, 14, "Andhra Pradesh"), (15, 15, "Andaman and Nicobar Islands"),
    (16, 19, "Arunachal Pradesh"), (20, 26, "Assam"), (27, 35, "Bihar"),
    (36, 41, "Chhattisgarh"), (42, 42, "Dadra and Nagar Haveli"), (43, 43, "Goa"),
    (44, 58, "Gujarat"), (59, 61, "Haryana"), (62, 67, "Himachal Pradesh"),
    (68, 71, "Jammu and Kashmir"), (72, 75, "Jharkhand"), (76, 83, "Karnataka"),
    (84, 89, "Kerala"), (90, 90, "Ladakh"), (91, 95, "Madhya Pradesh"),
    (96, 101, "Maharashtra"), (102, 107, "Manipur"), (108, 110, "Meghalaya"),
    (111, 117, "Mizoram"), (118, 122, "Nagaland"), (123, 128, "Odisha"),
    (129, 133, "Punjab"), (134, 143, "Rajasthan"), (144, 147, "Sikkim"),
    (148, 160, "Tamil Nadu"), (161, 164, "Telangana"), (165, 169, "Tripura"),
    (170, 182, "Uttar Pradesh"), (183, 186, "Uttarakhand"), (187, 196, "West Bengal"),
]
STATE_WORDS = {w for _, _, s in STATE_RANGES for w in s.split()} | {
    "Andaman", "&", "Nikobar", "Dadar", "Kashmir", "Jammu"}

# Unit costs from the brief's Annexure-1 (Rs crore). 6.1632 and 2.9652 are exactly 60%
# of the 12th-plan L-II and L-III costs (seen only for Bihar, Jharkhand, Panipat, Kutch,
# Thane, Nizamabad, Meerut); 8.772 (Gangtok) matches no unit cost.
AMOUNT_LEVEL = {15.93: "I", 17.132: "I", 9.63: "II", 10.272: "II", 6.1632: "II",
                4.775: "III", 4.942: "III", 2.9652: "III"}
AMOUNT_PLAN = {15.93: "11th", 9.63: "11th", 4.775: "11th",
               17.132: "12th", 10.272: "12th", 4.942: "12th"}

ROW = re.compile(r"^\s*(\d{1,3})\s{2,}(\S.*?)\s{2,}(\d+\.\d+)\s*$")
NUM_ONLY = re.compile(r"^\s*(\d{1,3})\s+(\d+\.\d+)\s*$")


def pdf_lines(path):
    out = subprocess.run(["pdftotext", "-layout", path, "-"], check=True,
                         capture_output=True, text=True).stdout
    return out.splitlines()


def strip_state(text):
    """Drop state-label words that pdftotext put on the same line as a name."""
    m = re.match(r"^(\S.*?)\s{3,}(\S.*)$", text)
    if m and all(w in STATE_WORDS for w in m.group(1).split()):
        return m.group(2)
    return text


def parse_main(path):
    lines = pdf_lines(path)
    rows = []
    for i, ln in enumerate(lines):
        m = ROW.match(ln)
        if m:
            rows.append((int(m.group(1)), strip_state(m.group(2).strip()), float(m.group(3))))
            continue
        m = NUM_ONLY.match(ln)  # name wrapped onto the lines above and below
        if m:
            above = strip_state(lines[i - 1].strip())
            below = lines[i + 1].strip()
            rows.append((int(m.group(1)), f"{above} {below}", float(m.group(2))))
    df = pd.DataFrame(rows, columns=["sno", "name", "amount_cr"])
    state = {n: s for a, b, s in STATE_RANGES for n in range(a, b + 1)}
    df["state"] = df.sno.map(state)
    df["level_from_amount"] = df.amount_cr.map(AMOUNT_LEVEL)
    df["plan_from_amount"] = df.amount_cr.map(AMOUNT_PLAN)
    return df


BRIEF_LEVEL = re.compile(r"^\s*(\d{1,3})?\.?\s*(\S.*?)\s{2,}(?:L-\s?)?(III|II|I)\.?\s*(Functional)?\s*$")


def parse_brief(path):
    """Return (name_fragment, level, status) rows from the brief's Annexures 2 and 3."""
    section, rows = None, []
    for ln in pdf_lines(path):
        if "CONSTRUCTION COMPLETED" in ln:
            section = "11th plan: construction completed"
        elif "UNDER CONSTRUCTION" in ln:
            section = "11th plan: under construction"
        elif "CONSTRUCTION NOT YET STARTED" in ln:
            section = "11th plan: construction not started"
        elif "supported during 12th FYP" in ln:
            section = "12th plan: supported (none functional as of 2019)"
        if section is None:
            continue
        m = BRIEF_LEVEL.match(ln)
        if m and not ln.strip().startswith(("S. No", "Sl. No")):
            name = strip_state(m.group(2).strip())
            status = "functional (2019)" if m.group(4) else section
            rows.append((name, m.group(3), status))
    return pd.DataFrame(rows, columns=["brief_name", "brief_level", "brief_status"])


def attach_brief(df, brief):
    """One-to-one fuzzy assignment of brief rows to TCF rows, best scores first.

    Brief names are often fragments (wrapped cells), so a fragment like "Govt. General
    Hospital & Medical College," matches several TCFs; greedy one-to-one assignment
    plus a plan filter (11th-plan sections only match 11th-plan amounts) resolves it.
    """
    pairs = []
    for bi, b in brief.iterrows():
        is12 = b.brief_status.startswith("12th")
        for ti, t in df.iterrows():
            if t.plan_from_amount is not None and pd.notna(t.plan_from_amount) and (t.plan_from_amount == "12th") != is12:
                continue
            sc = fuzz.token_set_ratio(b.brief_name, re.sub(r"^DH ", "District Hospital, ", t["name"]))
            if sc >= 80:
                pairs.append((sc, fuzz.ratio(b.brief_name, t["name"]), bi, ti))
    used_b, used_t, rows = set(), set(), {}
    for sc, _, bi, ti in sorted(pairs, reverse=True):
        if bi in used_b or ti in used_t:
            continue
        used_b.add(bi), used_t.add(ti)
        b = brief.loc[bi]
        rows[ti] = (b.brief_level, b.brief_status, b.brief_name, round(sc))
    add = pd.DataFrame.from_dict(rows, orient="index",
                                 columns=["brief_level", "brief_status", "brief_name", "brief_score"])
    unmatched = brief.drop(index=list(used_b))
    if len(unmatched):
        print("brief rows not assigned:")
        print(unmatched.to_string())
    return df.join(add)


def main(src, brief_pdf, out_csv):
    df = parse_main(src)
    assert df.sno.tolist() == list(range(1, 197)), "expected serials 1..196"
    assert df.state.notna().all()
    df = attach_brief(df, parse_brief(brief_pdf))
    df["level"] = df.brief_level.fillna(df.level_from_amount)
    df.to_csv(out_csv, index=False)
    print(f"rows {len(df)}; brief-matched {df.brief_level.notna().sum()}")
    print(df.level.value_counts(dropna=False).to_string())
    bad = df[df.brief_level.notna() & df.level_from_amount.notna() & (df.brief_level != df.level_from_amount)]
    print("level disagreements (brief vs amount):")
    print(bad[["sno", "name", "amount_cr", "level_from_amount", "brief_level"]].to_string())


if __name__ == "__main__":
    main(*sys.argv[1:4])
