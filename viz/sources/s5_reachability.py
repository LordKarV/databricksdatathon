# Story 5: government portals that do not answer from our network, and what that does to verification.
import re  # noqa: E402
from urllib.parse import urlparse  # noqa: E402

from _common import *  # noqa: F401,F403  # NOTEBOOK-SKIP

OUTCOME = {"ok_html": "Text read", "unreachable": "No answer (timeout or connection)",
           "blocked_http_403": "Refused (403, robots, login)", "robots_disallowed": "Refused (403, robots, login)",
           "login_redirect": "Refused (403, robots, login)", "skipped_after_blocked": "Refused (403, robots, login)",
           "ok_empty": "Empty page or 404", "http_404": "Empty page or 404"}
OUT_ORDER = ["Text read", "No answer (timeout or connection)", "Refused (403, robots, login)", "Empty page or 404"]
OUT_COL = [S.CATEGORICAL[0], S.CATEGORICAL[1], S.CATEGORICAL[6], S.OTHER]  # purple, not yellow: orange-yellow failed the normal-vision floor (13.7)
STRATA = [("official_about", "Facility's own site"), ("aggregator_about", "Aggregator page about it"),
          ("list_page", "Listing page"), ("research", "Research paper"), ("government", "Government portal")]
SCHEME = re.compile(r"esic|hryesi|cghs|pmjay|ayushman|cashless|empanel|arogya|swasthya|pcpndt|kpme|transtan|sotto|"
                    r"(^|\.)ors\.gov|notto|covidcbrs|atalamrit|asbtc|blood|hosplist|registeredhospital", re.I)


def portal_type(url):
    """Hand-written rule for the kind of government page; printed in s5_portal_types.csv for checking."""
    pu = urlparse(url)
    host = pu.netloc.lower().removeprefix("www.")
    if not re.search(r"\.(gov|nic|edu|ac)\.in$", host):
        return "Not a government host (misfiled)"
    if "public-utilit" in pu.path.lower():
        return "District portal directory page"
    if SCHEME.search(host + pu.path):
        return "Scheme, empanelment or registry portal"
    return "Other government page"


pc = load("source_page_checks", ["url", "stratum", "fetch_status"]).drop_duplicates("url")
pc["outcome"] = pc.fetch_status.map(OUTCOME)
assert pc.outcome.notna().all(), pc.fetch_status[pc.outcome.isna()].unique()
a = (pc.groupby(["stratum", "outcome"]).size().unstack(fill_value=0).reindex(columns=OUT_ORDER, fill_value=0))
a["urls"] = a.sum(axis=1)
write_csv(a.reset_index(), "s5_fetch_outcomes")

gov = pc[pc.stratum == "government"].copy()
gov["portal_type"] = gov.url.map(portal_type)
gov["timed_out"] = gov.fetch_status == "unreachable"
TYPES = ["District portal directory page", "Other government page", "Scheme, empanelment or registry portal",
         "Not a government host (misfiled)"]
b_rows = []
for t in TYPES:
    d = gov[gov.portal_type == t]
    p, lo, hi = S.wilson(int(d.timed_out.sum()), len(d))
    b_rows.append(dict(portal_type=t, timed_out=int(d.timed_out.sum()), urls=len(d), rate=p, lo95=lo, hi95=hi))
B = pd.DataFrame(b_rows)
write_csv(B, "s5_government_by_type")
write_csv(gov[["url", "portal_type", "fetch_status"]].sort_values(["portal_type", "url"]), "s5_portal_types")

# How much of the dataset's government evidence is the kind that does not answer.
u = load("source_urls", ["unique_id", "url", "source_class"])
ug = u[u.source_class == "government"].copy()
ug["portal_type"] = ug.url.map(portal_type)
pop = ug.groupby("portal_type").agg(urls=("url", "size"), records=("unique_id", "nunique")).reindex(TYPES)
write_csv(pop.reset_index(), "s5_government_population")
scheme_recs = pop.loc["Scheme, empanelment or registry portal", "records"]

# Registry hosts probed by hand on 2026-11-21, copied from research/discover/registries/CANDIDATES.md.
PROBE_NO_ANSWER = ["data.gov.in", "api.data.gov.in", "hospitals.pmjay.gov.in", "pmjay.gov.in",
                   "dashboard.pmjay.gov.in", "cghs.mohfw.gov.in", "cghs.nic.in", "nhrr.mohfw.gov.in",
                   "www.esic.gov.in", "hmis.mohfw.gov.in", "indianrailways.gov.in", "www.jeevandayee.gov.in",
                   "www.echsbpa.utiitsl.com", "cdsco.gov.in", "cmhis.nagaland.gov.in"]
PROBE_403 = ["facility.abdm.gov.in", "abdm.gov.in", "nha.gov.in"]
PROBE_OK = ["nabh.co", "nmc.org.in", "aikosh.indiaai.gov.in", "www.mohfw.gov.in", "www.echs.gov.in",
            "nin.mohfw.gov.in", "nhm.gov.in", "cbhidghs.mohfw.gov.in", "www.bis.gov.in", "cdnbbsr.s3waas.gov.in",
            "journals.plos.org"]

