"""Plain words for the derived/v2 witness ledger on the Why page: one line per model term, in English and Hindi.

Keys are the `label` of a derived/v2 contributions term (model/MODEL_SPEC.md 3.2, derived/v2/README.md); the
facts build fails on a term that has no line here, so a new model term cannot reach the page unnamed. Hindi follows
kb/taxonomy/HINDI_GLOSSARY.md (अस्पताल, लिस्टिंग, इमरजेंसी, सेवा, 24 घंटे खुली इमरजेंसी). The Hindi lines are a
draft written for this ledger and need the same native-speaker review as the glossary (#10).
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

# term -> (English, Hindi). "base" is the model's starting score, the same for every pair.
TERMS: dict[str, tuple[str, str]] = {
    "base": ("Starting score, the same for every listing", "शुरुआती अंक, हर लिस्टिंग के लिए एक जैसे"),
    # T: the listing's own text about the service
    "t1": ("Its listing names it, at least in a specialty tag or list",
           "लिस्टिंग में इसका नाम है, चाहे सिर्फ़ विभागों के नाम में"),
    "t2": ("Its listing describes it as a service of its own", "लिस्टिंग में यह सेवा अलग से लिखी है"),
    "t3": ("More than one line about it in one part of the listing",
           "लिस्टिंग के एक हिस्से में इसके बारे में एक से ज़्यादा बातें"),
    "t4": ("Lines about it in two or more parts of the listing",
           "लिस्टिंग के दो या ज़्यादा हिस्सों में इसके बारे में बातें"),
    "t5": ("Lines about it in several parts, with a size or count",
           "कई हिस्सों में इसके बारे में बातें, गिनती या आकार के साथ"),
    "trunc0": ("Not named, but its list of services was cut short",
               "नाम नहीं है, पर इसकी सेवाओं की लिस्ट अधूरी कटी हुई है"),
    # C: text that belongs to another facility, and the record's risk of it
    "c1": ("Some lines name another facility", "कुछ बातों में किसी दूसरे अस्पताल का नाम है"),
    "c2": ("Lines name another facility, and none is its own",
           "बातों में दूसरे अस्पताल का नाम है, इसकी अपनी कोई बात नहीं"),
    "tb_high": ("Record built from 30 or more web pages; some text may be another facility's",
                "रिकॉर्ड 30 या ज़्यादा वेब पेजों से बना है; कुछ बातें किसी दूसरे अस्पताल की हो सकती हैं"),
    "tb_mid": ("Record built from many web pages; some text may be another facility's",
               "रिकॉर्ड कई वेब पेजों से बना है; कुछ बातें किसी दूसरे अस्पताल की हो सकती हैं"),
    "tp_public": ("Public facility: its listing text is less often its own",
                  "सरकारी अस्पताल: इसकी लिस्टिंग की बातें कम बार इसकी अपनी होती हैं"),
    # N, S, P
    "n1": ("A line says it refers out, runs camps, plans it or does not offer it",
           "एक बात में लिखा है कि यह मरीज़ आगे भेजता है, कैंप लगाता है, आगे शुरू करेगा या यह सेवा नहीं देता"),
    "s1": ("Its focus (eye, dental, IVF or lab) does not fit this care",
           "इसका काम (आँख, दाँत, IVF या लैब) इस सेवा से मेल नहीं खाता"),
    "p1": ("It names something this care needs, such as an ICU, operating theatre or blood bank",
           "इस सेवा के लिए ज़रूरी कोई चीज़ लिखी है, जैसे ICU, ऑपरेशन थिएटर या ब्लड बैंक"),
    "p2": ("It names a second thing this care needs", "इस सेवा के लिए ज़रूरी दूसरी चीज़ का नाम भी है"),
    # X: official and registry lists
    "x_nabh:department": ("NABH's portal lists this department for it", "NABH पोर्टल पर इसका यह विभाग दर्ज है"),
    "x_nabh:department_proxy": ("NABH's portal lists a related department for it",
                                "NABH पोर्टल पर इससे जुड़ा विभाग दर्ज है"),
    "x_nabh:service_code": ("NABH's portal lists this service's code for it", "NABH पोर्टल पर इस सेवा का कोड दर्ज है"),
    "x_nmc:department": ("NMC list: a medical college with a postgraduate course in this",
                         "NMC सूची: इस विषय में PG कोर्स वाला मेडिकल कॉलेज"),
    "x_nmc:department_support": ("NMC list: a medical college with a related postgraduate course",
                                 "NMC सूची: इससे जुड़े PG कोर्स वाला मेडिकल कॉलेज"),
    "x_laqshya:certificate": ("LaQshya certificate for its maternity operating theatre",
                              "प्रसव ऑपरेशन थिएटर के लिए LaQshya प्रमाणपत्र"),
    "x_laqshya:expired": ("Expired LaQshya certificate for its maternity operating theatre",
                          "प्रसव ऑपरेशन थिएटर का LaQshya प्रमाणपत्र, जिसकी अवधि खत्म हो चुकी है"),
    "x_mohfw_tcf:designation": ("On the government list of trauma care facilities (MoHFW)",
                                "सरकार की ट्रॉमा केयर अस्पतालों की सूची (MoHFW) में है"),
    "x_erk_prereq": ("A blood centre on site (e-RaktKosh list), which this care needs",
                     "अस्पताल में ब्लड बैंक है (ई-रक्तकोष सूची), जो इस सेवा के लिए ज़रूरी है"),
    "x_pmndp_goa:service": ("On the Goa government dialysis list (PMNDP)",
                            "गोवा सरकार की डायलिसिस सूची (PMNDP) में है"),
    # W: the facility's own website
    "w_cell_A": ("Its own website says so clearly, on 2 or more pages",
                 "इसकी अपनी वेबसाइट पर 2 या ज़्यादा पेजों पर साफ़ लिखा है"),
    "w_cell_B": ("Its own website lists it clearly", "इसकी अपनी वेबसाइट की सेवाओं में साफ़ लिखा है"),
    "w_cell_C": ("Its own website has a clear line about it", "इसकी अपनी वेबसाइट पर इसके बारे में एक साफ़ बात है"),
    "w_cell_D": ("Its own website mentions it loosely, on 2 or more pages",
                 "इसकी अपनी वेबसाइट पर 2 या ज़्यादा पेजों पर हल्का सा ज़िक्र है"),
    "w_cell_E": ("Its own website mentions it loosely, on one page",
                 "इसकी अपनी वेबसाइट के एक पेज पर हल्का सा ज़िक्र है"),
    "w_overlap": ("Website and listing share pages, so that part counts once",
                  "वेबसाइट और लिस्टिंग के पेज एक ही हैं, इसलिए वह हिस्सा एक बार गिना"),
    "w_silent": ("Its website works but does not mention it", "इसकी वेबसाइट खुलती है पर उसमें इस सेवा का ज़िक्र नहीं"),
    "w_24x7@trauma_care": ("Its own website says 24x7 emergency",
                           "इसकी अपनी वेबसाइट पर 24 घंटे खुली इमरजेंसी लिखी है"),
    "w_24x7@emergency_csection": ("Its own website says 24x7 emergency",
                                  "इसकी अपनी वेबसाइट पर 24 घंटे खुली इमरजेंसी लिखी है"),
    # O, D, K
    "o_speciality": ("OpenStreetMap lists this specialty there", "OpenStreetMap पर यहाँ यह विभाग दर्ज है"),
    "d_unit": ("A dataset detail for this care (equipment, unit beds or a 24x7 unit)",
               "डेटा में इस सेवा की जानकारी (मशीनें, यूनिट के बेड या 24 घंटे की यूनिट)"),
    "k_iphs": ("Public standard (IPHS 2022): a hospital at this level should offer it",
               "सरकारी मानक (IPHS 2022): इस स्तर के अस्पताल में यह सेवा होनी चाहिए"),
    # context: what kind of place it is
    "beds_100p": ("100 or more beds", "100 या ज़्यादा बेड"),
    "beds_lt30": ("Fewer than 30 beds", "30 से कम बेड"),
    "breadth_20p": ("20 or more specialties listed", "20 या ज़्यादा विभाग लिखे हैं"),
    "breadth_lt5": ("Fewer than 5 specialties listed", "5 से कम विभाग लिखे हैं"),
    "level_dh": ("District hospital", "ज़िला अस्पताल"),
    "level_mc": ("Medical college hospital", "मेडिकल कॉलेज अस्पताल"),
    "level_phc": ("Primary health centre", "प्राथमिक स्वास्थ्य केंद्र"),
    "level_sdh": ("Sub-divisional hospital", "अनुमंडल अस्पताल"),
    "scale_contradiction": ("Its stated size is too small for this care", "इसका बताया गया आकार इस सेवा के लिए छोटा है"),
    "type_clinic": ("Listed as a clinic", "क्लिनिक के रूप में दर्ज"),
    "type_other": ("Facility type: other", "अस्पताल का प्रकार: अन्य"),
}

# Families the source cannot see for a pair (facility_features obs_<family> == "not_observable"). They add 0 points,
# so the page names them in one muted line instead of a row. R (the automated reader) is left out: it is not
# observable for every pair in v2, so it says nothing about this listing.
NOT_OBSERVED: dict[str, tuple[str, str]] = {
    "W": ("No website found", "वेबसाइट नहीं मिली"),
    "X": ("Public lists do not cover this kind of facility", "सरकारी सूचियाँ इस तरह के अस्पताल को शामिल नहीं करतीं"),
    "O": ("Not matched on OpenStreetMap", "OpenStreetMap पर नहीं मिला"),
    "K": ("Public standard (IPHS) does not apply or its level is unknown",
          "सरकारी मानक (IPHS) लागू नहीं या इसका स्तर पता नहीं"),
}

# The NABH portal holds three kinds of entry under one search (derived/v2 facility_attributes nabh_tier); a cite says
# which, so an entry-level certificate or a CGHS/ECHS empanelment is never read as accreditation (WS4 4a, #140).
NABH_TIER: dict[str, str] = {
    "full_accreditation": "NABH full accreditation {acc}",
    "entry_level": "NABH entry-level certificate {acc}",
    "cghs_echs_empanelment": "CGHS/ECHS empanelment listed on NABH's portal; not accreditation ({acc})",
}
NABH_UNTIERED = "Listed on NABH's portal ({acc})"

# derived/v2 overlay ON_A_PUBLIC_LIST:<list>:<date> -> the list's name on the Why page's "Official lists" line.
LIST_NAMES: dict[str, str] = {
    "nabh": "NABH",
    "nmc": "NMC medical colleges",
    "eraktkosh": "e-RaktKosh blood centres",
    "laqshya": "LaQshya (NHSRC)",
    "mohfw_tcf": "MoHFW trauma care facilities",
    "pmndp_goa": "Goa PMNDP dialysis centres",
}


def nabh_text(tier: str | None, acc: str) -> str:
    return NABH_TIER.get(tier or "", NABH_UNTIERED).format(acc=acc)


# Cite links (#166 review). Hosts whose entry links opened the entry in a desktop browser (Chromium with a normal user
# agent, our page as referer), checked 2026-11-22. A cite that links any other host fails the facts build.
CITE_HOSTS: frozenset[str] = frozenset({
    "portal.nabh.co", "nabh-tenant-bucket-prod.s3.ap-south-1.amazonaws.com", "nabh.co",
    "nmc.org.in", "eraktkosh.mohfw.gov.in", "qps.nhsrcindia.org", "web.archive.org", "nhm.goa.gov.in",
    "www.openstreetmap.org", "www.wikidata.org",
})
# Hosts whose entry links never open for a reader. The CGHS/ECHS certificate bucket answers S3 AccessDenied (403) to
# a GET, in a browser too and with NABH's page as referer: NABH's portal serves those files by signed link only, and
# external/nabh_accredited/parse.py drops the signature. hope.qcin.org:5004/Reportviewer.aspx answers "Invalid
# Request, url failed !!" without the portal's query string. Their cites link the list's own search page instead.
DEAD_ENTRY_HOSTS: frozenset[str] = frozenset({
    "annovatech-echscghs-2024.s3.ap-south-1.amazonaws.com", "hope.qcin.org:5004",
})
# Each list's own page a reader can search, from the "Page" line of its external/<source>/README.md. NMC's entry link
# is its JSON endpoint, which a phone shows as raw JSON, so NMC cites link the list's page as well.
LIST_PAGE: dict[str, str] = {
    "nabh": "https://nabh.co/find-a-healthcare-organisation/",
    "nmc": "https://nmc.org.in/page/information-desk-for-students-to-study-in-india-list-of-college-teaching-mbbs",
}
JSON_ENTRY_URLS: frozenset[str] = frozenset({"https://nmc.org.in/college-courses/list"})


def cite_url(list_key: str | None, url: str | None) -> tuple[str | None, bool]:
    """(the link a cite shows, whether that link opens the entry itself) for one list row's evidence url.

    An entry link that cannot open (not an http link, a DEAD_ENTRY_HOSTS host, a JSON endpoint) becomes the list's
    own search page when it has one, else no link. The cite keeps its text, source and date, so the reader still has
    the list name, the entry number and the date it was read.
    """
    if (url and url.startswith(("https://", "http://")) and urlsplit(url).netloc not in DEAD_ENTRY_HOSTS
            and url not in JSON_ENTRY_URLS):
        return url, True
    return LIST_PAGE.get(list_key or ""), False


# OpenStreetMap and Wikidata matches (derived/v2 witnesses value_text "osm high, 5.63 km"): the tier is our match
# confidence, so the page says what the match means instead. A conflict-tier match has the same name but a point far
# from the listing's (model/v2/assemble/acommon.py: "conflict tier: location warning").
OSM_MATCH = re.compile(r"^(osm|wikidata) (high|medium|conflict), ([\d.]+) km$")
OSM_SOURCE = {"osm": "OpenStreetMap", "wikidata": "Wikidata"}
OSM_TEXT: dict[str, tuple[str, str]] = {
    "match": ("{name}: on {src}, mapped {km} km from the listed point",
              "{name}: {src} पर, लिस्टिंग के पते से {km} किमी पर दर्ज"),
    "conflict": ("{name}: on {src} under the same name, but mapped {km} km from the listed point; check the address",
                 "{name}: {src} पर इसी नाम से, पर लिस्टिंग के पते से {km} किमी दूर दर्ज; पता जाँच लें"),
}


def osm_text(name: str, value: str | None) -> tuple[str, str] | None:
    """(English, Hindi) for an OSM/Wikidata match row, or None for a tag row such as "emergency=yes"."""
    m = OSM_MATCH.match(value or "")
    if not m:
        return None
    src, tier, km = m.groups()
    return tuple(t.format(name=name, src=OSM_SOURCE[src], km=km)  # type: ignore[return-value]
                 for t in OSM_TEXT["conflict" if tier == "conflict" else "match"])
