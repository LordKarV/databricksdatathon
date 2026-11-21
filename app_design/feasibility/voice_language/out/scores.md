### databricks-gemma-3-12b

| set | lang | service correct | red flag agrees (scored cases) | phrase verbatim |
| --- | --- | --- | --- | --- |
| main | en | 8/8 | 8/8 | 8/8 |
| main | hi | 8/8 | 8/8 | 8/8 |
| main | hinglish | 8/8 | 7/7 | 7/8 |
| main | mr | 6/6 | 6/6 | 6/6 |
| hard | bn | 1/1 | 1/1 | 1/1 |
| hard | hinglish | 2/4 | 2/3 | 3/4 |
| hard | ta | 1/1 | 1/1 | 1/1 |
| main | all | 30/30 | 29/29 | 29/30 |
| hard | all | 4/6 | 4/5 | 5/6 |

Calls: 36. Errors (call or schema): 0. Latency ms (wall, incl. CLI start): median 1116, p90 2279, max 4211.

Service misses:
- X2 `pet mein pathri hai, kidney mein bahut dard` expected other / rf None; got icu / urgent / rf False / phrase `kidney mein bahut dard`
- X4 `seene mein tez dard, pasina aa raha hai, baayan haath sunn` expected ['other', 'icu', 'cardiac_surgery'] / rf True; got trauma / emergency / rf True / phrase `बाayan haath sunn`
Red-flag disagreements:
- X3 `bachcha 2 saal ka hai, garam doodh gir gaya poore pet aur chhati pe` expected burns / rf True; got burns / urgent / rf False / phrase `garam doodh gir gaya poore pet aur chhati pe`
Decisive phrase not verbatim:
- G5 `bete ke dil mein chhed hai, doctor ne operation bola hai` expected cardiac_surgery / rf False; got cardiac_surgery / urgent / rf False / phrase `dil mein chhed hai, operation bola hai`
- X4 `seene mein tez dard, pasina aa raha hai, baayan haath sunn` expected ['other', 'icu', 'cardiac_surgery'] / rf True; got trauma / emergency / rf True / phrase `बाayan haath sunn`

### databricks-meta-llama-3-3-70b-instruct

| set | lang | service correct | red flag agrees (scored cases) | phrase verbatim |
| --- | --- | --- | --- | --- |
| main | en | 8/8 | 8/8 | 8/8 |
| main | hi | 8/8 | 8/8 | 8/8 |
| main | hinglish | 8/8 | 7/7 | 8/8 |
| main | mr | 6/6 | 6/6 | 6/6 |
| hard | bn | 1/1 | 1/1 | 1/1 |
| hard | hinglish | 4/4 | 3/3 | 4/4 |
| hard | ta | 1/1 | 1/1 | 1/1 |
| main | all | 30/30 | 29/29 | 30/30 |
| hard | all | 6/6 | 5/5 | 6/6 |

Calls: 36. Errors (call or schema): 0. Latency ms (wall, incl. CLI start): median 876, p90 2321, max 4775.

Service misses: none
Red-flag disagreements: none
Decisive phrase not verbatim: none
