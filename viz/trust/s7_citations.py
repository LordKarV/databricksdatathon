"""Story 7: follow the citation.

Chart s7_citations: for claim sentences tested against a page the record itself cites
(Goal 3 page check, 385 URLs fetched in five strata), how often the page contains the
sentence (strict match) or most of its words (token coverage), by kind of page.

Input: derived/v1/source_page_checks.parquet (built by pipelines/source_scoring; one row per
fetched URL x claim sentence). Not re-fetched here.
Run: .venv-viz/bin/python viz/trust/s7_citations.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import trust_io as io
import style as S

STRATA = {"official_about": "Facility's own site, about page", "aggregator_about": "Aggregator profile page",
          "list_page": "List page (many facilities)", "government": "Government page", "research": "Research paper"}


def run():
    p = io.load("page_checks")
    urls = p.groupby("stratum").url.nunique()
    t = p[p.claim_id.notna()].copy()
    g = t.groupby("stratum").agg(n=("supported", "size"), k=("supported", "sum"), k_tok=("token_supported", "sum"),
                                 urls_text=("url", "nunique")).reset_index()
    g["urls_any"] = g.stratum.map(t[t.supported].groupby("stratum").url.nunique()).fillna(0).astype(int)
    g["urls_checked"] = g.stratum.map(urls)
    g[["rate", "lo", "hi"]] = [S.wilson(int(k), int(n)) for k, n in zip(g.k, g.n)]
    g[["tok_rate", "tok_lo", "tok_hi"]] = [S.wilson(int(k), int(n)) for k, n in zip(g.k_tok, g.n)]
    g = g.sort_values("rate").reset_index(drop=True)
    N, K, KT = len(t), int(t.supported.sum()), int(t.token_supported.sum())

    fig, ax = S.new_figure(size=(12, 6.4))
    y = np.arange(len(g))
    off = 0.14
    S.add_interval(ax, y + off, g.tok_lo * 100, g.tok_hi * 100, horizontal=True, cap=0, lw=2, color=S.AXIS)
    S.add_interval(ax, y - off, g.lo * 100, g.hi * 100, horizontal=True, cap=0, lw=2, color=S.AXIS)
    ax.plot(g.tok_rate * 100, y + off, "o", ms=8, color=S.SEMANTIC["likely"], label="Most of its words are on the page")
    ax.plot(g.rate * 100, y - off, "o", ms=8, color=S.SEMANTIC["verified"], label="The sentence is on the page")
    for yi, r in g.iterrows():
        ax.annotate(f"{r.rate * 100:.1f}% ({int(r.k)} of {int(r.n):,})", (r.hi * 100, yi - off), xytext=(6, 0),
                    textcoords="offset points", va="center", fontsize=10.5, color=S.INK)
        ax.annotate(f"{r.tok_rate * 100:.0f}%", (r.tok_hi * 100, yi + off), xytext=(6, 0), textcoords="offset points",
                    va="center", fontsize=10.5, color=S.INK_2)
    ax.set_yticks(y, [f"{STRATA[s]}\n{int(u)} of {int(c)} pages readable; {int(a)} hold any claim"
                      for s, u, c, a in zip(g.stratum, g.urls_text, g.urls_checked, g.urls_any)], fontsize=10.5)
    ax.set_xlim(0, 60)
    ax.set_xlabel(f"Claim sentences found on a page the record cites (%, 95% Wilson interval; n = {N:,} sentences)")
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower right", fontsize=11)
    o = g.set_index("stratum").loc["official_about"]
    S.finding_title(ax, f"Only {K / N * 100:.1f}% of claim sentences ({K} of {N:,}) appear on a page their own record "
                        f"cites; on the facility's own about page, {o.rate * 100:.1f}% do", wrap=70,
                    subtitle=f"{int(g.urls_text.sum())} readable pages of {int(g.urls_checked.sum())} cited URLs, five "
                             "page types (stratified sample)")
    io.note(fig, "Source: derived/v1/source_page_checks.parquet (pipelines/source_scoring Goal 3 page check). "
                 "'On the page' = exact or near-exact match; 'most of its words' = token coverage rule (token_supported). "
                 "The pooled 5.4% mixes strata sampled at fixed sizes, so it is not a population estimate. The extractor paraphrased text, so the strict rate understates support. Intervals treat sentences "
                 "as independent; they cluster within pages, so true uncertainty is wider.")
    io.write_csv(g, "s7_citations")
    alt = (f"Dot plot by cited page type. Of {N:,} claim sentences tested against pages their own record cites, "
           f"{K} ({K / N * 100:.1f}%) were found on the page and {KT:,} ({KT / N * 100:.0f}%) had most of their words "
           f"there. The facility's own about page did best at {o.rate * 100:.1f}% ({int(o.k)} of {int(o.n):,}); "
           f"research papers and government pages held about 1%. The cited source_urls behave like search results, "
           f"not citations.")
    S.save(fig, io.out("s7_citations"), alt)
    print("s7", dict(N=N, K=K, KT=KT), g[["stratum", "k", "n", "rate", "tok_rate", "urls_text", "urls_any"]].to_dict("records"))
    return g


if __name__ == "__main__":
    run()
