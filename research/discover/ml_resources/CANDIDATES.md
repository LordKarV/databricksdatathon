# ML datasets and models for the facility finder

Discovery step, 2026-11-21. Nothing was downloaded except page-sized metadata (Hugging Face API JSON, HDX CKAN JSON, a 6 KB STAC metadata file) and two PDFs that WebFetch cached while reading them (HBP 2.1 master, 2.2 MB; IPHS 2022 Vol 1, 2.8 MB). No Databricks objects were touched.

## Facts from our own data that shape the model choice

Measured with duckdb on data/raw/facilities.parquet (script in scratchpad, not kept):

- The four claim list columns hold 730,568 sentence items: specialties 278,994, procedure 163,791, equipment 56,052, capability 231,731. 288,493 are unique strings, average 32.9 characters. So the "about 100k sentences" planning figure is low by roughly 3x for unique strings.
- Only 11 of 10,088 rows contain any Indic-script character (U+0900 to U+0DFF) in name, description, procedure or capability. Facility text is effectively English. Indic models matter for user queries (Hindi place names, a Hindi UI), not for the evidence text.
- Workspace (from audit/capabilities/CAPABILITIES.md): no GPU, no classic clusters; Apps run on 2 vCPU / 6 GB; READY embedding endpoints databricks-gte-large-en, databricks-bge-large-en, databricks-qwen3-embedding-0-6b; ai_query chat models work but gave confidence 1.0 on contaminated records.

## CPU feasibility, how to read it

No local benchmark was run: torch and onnxruntime are not installed in the project venv, and this step forbids model downloads. The only published CPU figure found is on https://www.sbert.net/docs/sentence_transformer/pretrained_models.html: multi-qa-MiniLM-L6-cos-v1 at "18,000 (GPU) / 750 (CPU)" queries per second, hardware not named. The per-model estimates below scale that by parameter count and are unverified. They should be measured on the App's 2 vCPU before relying on them.

Rough rule (unverified): 22M models are a few minutes per 100k sentences; 118M models about 10 minutes; 280M models 20 to 40 minutes; 560M models more than an hour. A cross-encoder costs about the same per pair as a bi-encoder of the same size per sentence, so the pair count matters: 288k unique sentences times 15 services is 4.3M pairs, which is infeasible on CPU. Filter with keywords or embeddings first, then run NLI on the shortlist.

## Ranked candidates

Priority 1 = must have, 5 = skip.

### Taxonomies and labels

| slug | name | priority | licence | notes |
| --- | --- | --- | --- | --- |
| pmjay_hbp_master | AB PM-JAY Health Benefit Package master (HBP 2.1 file, Bihar SHA mirror) | 1 | none stated; Government of India scheme document | 1,669 unique procedure codes, 917 package codes, 26 specialty prefixes (counted with pdftotext). Columns: Specialty Code HBP 2.0, Specialty, Package Code, Package Name, Procedure Code, Procedure Name, prices, Stratification, Implant. Examples: MG072A Haemodialysis; SO057A Caesarean Delivery; BM001A to D thermal burns by TBSA; neonatal care packages (basic to critical); ST Polytrauma. |
| iphs_2022 | Indian Public Health Standards 2022, Vol 1 (SDH and DH) and Vols 2 to 4 | 2 | none stated; "Copyright (c) 2021 ... NHSRC" | Annexure 3 "List of Service and Procedures" marks each procedure group E (essential) or D (desirable) by hospital size; haemodialysis and caesarean section appear as essential at DH. Gives facility-type priors and a public-sector service vocabulary. |
| icd10pcs_cms | ICD-10-PCS FY 2027 code files (CMS) | 3 | no licence text on page | US procedure coding; ZIPs of codes, order file, tables. Good synonyms, weak fit to Indian service names. |
| snomed_ct_india | SNOMED CT via NRCeS India (MLDS affiliate licence) | 4 | affiliate licence, MLDS registration, link "within 4-5 business days" | Best clinical vocabulary but licensed and slow to obtain; redistribution terms in the affiliate agreement PDF not read. |
| nabh_lists | NABH accreditation lists and standards | 5 | "QCI (c) 2020 All Rights Reserved" | portal.nabh.co lists only 25 self-assessment toolkits; no bulk register or per-hospital scope of services found. |

### Existing Indian facility lists (corroboration and labels)

