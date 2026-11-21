"""Rule-based source-domain classifier. Order of RULES matters: first match wins.
ponytail: hand-written host lists cover the head of the distribution (see q1 coverage
stats); the long tail falls to 'official_like' (host label matches the facility name)
or 'other'."""
import re

from rapidfuzz import fuzz

RULES = [
    ("research", r"(ncbi\.nlm\.nih\.gov|europepmc|researchgate|journals\.lww|sciencedirect|springer|"
                 r"wiley|tandfonline|frontiersin|nature\.com|bmj\.com|thelancet|cureus|academia\.edu|"
                 r"semanticscholar|doi\.org|medrxiv|biorxiv|plos|mdpi|hindawi|sagepub|(^|\.)oup\.com$|"
                 r"cambridge\.org|karger|thieme|jaypeejournals|wjgnet|medknow|ijcmph|ijrcog|msjonline|"
                 r"jebmh|jmscr|iosrjournals|ijsr\.net|scirp|jcdr|ijpsr|ijmrhs|journal|ijcr|ijss|"
                 r"pubmed|apjhs|ijhsr|dovepress|scielo|ajol|jamanetwork|nejm|elsevier|"
                 r"clinicaltrials\.gov|ctri\.nic\.in|ijmedicine|ijorl|ijsurgery|ijpediatrics|ijbcp|"
                 r"ijrms|ijmsweb|ijcmr|ijsrp|ijirt|ijrar|ijcrt|jetir|bvsalud|europeanreview|"
                 r"pjms|isjem|ijmrr|ejcm|tmrjournals|ijmhr|annals|archives|bjmp|jkscience|"
                 r"jpbs|pmj\.bmj|ijdvl|ijaweb|ijccm|ijoc|ijpmonline|jiaps|jgid|jfmpc|"
                 r"ncbi|scholar\.|repository|eprints|shodhganga|dspace)"),
    ("docs_repo", r"(scribd\.com|slideshare|pdfcoffee|issuu|yumpu|dokumen|studocu|docplayer|"
                  r"pdfslide|vdocuments|documents\.pub|fliphtml5|coursehero)"),
    ("wikipedia", r"(wikipedia\.org|wikiwand|wikidata)"),
    ("government", r"(\.gov\.in$|\.nic\.in$|\.gov$|gov\.in$|nic\.in$|pmjay|nha\.gov|ayushman|"
                   r"esic|cghs|nhm\.|nrhm|mohfw|icmr|aiims|\.gov\.|pmnrf)"),
    ("social", r"(facebook\.com|fb\.com|instagram\.com|linkedin\.com|^x\.com|twitter\.com|"
               r"youtube\.com|youtu\.be|threads\.net|pinterest|quora\.com|reddit\.com|tumblr|"
               r"medium\.com|blogspot|wordpress\.com|sharechat|koo\.in|telegram|whatsapp)"),
    ("news", r"(timesofindia|indiatimes|timesnownews|thehindu|tribuneindia|khabarchhe|ndtv|"
             r"hindustantimes|indianexpress|newindianexpress|deccanherald|deccanchronicle|"
             r"business-standard|livemint|news18|thewire|scroll\.in|theprint|dnaindia|firstpost|"
             r"outlookindia|indiatoday|medicaldialogues|expresshealthcare|financialexpress|"
             r"jagran|bhaskar|amarujala|patrika|lokmat|manoramaonline|mathrubhumi|onmanorama|"
             r"telegraphindia|thestatesman|freepressjournal|mid-day|siasat|newsmeter|"
             r"etvbharat|zeenews|abplive|republicworld|oneindia|thenewsminute|"
             r"daijiworld|udayavani|sakal|loksatta|maharashtratimes|navbharattimes|"
             r"prabhatkhabar|livehindustan|news|samachar|herald|chronicle|gazette|"
             r"pharmabiz|biospectrumindia|healthworld|ehealth\.eletsonline|"
             r"economictimes|moneycontrol|businesstoday|thequint|yourstory|inc42|bfsi)"),
    ("insurance_scheme", r"(policyx|policybazaar|healthinsuranceindia|iffcotokio|insurancedekho|"
                         r"newindia\.co\.in|starhealth|cashlesshospitalindia|careinsurance|"
                         r"smcinsurance|policy\.online|ayushmancardhospitals|nivabupa|"
                         r"hdfcergo|icicilombard|bajajallianz|tataaig|adityabirla|"
                         r"manipalcigna|reliancegeneral|godigit|acko|sbigeneral|"
                         r"orientalinsurance|uiic|futuregenerali|cholainsurance|"
                         r"kotakgeneral|royalsundaram|universalsompo|insurance|"
                         r"tpa|mediassist|paramounttpa|cashless|networkhospital|"
                         r"turtlemint|coverfox|renewbuy|beshak|zurichkotak)"),
    ("health_aggregator", r"(practo|justdial|lybrate|credihealth|medindia|onefivenine|docindia|"
                          r"hexahealth|medicineindia|healthfrog|drlogy|clinicspots|myupchar|"
                          r"whatclinic|skedoc|watchdoq|kivihealth|eka\.care|1mg\.com|apollo247|"
                          r"sehat\.com|bajajfinservhealth|cardiologistindia|myhospitalnow|"
                          r"joonsquare|diagnosticcentres|gynecologistnearme|proceed\.fit|"
                          r"mediyaar|medifee|365doctor|doctoriduniya|indiadentalclinic|"
                          r"clinicbooking|medsurgeindia|vaidam|secondmedic|ohohomeopathy|"
                          r"dentistinsider|hospitalsnearme|wefocusoncare|clinicspotsindia|"
                          r"indiadentalworld|hospidigital|goaid|eldercare\.nears|hospitalby|"
                          r"swheal|americanhealthtourism|bookmerilab|prognohealth|banodoctor|"
                          r"healthtourismkerala|kayawell|timesmed|medicalkerala|doctorskerala|"
                          r"quickerala|westernsurgical|sulekha|marham|docprime|healthgrades|"
                          r"curofy|medibuddy|tata1mg|pharmeasy|netmeds|hospitalsnear|"
                          r"doctorsnear|nearme|healthians|bookmyscans|labsnearme|vinsfertility|"
                          r"zocdoc|mfine|docterz|sehatq|ziffytech|doctoruna|hospitalsindia|doctorsgallery|"
                          r"mpdoctors|doctor360|clinic4all|weenear|placidway|medigence|quickobook|"
                          r"docmitra|meddco|karetrip|medifyhome|qanomed|getwellgo|mymedicaltour|"
                          r"hospitalskerala|morbidoctor|doctormyfriend|freemedicalinfo)"),
    ("maps_geo", r"(mappls|mapmyindia|latlong\.net|mapcarta|wanderlog|wikimapia|near-place|cybo\.com|"
                 r"pincode|mapsofindia|uber\.com|google\.|goo\.gl|openstreetmap|here\.com|"
                 r"bing\.com|waze|indiabyroad|placedigger|nearplace|getpincode|"
                 r"geoview|map|places|tripadvisor|makemytrip|justdialmap)"),
    ("business_dir", r"(indiamart|proptiger|chotu\.com|grotal|bdir\.in|zoominfo|zaubacorp|tracxn|"
                     r"dnb\.com|crunchbase|bharatibiz|tradeindia|ambitionbox|magicpin|shuru\.co|"
                     r"exportersindia|jupiteryellowdetail|5bestincity|threebestrated|indiainfo|"
                     r"yappe|dwello|housing\.com|rentechdigital|indiaonapage|gconnect|zoompo|"
                     r"rajasthanlink|seminarsonly|asklaila|yellowpages|tofler|glassdoor|"
                     r"naukri|indeed|apna\.co|foundit|monsterindia|owler|"
                     r"companycheck|falconebiz|instafinancials|thecompanycheck|"
                     r"nobroker|99acres|magicbricks|squareyards|commonfloor|"
                     r"foujiadda|yelp|hotfrog|cylex|brownbook|finda|"
                     r"listing|directory|yellow|business|india\.com$|"
                     r"contouravision\.myalcon|angels-initiative)"),
    ("education", r"(\.ac\.in$|\.edu(\.in)?$|collegedunia|shiksha|careers360|mbbscouncil|"
                  r"collegedekho|getmyuni|universitykart|college|university|nmc\.org|"
                  r"natboard|nbe\.edu)"),
    ("crowdfunding_ngo", r"(impactguru|ketto|milaap|givetoindia|giveindia|guidestar|ngodarpan|"
                         r"\.ngo$|charity|donate)"),
]
RULES.append(("other_health_site", r"(hospital|clinic|health|medical|dental|doctor|diagnos|"
                                   r"patholog|ivf|fertility|eye|heart|cardi|ortho|neuro|"
                                   r"cancer|onco|maternity|nursing|care|surgi|dent|derma|"
                                   r"skin|lab|scan|imaging|kidney|neph|dialysis|ayur|homeo)"))
