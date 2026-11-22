# Web labelling rubric (gold v3, issue #51) - apply exactly

Input rows: {pair_id, service, name, city, district, state, website}. `website` is the record's own domain; it is
usually right but check it is the same facility (name AND place) before trusting it.

Services, and what "confirmed" means:
- dialysis: haemodialysis offered at this facility
- emergency_csection: emergency caesarean section done here (obstetric operating theatre)
- nicu: neonatal intensive care unit, or a special newborn care unit (SNCU)
- cardiac_surgery: open-heart or cardiac surgery (CABG, valve) done here; a cath lab alone is not enough
- mri: an MRI scanner on site
- burn_care: a burn unit or ward, or burns treated as a service
- trauma_care: a trauma centre or a 24x7 emergency that takes accident and injury cases
- emergency_24x7: an emergency department open 24 hours
- stemi_thrombolysis: treats heart attacks (thrombolysis or primary angioplasty)

Per pair:
- exists: yes / no / unclear (evidence the facility exists and operates)
- location_ok: yes / no / unclear (it is in the stated city/district/state)
- service:
  - confirmed: the facility's own site, a government list or scheme page, or a reputable page with
    facility-specific detail that is not a copy of a directory listing, dated within about 5 years;
  - contradicted: credible evidence it does not offer it, an unrelated single-specialty facility (eye, dental,
    skin clinic ...), closed, the claim belongs to another facility, or an exhaustive official list omits it;
  - no_info: neither.
- confidence: high / medium / low
- evidence_urls: up to 3 URLs you actually read
- quote: at most 25 words, verbatim from the page that decided the verdict ("" if none)
- notes: one or two sentences on how you decided
- searches_used: web searches run for this pair (page fetches do not count)

Rules:
- At most 5 web searches per pair. Start with the given website (home page, then services / departments /
  facilities pages). If it is dead or belongs to another facility, search for the facility's own current site
  (name + city) first; then government or scheme lists (PM-JAY empanelment, state health department, NHM), then
  reputable news.
- Aggregators that copy listings (Justdial, Practo-style directories) can support `exists` only, never "confirmed".
- Public pages only. Respect robots.txt. Record no personal data: no doctor names, phone numbers or patient details.
- Do not guess. If you cannot decide, it is no_info with low confidence.
- Work alone: do not read any other *_out.json file in this folder.

Output: write JSON {"batch": "<batch id>", "labeller": "<A or B>", "results": [ {pair_id, exists, location_ok,
service, confidence, evidence_urls, quote, notes, searches_used}, ... ]} with every input pair. Write the file
after every 5 pairs so progress is not lost. If the search tool stops working, label the rest no_info with notes
saying so.
Final reply (short): counts of confirmed / contradicted / no_info, total searches, any tool limits hit.
