# Facility website crawl

A polite crawl of the facilities' own websites. It gives the knowledge base independent page text to quote from when stating what a facility offers, its hours and its details. It also records whether each site is still alive and still belongs to the facility. Every number below comes from `report.py` (written to `crawl_stats.json`) or from the hand checks listed at the end.

## Files

- `targets.py` builds `targets.parquet` (9,405 crawl targets) and `targets_stats.json`.
- `crawl.py` is the async crawler. It is resumable and stops itself after `--max-seconds`. It writes the checkpoint `data/crawl/checkpoint.jsonl`, the page text `data/crawl/pages/*.json.gz` and the run log `data/crawl/runs.jsonl`, then rebuilds `pages.parquet` and `sites.parquet`.
- `extract.py` holds the pure functions: text extraction (trafilatura, with a selectolax/lexbor full-text fallback), phone and email redaction, keyword link choice, language by script, and the parked/suspended/spam hints. It has a self-check: `.venv-crawl/bin/python kb/crawl/extract.py`.
- `report.py` writes `crawl_stats.json`, `coverage_by_state.csv` and `coverage_by_type.csv`.
- `gov_probe.jsonl` holds the government-portal reachability probe.

Environment: `/Users/karthikvattem/projects/datathon/.venv-crawl` (httpx, selectolax, trafilatura, protego, pandas, pyarrow, rapidfuzz, duckdb).

    .venv-crawl/bin/python kb/crawl/targets.py
    .venv-crawl/bin/python kb/crawl/crawl.py --max-seconds 500          # repeat until "0 targets never started"
    .venv-crawl/bin/python kb/crawl/crawl.py --max-seconds 400 --retry transient
    .venv-crawl/bin/python kb/crawl/report.py

Note: `.gitignore` has `*.parquet`, with an exception only for `derived/`. The three parquet files here (6 MB in total) are untracked until someone adds an exception for `kb/`.

## Targets

A record's candidate URLs are `officialWebsite`, `websites` and `source_urls`. A URL is kept only when `audit/provenance/domains.classify` calls its host `official` or `official_like`. Shorteners, site builders' shared front pages and directories that slipped through the name match are dropped (`NOT_A_SITE`). Examples: business.site, g.page, sites.google.com, infoisinfo, indiamart.

- 8,015 of 9,959 usable records have at least one candidate. By type: hospitals 4,583 of 5,610, clinics 2,987 of 3,770, dentists 374 of 488.
- A site is a host without `www.` or `m.`, which gives 9,037 sites on 8,918 registrable domains. Site builders such as placeweb.site and setmore.com host one facility per subdomain, so the host is the unit. The registrable domain is the rate-limit key.
- 219 sites are shared: records in 2 or more cities, or 2 or more duplicate groups, point at them (Apollo, Fortis, Manipal, Indira IVF and others). Each shared site gets one `shared_home` target linked to all its records. Each record with a branch-specific URL (non-root path) gets its own `branch` target, 368 in all. The other 8,818 sites are `site` targets.
- Order: hospitals first, then clinics, then dentists and other types. Within each tier, targets go round-robin over states. `shared_home` targets come after the facility-specific targets of their tier.
- Government portals were skipped as instructed. Two were probed once each: a district NIC page (`thrissur.nic.in`) answered HTTP 200 in 2.4 s, and `pmjay.gov.in` timed out after 15 s. District NIC portals are therefore reachable from this machine, but PM-JAY is not.

## Crawler rules

- User-Agent `datathon-facility-check/0.1`.
- Requests to one registrable domain are spaced at least 1 s apart. This includes every redirect hop (redirects are followed by hand) and robots.txt.
- 24 workers in parallel.
- 15 s cap per request, HTML only, 2 MB cap per page (98 pages were truncated at the cap).
- robots.txt is parsed with protego (RFC 9309, wildcards). Python's `urllib.robotparser` was tried first and dropped: it reads `Disallow: /?` as `Disallow: /`. Rules are handled as follows:
  - 401 or 403 on robots.txt: do not crawl the site.
  - 5xx on robots.txt: do not crawl the site.
  - 404 or an HTML soft-404: allow.
  - Crawl-delay: honoured up to 30 s. Sites asking for more are skipped (11 sites).