COMPILED = [(c, re.compile(p)) for c, p in RULES]
NOT_RESEARCH = re.compile(r"(freepressjournal|thecsrjournal|livejournal)")

GENERIC_NAME_TOKENS = {
    "hospital", "hospitals", "clinic", "clinics", "the", "and", "dr", "multi", "speciality",
    "specialty", "super", "care", "centre", "center", "health", "healthcare", "medical", "dental",
    "nursing", "home", "pvt", "ltd", "private", "limited", "of", "&", "eye", "and", "research",
    "institute", "diagnostic", "diagnostics", "lab", "labs", "multispeciality",
}


def name_key(name):
    toks = re.findall(r"[a-z0-9]+", (name or "").lower())
    return "".join(t for t in toks if t not in GENERIC_NAME_TOKENS)


def classify(h, official_hosts, name):
    """Return the source class for host h given the record's officialWebsite hosts and name.
    'official' = host is the record's officialWebsite; 'official_like' = host label contains
    the distinctive part of the facility name (may be a sister branch, see q1)."""
    if NOT_RESEARCH.search(h):  # 'journal' in a newspaper or blog host
        return "news" if "livejournal" not in h else "social"
    for c, rx in COMPILED[:8]:  # research..aggregator: always win over name match
        if rx.search(h):
            return c
    # after the third-party rules: officialWebsite sometimes holds a practo/justdial URL
    if h in official_hosts:
        return "official"
    label = h.split(".")[0] if not h.startswith("m.") else h.split(".")[1]
    nk = name_key(name)
    if len(nk) >= 4 and fuzz.partial_ratio(nk, re.sub(r"[^a-z0-9]", "", label)) >= 85:
        return "official_like"
    for c, rx in COMPILED[8:]:
        if rx.search(h):
            return c
    return "other"


if __name__ == "__main__":
    assert classify("pmc.ncbi.nlm.nih.gov", set(), "X") == "research"
    assert classify("pushpanjaligroup.com", set(), "X") != "research"
    assert classify("freepressjournal.in", set(), "X") == "news"
    assert classify("practo.com", set(), "X") == "health_aggregator"
    assert classify("rainbowhospitalkolhapur.com", set(), "Rainbow Hospital") == "official_like"
    assert classify("abc.com", {"abc.com"}, "X") == "official"
    assert classify("practo.com", {"practo.com"}, "X") == "health_aggregator"
    assert classify("jalandhar.nic.in", set(), "X") == "government"
    assert classify("en.wikipedia.org", set(), "X") == "wikipedia"
    print("domains.py self-check ok")