| slug | name | priority | licence | notes |
| --- | --- | --- | --- | --- |
| hotosm_ind_health_facilities | HOTOSM India health facilities (OSM export on HDX) | 1 | ODC-ODbL | 139,664 features, snapshot 2026-10-09; GeoParquet 14.5 MB; names 97.6% complete, address 71.7%, operator 6.8%, capacity empty. Existence and location corroboration. |
| nhp_hospital_directory_2015 | Hospital Directory as on July 2015 (National Health Portal, AIKosh mirror) | 2 | "GODL license" | 449.16 KB; fields include category, systems of medicine, PIN code, website, specializations. Old but has per-hospital specializations, i.e. weak labels. |
| nin_geocoded_directory | National Hospital Directory with Geo Code (NIN, AIKosh mirror) | 2 | "GODL license" | 9.86 MB; lat/long, facility type, ownership, services. data.gov.in original refused connections from here. |
| cghs_empanelled | CGHS empanelled hospitals (AIKosh) | 4 | "GODL license" | City, name, address; no services shown; file size shown as 0. |
| healthsites_io | healthsites.io API | 4 | ODbL (site) | API key required; data largely OSM-derived, so redundant with HOTOSM. |
| gomed_hf | GoMed-Dataset (Hugging Face) | 4 | CC-BY-4.0 | 1,326 hospitals, 11,746 hospital-treatment links, 1.9 MB zip; README says generated by an ML agent, sources include Practo scrapes; viewer fails with a cast error. Use only as a spot-check. |
| hospitalsnearme | Hospitals Near Me directory | 5 | "All Rights Reserved" | 6,202 hospitals with PIN and lat/long; no reuse permission. |
| practo_scrapes | Practo doctor scrapes (GitHub, Apify) | 5 | none / Practo terms | Doctor-level personal data (names, fees, phones). Do not use. |

### Models

| slug | params | licence | CPU over 100k short sentences | role |
| --- | --- | --- | --- | --- |
| dbx_hosted_embeddings (qwen3-embedding-0.6b, gte-large-en, bge-large-en) | n/a, served | Databricks terms | no local CPU; uses daily quota, precompute once | embeddings without shipping a model; qwen3 is multilingual |
| intfloat/multilingual-e5-small | 117.7M | MIT | likely under 15 min (unverified) | default local bi-encoder for retrieval and claim-to-service matching |
| cross-encoder/nli-deberta-v3-small | 141.9M | Apache-2.0 | about 100k pairs in under an hour (unverified) | "does this sentence support service X" entailment score |
| MoritzLaurer/deberta-v3-base-zeroshot-v2.0 | 184.4M | MIT | borderline, roughly 30 to 60 min per 100k pairs (unverified) | zero-shot entailment, stronger than small |
| sentence-transformers/all-MiniLM-L6-v2 | 22.7M | Apache-2.0 | minutes | fast English baseline (text is English) |
| cross-encoder/ms-marco-MiniLM-L6-v2 | 22.7M | Apache-2.0 | minutes | cheap reranker before NLI |
| sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 | 117.7M | Apache-2.0 | under 15 min (unverified) | multilingual fallback |
| intfloat/multilingual-e5-base | 278.0M | MIT | 20 to 40 min (unverified) | better quality if time allows |
| BAAI/bge-m3 | about 568M (2,271 MB fp32 weights) | MIT | over an hour (unverified) | dense plus sparse plus multi-vector; precompute offline only |
| BAAI/bge-reranker-v2-m3 | 567.8M | Apache-2.0 | over an hour per 100k pairs (unverified) | offline reranking only |
| MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7 | 278.8M | MIT | 20 to 40 min (unverified) | multilingual NLI; Hindi XNLI 0.769 |
| MoritzLaurer/deberta-v3-large-zeroshot-v2.0 | 435.1M | MIT | over an hour (unverified) | offline silver-label generator for a small classifier |
| ai4bharat/indictrans2-indic-en-dist-200M and en-indic-dist-200M | 228.3M / 274.6M | MIT, HF gated "auto" (accept terms) | queries only, trivial volume | translate Hindi user queries; CTranslate2 checkpoints exist |
| ai4bharat/indictrans2-*-1B | 1.02B / 1.12B | MIT, gated "auto" | too slow for bulk on CPU | skip; use distilled |
| cambridgeltl/SapBERT-from-PubMedBERT-fulltext | 109.5M | Apache-2.0 | about 10 min (unverified) | map claim phrases to a service vocabulary (entity linking) |
| abhinand/MedEmbed-small-v0.1 | 33.4M | Apache-2.0 | minutes | medical-domain English embeddings |
| cambridgeltl/SapBERT-UMLS-2020AB-all-lang-from-XLMR | 278.0M | no licence tag; UMLS-derived | 20 to 40 min (unverified) | multilingual entity linking; licence unclear |
| google/muril-base-cased | about 238M (953 MB fp32) | Apache-2.0 | n/a, MLM needs fine-tuning | Indic encoder; not needed for English text |
| ai4bharat/IndicBERTv2-MLM-only | about 279M (1,116 MB fp32) | MIT | n/a, MLM needs fine-tuning | as above |
| sentence-transformers/LaBSE | 470.9M | Apache-2.0 | about an hour (unverified) | cross-lingual name matching; heavy for the gain |
| l3cube-pune/indic-sentence-similarity-sbert | about 237M (950 MB fp32) | CC-BY-4.0 | 20 to 40 min (unverified) | Indic sentence similarity; not needed for English text |