- Pages per target: at most 6. These are the homepage (or the branch URL), up to 2 of the record's own deep URLs, then same-site links whose URL or anchor text matches a keyword group. One link is taken per group first, in this order: specialty, services, facilities, emergency, timing, dialysis, maternity, icu, radiology, about, contact, doctors. Remaining slots are then filled in the same order. Individual doctor profile pages are not followed. Branch targets only follow links that contain the branch slug.
- Every stored text has emails and Indian phone numbers replaced by `[email]` and `[phone]`. A full re-scan after the fix found 0 emails and 0 bare 10-digit mobiles in 28,106 files. The first regex missed numbers before a sentence-ending period. All files were re-redacted, and the pre-fix checkpoint copies were deleted.
- On a TLS certificate error the crawler retries once without verification (221 sites, flag `site_tls_invalid`). On a connection failure over https it retries over http (128 sites).

## Outputs

`pages.parquet` has one row per page attempt: 31,075 rows, 28,909 with stored text. Its columns are `target_id`, `unique_ids` (list), `url`, `final_url`, `role` (home, seed, or `link:<keyword group>`), `http_status`, `fetched_at` (UTC), `last_modified`, `content_type`, `truncated`, `error`, `title`, `text_hash` (sha1 of the stored text), `text_len`, `chrome_len`, `lang`, `fallback_text` and `path`.

Stored rows outnumber files (28,909 vs 28,106) because duplicate records and chain homes reach the same final URL. They share one file named by the hash of the final URL.

Each gz file holds `{target_id, url_final, fetched_at, title, text, chrome_text}`:
- `text` is the boilerplate-stripped main text. When trafilatura found under 300 characters, it is the full visible text instead (3,453 pages).
- `chrome_text` is header, footer and top-bar text not already in `text`. Hours and "24x7 emergency" banners often live there. Downstream quote matching should search both fields.

`lang` is a script-based guess: 28,311 pages `en` (any Latin script), 444 `none` (empty), 109 Devanagari, 20 Gujarati, 10 Tamil, 8 Malayalam, 4 Telugu, 3 Bengali. Hinglish counts as `en`.

`sites.parquet` has one row per target: `target_id`, `site`, `domain`, `kind`, `shared`, `unique_ids`, `site_status`, `site_home_final_url`, flags (`site_tls_invalid`, `site_http_fallback`, `site_redirect_same_org`, `site_under_construction`, `site_spam_injected`, `site_relabelled`, `site_first_page_error`), `n_pages_stored` and `n_page_attempts`.

Downstream use: only take text from targets whose `site_status` is `ok` or `ok_thin`. Treat `site_spam_injected` as a warning that the site has been hacked: the facility text is real, but the site is not maintained.

## Results

Crawl time was 51.5 minutes over 9 runs of at most 500 s each, out of the 120-minute budget. That includes a 122 s smoke run whose output was thrown away (robots parser bug) and recrawled, one retry pass for transient failures (310 targets), and one recrawl of the redirect and parked targets after the classifier fixes (209 targets). Nothing is left to crawl: every one of the 9,405 targets has a final status.

All 9,037 sites were attempted, and 6,127 of them are reachable (`ok` or `ok_thin` on at least one target). At target level, 6,405 of 9,405 are reachable: 5,949 of 8,818 own sites, 280 of 368 branch pages and 176 of 219 chain homes.

Failure breakdown (targets):

| Group | Status | Targets |
|---|---|---|
| Dead or unreachable (2,123) | dns_fail | 1,880 |
| | timeout | 122 |
| | connect_error | 49 |
| | http_5xx | 42 |
| | tls_error | 29 |
| | protocol_error | 1 |
| Live but not this facility (565) | http_4xx | 253 |
| | hijacked_spam (gambling or adult spam on an expired domain) | 156 |
| | redirect_unverified (new domain that does not name the facility) | 61 |
| | suspended_or_expired (hosting suspended, bare "Index of /") | 31 |
| | parked_or_for_sale | 22 |
| | too_many_redirects | 18 |
| | empty | 12 |
| | redirect_third_party (social or directory) | 8 |
| | non_html | 4 |
| Blocked by site policy (312) | robots_disallow | 121 |
| | robots_txt_forbidden | 94 |
| | robots_txt_5xx | 86 |
| | crawl_delay_too_long | 11 |

