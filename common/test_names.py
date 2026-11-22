"""display_name: the address tail goes, an official name with its town stays. Run: pytest common -q"""
import pytest

from common.names import display_name


@pytest.mark.parametrize("raw, shown", [
    ("Phular Superspeciality Hospital, Road No-02, Juran Chappra, Muzaffarpur - 842001", "Phular Superspeciality Hospital"),
    ("Navjeevan Heart and Women's Hospital - Near Horizon Hotel, GIDC Ankleshwar, 393002", "Navjeevan Heart and Women's Hospital"),
    ("Pathkind Labs, Shop No 1, Block Ba, Dda Market, Shalimar Bagh, Delhi 110088", "Pathkind Labs"),
    ("Hi-Tech Emergency Hospital \u2013 Saguna More, Bailey Road, Patna-801503", "Hi-Tech Emergency Hospital"),
    ("The Dental Masters - SCO 8 First Floor, Sector 21-C, Chandigarh", "The Dental Masters"),
    ("Paras Dental Care Clinic 2 - 505, Laxman Path, Jaipur", "Paras Dental Care Clinic 2"),
    ("Devdikar Dialysis, Sahakarnagar, Nr New S T Stand, Akluj", "Devdikar Dialysis"),
    ("Medicity Laboratory - 12 No. Indra Biswas Road, Kolkata - 700037", "Medicity Laboratory"),
    # kept: the part after the comma or dash is a town or part of the name, not an address
    ("Patna Hospital & Research Centre, Patna", "Patna Hospital & Research Centre, Patna"),
    ("RAM HOSPITAL & RESEARCH CENTRE, KANPUR", "RAM HOSPITAL & RESEARCH CENTRE, KANPUR"),
    ("Multi-Speciality Hospital - 24x7 Care", "Multi-Speciality Hospital - 24x7 Care"),
    ("Dr. S Memorial Radio- Diagnostic Center", "Dr. S Memorial Radio- Diagnostic Center"),
    ("Sub Divisional Hospital Pusa", "Sub Divisional Hospital Pusa"),
    ("Branch - 2M&M Ortho Multispeciality Hospitals", "Branch - 2M&M Ortho Multispeciality Hospitals"),
    # a possessive the source title-cased is shown in lower case; an all-caps name keeps its case
    ("Pawar'S Clinic", "Pawar's Clinic"),
    ("Dr Swathi'S Children Clinic - Nallagandla, Hyderabad", "Dr Swathi's Children Clinic - Nallagandla, Hyderabad"),
    ("Amma Children\u2019S Hospital", "Amma Children\u2019s Hospital"),
    ("SAMAL'S ADVANCED DENTAL CARE", "SAMAL'S ADVANCED DENTAL CARE"),
    ("Samved IVF & WOMEN'S Hospital", "Samved IVF & WOMEN'S Hospital"),
    ("Pawar'S", "Pawar's"),
    (None, None),
])
def test_display_name(raw, shown):
    assert display_name(raw) == shown