NLP training data checked: Divyanshu/indicxnli (CC0-1.0, 11 Indic languages, machine-translated XNLI) and cfilt/HiNER-original (CC-BY-SA-4.0, Hindi general-domain NER). Neither is medical; priority 5.

## Recommended stack

1. Map every claim sentence to services through the PM-JAY HBP specialty and procedure vocabulary plus a hand-written synonym list for the demo services (dialysis, C-section, NICU, cardiac surgery, MRI, burns, trauma).
2. Shortlist sentence-service pairs with keywords plus multilingual-e5-small or a Databricks-hosted embedding, precomputed once into a workspace table.
3. Score the shortlist with cross-encoder/nli-deberta-v3-small (or deberta-v3-base-zeroshot-v2.0 offline), and show the entailment score next to the quoted sentence.
4. Corroborate existence and location against HOTOSM OSM and the NIN geocoded directory; use IPHS facility-type priors as a weak prior, never as evidence.

## Access problems seen

- data.gov.in, pmjay.gov.in, hospitals.pmjay.gov.in: connection refused or no response from this machine and from WebFetch.
- nha.gov.in, facility.abdm.gov.in: HTTP 403. The NHA HBP 2.0 master and HBP 2.2 manual were therefore not read; the Bihar SHA mirror of HBP 2.1 was used instead.
- data.humdata.org dataset page: 403 to WebFetch; the CKAN API and the HOT S3 metadata worked.

## URLs

- https://biswass.bihar.gov.in/Documents/HBP-2.1.pdf
- https://pib.gov.in/PressReleasePage.aspx?PRID=1761175
- https://nhsrcindia.org/IPHS2022/iphs-2022-guidelines
- https://nhsrcindia.org/sites/default/files/Volume%201_SDH-DH_0.pdf
- https://www.cms.gov/medicare/coding-billing/icd-10-codes
- https://www.nrces.in/standards/snomed-ct
- https://portal.nabh.co/
- https://data.humdata.org/dataset/hotosm_ind_health_facilities
- https://production-raw-data-api.s3.amazonaws.com/ISO3/IND/health_facilities/hotosm_ind_health_facilities_report.html
- https://healthsites.io/api/docs/
- https://aikosh.indiaai.gov.in/home/datasets/details/hospital_directory_as_on_july_2015.html
- https://aikosh.indiaai.gov.in/home/datasets/details/national_hospital_directory_with_geo_code_and_additional_parameters_updated_till_last_month.html
- https://aikosh.indiaai.gov.in/home/datasets/details/list_of_hospitals_empaneled_under_cghs_all_over_india.html
- https://huggingface.co/datasets/Gogeta007/GoMed-Dataset
- https://hospitals.onrender.com
- https://github.com/AI4Bharat/IndicTrans2
- https://huggingface.co/api/models/<id> for each model row (licence, params, lastModified, gated)
- https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7
- https://huggingface.co/BAAI/bge-m3
- https://www.sbert.net/docs/sentence_transformer/pretrained_models.html
- https://huggingface.co/datasets/Divyanshu/indicxnli
- https://huggingface.co/datasets/cfilt/HiNER-original