Other flags: 150 redirects went to a same-organisation domain (rebrands, and chains that absorbed a site) and were crawled there. 45 sites are under construction. 34 reachable sites carry injected spam.

About 1 in 5 official websites in the dataset no longer resolves (1,880 of 9,405 targets). That is a useful liveness signal for the trust model.

### Pages

- 28,909 pages stored; 28,589 of them belong to reachable targets.
- 26,958 distinct texts.
- Median text length 1,705 characters, 90th percentile 6,226.
- 437 stored pages have empty text.
- Roles: 6,378 home, 4,769 record-given deep URLs, 17,762 keyword links.
- Keyword links by group: about 3,450, services 3,328, contact 2,925, specialty 2,403, facilities 1,321, maternity 1,111, emergency 715, doctors 714, dialysis 582, radiology 571, timing 390, icu 252.
- 6,559 pages sent a Last-Modified header.

### Coverage

A record counts as covered when a facility-specific target (own site or branch page) linked to it is reachable. A further 160 records reach only their chain's homepage (`chain_home_only` in the CSVs).

| Type | Records | With candidate | Covered | Share |
|---|---|---|---|---|
| hospital | 5,610 | 4,583 | 3,382 | 0.603 |
| clinic | 3,770 | 2,987 | 2,040 | 0.541 |
| dentist | 488 | 374 | 259 | 0.531 |
| other or null | 91 | 71 | 40 | 0.440 |

All 34 states and UTs present in the data have at least one covered record. The share covered runs from 0.715 (Kerala) and 0.723 (Chandigarh) down to 0.300 (Jammu and Kashmir) and 0.286 (Meghalaya, 4 of 14). See `coverage_by_state.csv`.

### Identity check (automatic)

On 5,779 reachable facility-specific targets whose linked record has a distinctive name key of 5 or more characters, the stored text contains that key (fuzzy partial ratio of 90 or more) for 3,932 targets: 0.680, Wilson 95% [0.668, 0.692]. The other 32% are a mix of name spelling variants and sites that may describe a different facility. Nothing has been hand-checked to split the two. Downstream steps should require the facility name, or its address PIN, on the page before using a quote from it.

### Content teaser

These are regex hits over the 6,229 reachable facility-specific targets, a rough guide to what the extraction step can find. They are not verified facts.

- Some mention of 24x7 or 24 hours: 2,702
- OPD or timing pattern: 2,065
- Insurance, cashless or PM-JAY: 1,402
- A bed count: 1,165
- Dialysis: 1,069
- NABH: 901

## Hand checks

| Check | Result | Wilson 95% |
|---|---|---|
| dns_fail re-resolved via 8.8.8.8 | 0 of 40 resolved | false-failure rate at most 0.088 |
| hijacked_spam titles | 25 of 25 are gambling spam | [0.867, 1.0] |
| parked_or_for_sale, first version | 8 of 10 correct | [0.49, 0.943] |

- The parked misses were netranidan.com, where `dan.com` matched inside the hostname (now fixed), and one US lead-generation site.
- redirect_unverified was a census, not a sample. All 67 targets in this class before the last spam relabel were labelled by eye: 25 same organisation (rebrand or acquired), 29 different organisation or junk, 13 unclear. Treat this status as "not verified", not as "wrong".

## Known limits

- Only text pages were fetched, so PDFs (brochures, tariff lists) and pages that need JavaScript were missed. 437 stored pages have empty text, many of them script-rendered.
- A fixed 6-page budget favours services and specialty pages. Hours pages are only 390 of the link pages; hours more often sit in `chrome_text` and on contact pages.
- `last_modified` is often the server's render time, not a content date.
- Chain homes describe the chain, not the branch. Do not attribute chain-wide claims to a branch without a branch page.
