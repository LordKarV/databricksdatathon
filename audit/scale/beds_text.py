"""Extract facility-level bed counts from description/capability/procedure/equipment text.

Each JSON item (or description sentence) is one claim. A bed number counts as a facility
total only when the clause around it has no unit/department keyword and the claim has no
chain/future keyword, because "10-bed ICU", "7,600 beds in 27 hospitals" and "expansion to
1000 beds" describe something other than this facility's current capacity.
"""
import re
from common import jlist

BED_RX = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)\s*(?:-|\s)?\s*(?:bed(?:s|ded)?)\b", re.I)
UNIT_RX = re.compile(
    r"\b(n?icu|picu|sicu|micu|nsicu|cvtu|iccu|ccu|hdu|icus|intensive|critical|dialysis|ward|wards|unit|units|"
    r"department|dept|emergency|casualty|trauma|labou?r|maternity|private|room|rooms|burns?|isolation|"
    r"theatre|nursery|daycare|day[- ]care|oncology|cancer|wing|block|cabin|suite|recovery|post[- ]?op|"
    r"medicine|surgery|pediatrics|paediatrics|orthopedics|obg|gynae|chemo|observation|transplant|"
    r"step[- ]down|covid|ventilator|stroke|rehab|psychiatric|deaddiction|de-addiction|neonatal|nicu|"
    r"general|semi|special|deluxe|cardiac|ot|sncu|picu|kmc|ayush|tb|leprosy|eye|dental|chairs?)\b",
    re.I,
)
SCOPE_RX = re.compile(
    r"\b(hospitals|network|group of|chain|across|centres|centers|branches|upgrade|expand|expansion|"
    r"proposed|planned|potential|will|scope|under construction|upcoming|campus has|sister)\b",
    re.I,
)
CUT_BEFORE = re.compile(r"[,;.]|\band\b|\bincluding\b|\bplus\b", re.I)
CUT_AFTER = re.compile(r"[,;.()]|\band\b|\bwith\b|\bincluding\b|\bplus\b", re.I)
# past or superseded capacity: "had 513 beds in 1930", "inaugurated in 1975 with 50 beds"
HIST_RX = re.compile(
    r"\b(had|inaugurated|started|commenced|initially|originally|began|extension of|increased|"
    r"upgraded from|from \d+ beds?|beds? in (?:18|19)\d\d|earlier|formerly|previously|plans?|planning|adding|"
    r"(?:founded|established|set up|started) in \d{4} (?:as|with))\b",
    re.I,
)


def claims(row):
    for f in ("capability", "procedure", "equipment"):
        for s in jlist(row[f]):
            yield f, s
    for s in re.split(r"(?<=[.;])\s+", row["description"] or ""):
        yield "description", s


def _clause(s, m):
    before = s[: m.start()]
    cuts = list(CUT_BEFORE.finditer(before))
    before = before[cuts[-1].end():] if cuts else before
    after = s[m.end():]
    c = CUT_AFTER.search(after)
    after = after[: c.start()] if c else after
    return before[-40:] + m.group(0) + after[:40]


def bed_mentions(row):
    """List of (field, number, is_total_candidate, claim_text)."""
    out = []
    for f, s in claims(row):
        scoped = bool(SCOPE_RX.search(s) or HIST_RX.search(s))
        for m in BED_RX.finditer(s):
            n = int(m.group(1).replace(",", ""))
            total = not scoped and not UNIT_RX.search(_clause(s, m))
            out.append((f, n, total, s))
    return out


if __name__ == "__main__":
    class R(dict):
        __getitem__ = dict.get
    t = lambda s: [(n, tot) for _, n, tot, _ in bed_mentions(R(capability='["%s"]' % s, description=""))]
    assert t("Has 50 beds, including 4 ICU beds") == [(50, True)]  # "4 ICU beds" is not matched: number must touch "bed"
    assert t("Has a 10-bed ICU") == [(10, False)]
    assert t("7,600 beds in 27 hospitals") == [(7600, False)]
    assert t("Bed capacity of 670 beds with potential expansion to 1000 beds") == [(670, False), (1000, False)]
    assert t("300-bed tertiary care hospital") == [(300, True)]
    assert t("Neonatal ICU with 13 beds") == [(13, False)]
    assert t("Had 513 beds in 1930") == [(513, False)]
    assert t("Was established in 1987 as a 40-bed hospital") == [(40, False)]
    assert t("Plans a 300-bed super multi-specialty hospital") == [(300, False)]
    assert t("Khirpai Rural Hospital, with 30 beds at Khirpai") == [(30, True)]
    print("ok")