g = a.loc["government"]
fig, (ax, bx) = S.new_figure((13.5, 8.0), 1, 2, gridspec_kw={"width_ratios": [1.15, 1]})
sch = B.set_index("portal_type").loc["Scheme, empanelment or registry portal", ["timed_out", "urls"]].astype(int)
S.fig_title(fig, f"{g['No answer (timeout or connection)']} of {g.urls} sampled government pages did not answer our one fetch; "
                 f"{sch.timed_out} of those are the scheme and registry portals that could confirm empanelment "
                 f"({sch.timed_out} of {sch.urls} such portals)", wrap=105)
y = np.arange(len(STRATA))[::-1]
for yi, (key, lab) in zip(y, STRATA):
    r = a.loc[key]
    left = 0
    for o, col in zip(OUT_ORDER, OUT_COL):
        share = 100 * r[o] / r.urls
        ax.barh(yi, share, left=left, color=col, height=0.62, label=o if yi == y[0] else None, **S.bar_style())
        if share >= 7:
            ax.text(left + share / 2, yi, f"{r[o]}", ha="center", va="center", fontsize=10,
                    color="#ffffff" if col in (S.CATEGORICAL[0], S.CATEGORICAL[1], S.CATEGORICAL[6]) else S.INK)
        left += share
ax.set_yticks(y, [f"{lab}\n(n = {a.loc[k, 'urls']} URLs)" for k, lab in STRATA])
ax.set_xlim(0, 100)
ax.set_xlabel("Share of sampled source URLs (%); counts inside bars")
ax.grid(axis="y", visible=False)
ax.legend(ncol=2, loc="upper left", bbox_to_anchor=(0, -0.13), fontsize=10.5)
S.panel_title(ax, "A. What happened when we fetched each sampled source page")

yb = np.arange(len(B))[::-1]
bars = bx.barh(yb, 100 * B.rate, color=S.CATEGORICAL[1], height=0.6, **S.bar_style())
S.add_interval(bx, yb, 100 * B.lo95, 100 * B.hi95, horizontal=True, cap=3)
for yi, r in zip(yb, B.itertuples()):
    bx.text(100 * r.hi95 + 2, yi, f"{r.timed_out} of {r.urls}" + ("  (small n)" if r.urls < S.SMALL_N else ""),
            va="center", fontsize=10.5, color=S.INK)
bx.set_yticks(yb, [textwrap.fill(t, 22) for t in B.portal_type], fontsize=10.5)
bx.set_xlim(0, 140)
bx.set_xticks([0, 20, 40, 60, 80, 100])
bx.set_xlabel("No answer (%, 95% Wilson interval)")
bx.grid(axis="y", visible=False)
S.panel_title(bx, f"B. Government URLs by kind of page (n = {len(gov)})")
note = (f"In the whole dataset, {pop.loc['Scheme, empanelment or registry portal', 'urls']:,} government URLs in "
        f"{scheme_recs:,} records point at scheme or registry portals. National registries probed by hand: "
        f"{len(PROBE_NO_ANSWER)} hosts timed out or refused (PM-JAY, CGHS, NHRR, ESIC, HMIS, data.gov.in), "
        f"{len(PROBE_403)} returned 403 (the ABDM facility registry, ABDM, NHA); {len(PROBE_OK)} answered "
        f"(NABH, NMC, MoHFW, NHM). Geo-blocking is suspected, not verified.")
bx.text(-0.3, -0.16, textwrap.fill(note, 92), transform=bx.transAxes, va="top", fontsize=9.5, color=S.INK_2,
        linespacing=1.35, bbox=dict(boxstyle="round,pad=0.5", fc=S.NEUTRAL, ec="none"))
S.source_note(fig, src("source_page_checks", "source_urls") + "; research/discover/registries/CANDIDATES.md (probe, "
                   "2026-11-21).\nOne fetch per URL, 15 s timeout, robots.txt obeyed (pipelines/source_scoring/s3_pagecheck.py).")
S.save(fig, OUT / "s5_reachability", alt_text=(
    f"Stacked bars of fetch outcomes for 385 sampled source URLs. Government portals: {g['No answer (timeout or connection)']} of "
    f"{g.urls} gave no answer, against {a.loc['official_about', 'No answer (timeout or connection)']} of {a.loc['official_about', 'urls']} "
    f"facility sites and 0 of {a.loc['research', 'urls']} research pages, though research publishers refused "
    f"{a.loc['research', 'Refused (403, robots, login)']} of {a.loc['research', 'urls']}. By kind of government page: "
    + "; ".join(f"{r.portal_type} {r.timed_out} of {r.urls} without an answer" for r in B.itertuples())
    + f". District NIC directory pages answer; scheme, empanelment and registry portals (ESIC, CGHS, state cashless "
      f"schemes, PCPNDT, organ registries) mostly do not, so claims of empanelment could not be checked from our network "
      f"(one fetch each; geo-blocking suspected, not verified)."))
print("s5:\n", a.to_string(), "\n", B.round(3).to_string(), "\n", pop.to_string())
