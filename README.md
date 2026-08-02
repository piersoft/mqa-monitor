# Monitoraggio MQA — data.europa.eu

Rilevazione settimanale dello scoring MQA (Metadata Quality Assessment) di
[data.europa.eu](https://data.europa.eu/data/combined) **per organizzazione titolare del
catalogo di origine** (Comune di Milano, INPS, Regione Toscana...), con confronto
automatico rispetto alla settimana precedente.

Nasce per il catalogo `dati-gov-it`, ma funziona con qualsiasi catalogo del portale.

## Come funziona

L'API di ricerca di data.europa.eu espone lo scoring in `quality_meas.scoring`
(scala 0–405). La paginazione classica si ferma a 10.000 risultati: per scorrere
un catalogo intero serve il parametro `scroll=true`, che restituisce uno
`scrollId` da riusare su `/api/hub/search/scroll`.

Lo script:

1. scorre l'intero catalogo (~65.000 dataset per `dati-gov-it`, ~25 secondi);
2. aggrega per ente — n. dataset, media, mediana, min, max, rating MQA,
   quanti dataset *Excellent* e quanti *Bad*, quanti `dct:publisher` distinti;
3. salva due snapshot datati:
   - `mqa/aggregato/<catalogo>_<livello>_<data>.csv` — l'aggregato,
   - `mqa/dataset/<catalogo>_<data>.csv.gz` — il dettaglio per dataset,
     utile per capire *quali* dataset hanno fatto scendere un ente;
4. confronta con lo snapshot precedente e genera
   `mqa/report_<catalogo>_<livello>_<data>.md` con chi sale, chi scende, i nuovi
   enti e quelli spariti.

### Perche non `dct:publisher`

data.europa.eu monitora `dct:publisher`, che su un catalogo federato come
dati.gov.it e' inaffidabile come unita di analisi: contiene uffici, redazioni e
denominazioni interne. Nel catalogo attuale i publisher distinti sono 1.637
contro 398 organizzazioni, e il publisher piu frequente di Regione Marche
risulta "Comune di Civitanova Marche", quello del MEF "Open", quello di Regione
Puglia "Redazione OD".

Il legame con l'ente reale sta in `contact_point.resource`, che su ogni dataset
harvestato da dati.gov.it punta a
`https://www.dati.gov.it/organization/<uuid>` (copertura verificata: 100% dei
64.656 dataset). Lo script usa quell'UUID come chiave: resta stabile anche se
l'ente cambia denominazione.

Il livello `publisher` resta disponibile con `--group-by publisher`.

### Titoli leggibili degli enti

L'etichetta viene risolta in cascata: `mqa/org_titles.json` se presente, poi
l'API CKAN di dati.gov.it, poi come fallback la titolazione dello slug
(`comune-di-milano` -> "Comune di Milano"), che copre bene ma perde gli accenti
(`Citta Metropolitana di Napoli`).

Per rigenerare il file dei titoli:

```bash
curl -s "https://www.dati.gov.it/opendata/api/3/action/organization_list?all_fields=true&limit=1000" \
  | python3 -c "import json,sys; d=json.load(sys.stdin)['result']; \
    json.dump({o['name']: o.get('title') or o['name'] for o in d}, \
    open('mqa/org_titles.json','w'), ensure_ascii=False, indent=1, sort_keys=True)"
```

Lo storico è il `git log`: ogni run è un commit.

## Soglie di rating

| Rating | Punteggio |
|---|---|
| Excellent | 351–405 |
| Good | 221–350 |
| Sufficient | 121–220 |
| Bad | 0–120 |

## Esecuzione locale

Solo libreria standard, nessuna dipendenza. Serve Python ≥ 3.8.

```bash
python3 mqa_monitor.py --outdir ./mqa --min-datasets 5 --top 25
python3 mqa_monitor.py --catalog dados-gov-pt        # altro catalogo
```

Al primo run non c'è confronto: quello snapshot è la baseline.

## Automazione

`.github/workflows/mqa-weekly.yml` gira ogni domenica alle 10:00 UTC
(12:00 italiane in ora legale, 11:00 in ora solare), committa lo snapshot e
apre una issue con il report. Avviabile anche a mano da *Actions →
Run workflow*, scegliendo catalogo e soglie.

## Limiti noti

- L'API espone solo lo **score totale**, non le cinque dimensioni
  (findability, accessibility, interoperability, reusability, contextuality).
- Con `--group-by publisher` gli enti sono identificati per **nome testuale**:
  una PA che cambia denominazione risulta come "sparito + nuovo". Con
  l'aggregazione per organizzazione (default) il problema non si pone.
- L'API CKAN di dati.gov.it puo rispondere 403 da alcuni IP: in quel caso lo
  script prosegue con i titoli gia in `org_titles.json` o con il fallback.
