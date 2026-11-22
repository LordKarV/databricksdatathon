# Fetch-only addendum (applies on top of RUBRIC.md)

The web-search tool is NOT available for this batch. Do not call it. Use page fetches only:
1. The given website: home page, then its services / departments / facilities / about pages (follow links).
2. If it is dead or belongs to another facility, try obvious variants of the facility's own domain
   (with and without www, .com / .in / .org) only when the name makes the domain likely; do not guess widely.
3. Government sources you can reach by URL without searching, where relevant: the facility's state health
   department or NHM site, or a district site (<district>.nic.in) page listing hospitals.
Same verdict rules, same evidence standard. Set searches_used to 0 and add "method": "fetch_only" to every
result. If no page decides it, the verdict is no_info (low confidence) - that is expected and fine.
