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

### I tre livelli

| Livello | Da dove | Voci | Cosa e | Dimensioni |
|---|---|---:|---|---|
| **Titolari** | SPARQL, `dct:rightsHolder` | 1.614 | L'ente proprietario dei dati | si |
| Organizzazioni | SPARQL, `dcat:contactPoint` | 398 | Chi ospita il catalogo di origine | si |
| Editori | API, `dct:publisher` | 1.608 | Il valore grezzo monitorato da EDP | no |

Titolari e Organizzazioni sono le due viste della pagina. Gli **Editori** restano
calcolati in `mqa/storico.csv` ma fuori dalla pagina: sono il livello che EDP
espone nelle API, utile solo per spiegare perche i numeri del portale europeo non
coincidono con questi.

Il livello **titolare** e l'unico corretto quando una PA pubblica tramite il
catalogo di qualcun altro. Il Comune di Montemesola ha 40 dataset sul portale
regionale pugliese: su EDP arrivano con publisher "Redazione OD" e contact point
`regione-puglia`, quindi ai primi due livelli il Comune non compare affatto.
Il titolare sopravvive solo nel triplestore, dove `dct:rightsHolder` porta al nome
e al codice IPA (`c_f563`).

### Le cinque dimensioni

Reperibilita, accessibilita, interoperabilita, riusabilita e contesto arrivano
solo dal triplestore: l'API di ricerca espone il solo totale, e via REST
costerebbero una chiamata per dataset (misurato: ~90 minuti e rate limit oltre gli
8 thread). Con SPARQL sono due query aggregate da ~45 secondi in tutto.

Nota su `dct:hasPart`: dati.gov.it dichiara i sotto-cataloghi nel `catalog.ttl`,
ma EDP appiattisce la gerarchia in harvesting e nel triplestore non ne resta
traccia. Il legame con l'organizzazione passa quindi da `dcat:contactPoint`.

Il titolare e comunque l'unico livello: reperibilita,
accessibilita, interoperabilita, riusabilita e contesto, che l'API di ricerca non
espone e che via REST costerebbero una chiamata per dataset.

`mqa_sparql.py` le raccoglie tutte con una sola query aggregata (~35 secondi,
9.684 misure), senza carico su dati.gov.it. Il namespace delle metriche e
`https://piveau.eu/ns/voc#`; ogni dataset vive nel proprio grafo, le misure in
`.../metrics/<id>`.

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

Il livello `publisher` resta comunque disponibile: nella pagina con il menu
*Editori*, e per il report Markdown con `mqa_monitor.py --group-by publisher`.

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

## Pagina pubblica

`build_site.py` ricostruisce la serie storica e genera i dati della pagina:

```bash
python3 build_site.py --catalog dati-gov-it
```

Produce `mqa/storico.csv` (una riga per ente per livello per rilevazione, per
analisi offline) e `docs/data.json`, letto da `docs/index.html`.

Entrambi i livelli — **organizzazioni** ed **editori** — vengono calcolati dagli
stessi snapshot, senza riscaricare nulla: ogni riga di `mqa/dataset/*.csv.gz`
porta gia `org_uuid`, `org_slug` e `publisher`. Nella pagina si passa dall'uno
all'altro con il primo menu a tendina.

`docs/data.json` tiene le ultime 104 rilevazioni (due anni), regolabile con
`--max-rilevazioni`. Lo storico completo resta in `mqa/storico.csv` e negli
snapshot.

Lo storico non viene appeso ma **ricalcolato** ogni volta a partire dagli snapshot
in `mqa/dataset/`: un run ripetuto o fallito non lascia righe duplicate, e
cancellare uno snapshot lo toglie anche dallo storico.

Per pubblicarla: *Settings -> Pages -> Source: Deploy from a branch -> `main` /
`docs`*. Per vederla in locale serve un server HTTP, perche la pagina carica
`data.json` via fetch:

```bash
cd docs && python3 -m http.server
```

### Link diretti

Ogni ente ha un indirizzo condivisibile:

```
https://piersoft.github.io/mqa-monitor/?titolare=c_f563
https://piersoft.github.io/mqa-monitor/?titolare=Comune%20di%20Montemesola
https://piersoft.github.io/mqa-monitor/?organizzazione=comune-di-torino
```

Accetta il codice (IPA per i titolari, slug o UUID per le organizzazioni) oppure
il nome, anche parziale. Il livello si imposta da solo e la riga si apre gia
espansa. Aprendo una riga l'indirizzo si aggiorna, quindi si copia dalla barra
del browser.

GitHub Pages serve solo file statici, ma la query string arriva comunque al
browser: la risoluzione avviene lato client in `docs/index.html`, senza bisogno
di rewrite lato server.

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
