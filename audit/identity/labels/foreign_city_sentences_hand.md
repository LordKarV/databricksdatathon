Hand check of out/foreign_city_sentences.csv (does the sentence describe a different site or entity?)
Chain sample (random_state=3, 20 rows): 18 yes, 2 no (both Manipal Baner: Baner is a Pune locality, own-place check missed it).
Non-chain sample (random_state=5, 20 rows): 13 yes, 7 no. The 7 no: Bangur (Kolkota vs kolkata spelling),
Srinivasa (doctor's education in Hyderabad), Meera Kalyan (Ulhasnagar is the same district), Kalp ('Jodhpur Cross Road'
is an Ahmedabad locality), Mrinmayee (Chembur is in Mumbai), CritiCare Kurla (Kurla is in Mumbai), Deepam (Guduvancheri near Chennai).
Tertiary claims at small chain sites (out/chain_small_site_tertiary_claims.csv, 9 records): 4 look inherited
(Apollo Clinic Beliaghata kidney transplant, The Apollo Clinic Nashik bypass surgery, Apollo Clinic Ghaziabad lung
transplant, Apollo Clinic Manikonda renal transplantation); 2 are visiting-consultant claims stated as services
(Apollo Clinic Raipur liver transplant consult, Apollo Clinic Hanamkonda neurosurgeon); 2 are detector errors
(SAAOL Surat 'Does not perform bypass surgery' is a negation; Belle Vue Clinic Kolkata is a large hospital despite its name);
1 uncertain (HCG Aastha Cancer Centre Ahmedabad typed clinic, liver transplant and neurosurgery claims).
