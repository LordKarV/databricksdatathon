"""Parse fetched PMNDP pages into CSVs. Usage: python -I parse.py <data_dir>

Writes <data_dir>/pmndp_state_counts.csv (NHSRC table joined to the PMNDP portal map data)
and <data_dir>/goa_pmndp_centres_2020.csv (8 centres, no phones/e-mails/officer names).
"""
import csv
import html
import re
import sys
from pathlib import Path

D = Path(sys.argv[1])


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def norm_state(s):
    s = clean(s).lower().replace("&", " and ").replace("lsland", "island")
    s = re.sub(r"[^a-z ]", " ", s)
    s = re.sub(r"\b(the|of|national capital territory|nct)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    aliases = {"a and n island": "andaman and nicobar islands", "a and n islands": "andaman and nicobar islands",
               "andaman and nicobar": "andaman and nicobar islands", "orissa": "odisha",
               "tamilnadu": "tamil nadu", "j and k": "jammu and kashmir", "pondicherry": "puducherry",
               "dnh and dd": "dadra and nagar haveli and daman and diu",
               "d and n haveli and daman and diu": "dadra and nagar haveli and daman and diu"}
    return aliases.get(s, s)


def num(s):
    m = re.search(r"\d+", s or "")
    return int(m.group()) if m else None


def nhsrc_rows():
    h = (D / "map_table.html").read_text(errors="replace")
    body = h[h.find("<tbody"):h.find("</tbody>")]
    for tr in re.findall(r"<tr.*?</tr>", body, re.S):
        tds = [clean(t) for t in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(tds) == 5:
            yield {"state_raw": tds[0], "state_key": norm_state(tds[0]), "nhsrc_total_districts": num(tds[1]),
                   "nhsrc_functional_districts": num(tds[2]), "nhsrc_functional_centres": num(tds[3]),
                   "nhsrc_mode": tds[4]}


def portal_rows():
    s = (D / "js" / "settings.js").read_text(errors="replace")
    out = {}
    for m in re.finditer(r'"name": "(<div class=.map-point.*?)",\s*\n', s):
        cells = [clean(c) for c in re.findall(r"<(?:div|td)[^>]*>(.*?)</(?:div|td)>", m.group(1), re.S)]
        cells = [c for c in cells if c]
        kv = dict(zip(cells[1::2], cells[2::2]))
        out[norm_state(cells[0])] = {
            "portal_mode": cells[2],  # label text varies per state, value is always the 2nd cell
            "portal_total_districts": num(kv.get("Total No. of Districts")),
            "portal_aspirational_districts": kv.get("No. of Aspirational Districts"),
            "portal_functional_districts": num(kv.get("No. of Districts (where Dialysis services are functional)")),
            "portal_functional_centres": num(kv.get("Total No. of functional Dialysis centers")),
            "portal_machines": num(kv.get("Total No. of functional Dialysis Machines")),
        }
    return out


# Transcribed by hand from pdftotext output of the 3-page PDF, status as on 29/06/2020). Contact columns dropped.
GOA = [
    ("South Goa", "Hospicio Hospital", "Hospicio Hospital, Margao Goa", "403601"),
    ("South Goa", "CHC Canacona", "CHC Canacona, Canacona Goa", "403709"),
    ("South Goa", "PHC Navelim", "Navelim Salcette Goa", "403707"),
    ("South Goa", "PHC Balli", "Goa Cavorem Balli Village", "403703"),
    ("South Goa", "SDH Ponda", "St. Cruz Tisk Ponda, Mardangad, Ponda Goa", "403401"),
    ("North Goa", "District Hospital Mapusa", "1st floor Dialysis Unit, Alto Duler, Padem, Mapusa, Goa", "403507"),
    ("North Goa", "CHC Valpoi", "Valpoi Sattari Goa, North Goa", "403703"),  # PIN as printed; Valpoi is usually 403506
    ("North Goa", "Goa Medical College", "Goa Medical College, Bambolim Goa", "403202"),
]


def write(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
        w.writeheader()
        w.writerows(rows)


def main():
    portal = portal_rows()
    rows = [{**r, **portal.get(r["state_key"], {})} for r in nhsrc_rows()]
    missing = [r["state_key"] for r in rows if r["state_key"] not in portal]
    assert len(rows) == 36, len(rows)
    write(D / "pmndp_state_counts.csv", rows)
    goa_pins = set((D / "state_lists" / "goa_pins.txt").read_text().split())
    assert {p for *_, p in GOA} == goa_pins, f"Goa PDF PINs changed; re-transcribe: {goa_pins}"
    write(D / "goa_pmndp_centres_2020.csv",
          [{"state": "Goa", "district": d, "centre_name": n, "address": a, "pincode": p,
            "status_as_on": "2020-06-29", "source_url": "https://nhm.goa.gov.in/wp-content/uploads/2020/07/PMNDP-List-of-centres.pdf"}
           for d, n, a, p in GOA])
    print(f"states={len(rows)} unmatched_to_portal={missing} portal_states={len(portal)}")
    print("nhsrc centres sum", sum(r["nhsrc_functional_centres"] or 0 for r in rows),
          "portal centres sum", sum(r.get("portal_functional_centres") or 0 for r in rows))


if __name__ == "__main__":
    main()
