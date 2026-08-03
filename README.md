# Monitoraggio MQA — data.europa.eu

Rilevazione giornaliera del punteggio MQA (Metadata Quality Assessment) che
data.europa.eu assegna ai dataset di dati.gov.it, aggregato **per ente** e con
confronto storico.

Pagina pubblica: <https://piersoft.github.io/mqa-monitor/>

Nasce per il catalogo `dati-gov-it`, ma funziona con qualsiasi catalogo del
portale europeo.

---

## Il problema

Il portale europeo espone il punteggio dataset per dataset, ma non un modo per
scorrerli tutti né per aggregarli per ente: restava il controllo manuale, uno
alla volta. E soprattutto il livello che EDP monitora — `dct:publisher` — su un
catalogo federato come dati.gov.it non identifica nessuno: sono uffici, redazioni
e denominazioni interne.

## I tre livelli

| Livello | Fonte | Voci | Cosa è | Dimensioni |
|---|---|---:|---|---|
| **Titolari** | SPARQL, `dct:rightsHolder` | 1.614 | L'ente proprietario dei dati | sì |
| **Organizzazioni** | SPARQL, `dcat:contactPoint` | 398 | Chi ospita il catalogo di origine | sì |
| Editori | API, `dct:publisher` | 1.608 | Il valore grezzo monitorato da EDP | no |

I primi due sono le viste della pagina. Gli **editori** restano calcolati in
`mqa/storico.csv` ma fuori dalla pagina: servono solo a spiegare perché i numeri
del portale europeo non coincidono con questi.

### Perché il titolare

Il Comune di Montemesola ha 40 dataset, pubblicati sul portale regionale
pugliese. Su EDP arrivano con publisher `Redazione OD` e contact point
`regione-puglia`: ai primi due livelli il Comune **non compare affatto**.

Il titolare sopravvive solo nel triplestore, dove `dct:rightsHolder` porta al
nome e al codice IPA (`c_f563`). L'API di ricerca non lo espone.

Vale anche il contrario: `dct:publisher` produce 1.637 voci contro 398
organizzazioni, e il publisher più frequente di Regione Marche risulta "Comune di
Civitanova Marche", quello del MEF "Open", quello di Regione Puglia
"Redazione OD".

### Perché non `dct:hasPart`

dati.gov.it dichiara i sotto-cataloghi nel proprio `catalog.ttl`, ma EDP
appiattisce la gerarchia in harvesting: nel triplestore il grafo del catalogo
contiene solo `dcat:dataset`, `dcat:record` e `dcat:service`. Il legame con
l'organizzazione passa quindi da `dcat:contactPoint`, che è un URI diretto
(`https://www.dati.gov.it/organization/<uuid>`) e si raggruppa nativamente.

## Le cinque dimensioni

Reperibilità, accessibilità, interoperabilità, riusabilità e contesto arrivano
solo dal triplestore. L'API di ricerca espone il solo totale, e via REST
costerebbero una chiamata per dataset — misurato: ~90 minuti e rate limit oltre
gli 8 thread paralleli. Con SPARQL sono due query aggregate, ~45 secondi in
tutto, e nessun carico su dati.gov.it.

Dettagli utili per chi volesse rifare le query:

- ogni dataset vive nel proprio grafo, il cui URI coincide con quello del dataset
- le misure stanno in `.../metrics/<id>`
- il namespace delle metriche è `https://piveau.eu/ns/voc#` (non
  `europeandataportal.eu`, che restituisce risultati vuoti senza errore)

## Come funziona

```
mqa_sparql.py    →  mqa/titolari/<cat>_<data>.csv        ogni giorno,  ~45 s
                    mqa/organizzazioni/<cat>_<data>.csv
mqa_monitor.py   →  mqa/dataset/<cat>_<data>.csv.gz      solo lunedì,  ~25 s
                    mqa/aggregato/<cat>_<livello>_<data>.csv
                    mqa/report_<cat>_<livello>_<data>.md
build_site.py    →  mqa/storico.csv                      ogni giorno
                    docs/data.json
```

`mqa_monitor.py` usa il parametro `scroll=true` dell'API di ricerca: la
paginazione normale si ferma a 10.000 risultati, lo scroll no. Restituisce uno
`scrollId` da riusare su `/api/hub/search/scroll`, e con
`includes=id,publisher.name,quality_meas.scoring,contact_point` scarica 64.656
dataset in circa 25 secondi.

`build_site.py` **ricostruisce** ogni volta storico e dati della pagina a partire
dagli snapshot: un run ripetuto o fallito non lascia righe duplicate, e cancellare
uno snapshot lo toglie anche dallo storico. In cambio, quei file sono l'unica
fonte — non vanno eliminati per fare spazio.

Lo storico completo è comunque il `git log`: ogni rilevazione è un commit.

## Cadenza

Il workflow gira **ogni mattina** alle 06:00 UTC (08:00 italiane in ora legale,
07:00 in ora solare), perché EDP ricalcola quasi ogni giorno mentre l'harvesting
di dati.gov.it chiude il sabato sera: con la rilevazione settimanale, tra la
correzione di un ente e la sua verifica potevano passare tredici giorni.

Non tutto però gira ogni giorno:

| Passo | Cadenza | Peso per run |
|---|---|---:|
| SPARQL (titolari, organizzazioni) | ogni giorno | 177 KB, testo comprimibile |
| Scroll dell'API (`.csv.gz`) | solo lunedì | 1.056 KB, già compresso |

Il `.csv.gz` non si comprime in git: a cadenza giornaliera sarebbero ~385 MB
l'anno. Serve solo per i nomi leggibili delle organizzazioni e per il livello
editori, che non cambiano in un giorno. L'input `forza_scroll` lo esegue comunque.

La colonna **7 giorni** confronta con la rilevazione più vicina a una settimana
prima, non con quella del giorno precedente: una variazione giornaliera è spesso
rumore — un server che non risponde per un'ora fa scendere l'accessibilità e
risalire il giorno dopo.

`docs/data.json` tiene tutte le rilevazioni degli ultimi 60 giorni e poi una a
settimana: con 2.000 enti ogni rilevazione pesa ~30 KB, e un anno di dati
giornalieri renderebbe la pagina inutilizzabile. Lo storico integrale resta in
`mqa/storico.csv`.

## Soglie di rating

| Rating | Punteggio |
|---|---|
| Excellent | 351–405 |
| Good | 221–350 |
| Sufficient | 121–220 |
| Bad | 0–120 |

Le cinque dimensioni valgono rispettivamente 100, 100, 110, 75 e 20 punti.

## Perché il totale non coincide con quello di data.europa.eu

Per l'intero catalogo `dati-gov-it` il portale europeo pubblica **371/405**,
questa pagina una media più bassa. Non è una discrepanza: sono due statistiche
diverse.

- **EDP** costruisce un dataset "rappresentativo", applicando ai pesi massimi la
  percentuale di successo di ogni controllo, arrotondata all'unità.
- **Qui** si fa la media aritmetica dei punteggi dei singoli dataset.

| Dimensione | Qui | EDP |
|---|---:|---:|
| Findability | 99,9 | 100 |
| Accessibility | 64,4 | 72 |
| **Interoperability** | **69,5** | **104** |
| Reusability | 74,4 | 75 |
| Contextuality | 20,0 | 20 |

Quattro dimensioni su cinque coincidono quasi perfettamente: quasi tutto lo scarto
sta nell'interoperabilità, perché quei controlli si applicano alle
*distribuzioni* e non ai dataset. Un dataset con dieci distribuzioni di cui una
proprietaria perde punti nel proprio punteggio, ma nel conteggio aggregato pesa
nove "sì" contro un "no".

Per capire chi deve migliorare cosa serve la media dei punteggi, che si scompone
per ente. Il valore ufficiale viene comunque letto a ogni run da
`api/mqa/cache/catalogues/<catalogo>` e mostrato in fondo alla pagina.

## Esecuzione locale

Solo libreria standard, nessuna dipendenza. Serve Python ≥ 3.8.

```bash
python3 mqa_sparql.py --catalog dati-gov-it     # titolari e organizzazioni
python3 mqa_monitor.py --outdir ./mqa           # scroll dell'API + report
python3 build_site.py --catalog dati-gov-it     # storico e dati della pagina
```

La pagina va servita via HTTP, perché carica `data.json` via fetch:

```bash
cd docs && python3 -m http.server
```

## Link diretti

Ogni ente ha un indirizzo condivisibile:

```
https://piersoft.github.io/mqa-monitor/?titolare=c_f563
https://piersoft.github.io/mqa-monitor/?titolare=Comune%20di%20Montemesola
https://piersoft.github.io/mqa-monitor/?organizzazione=comune-di-torino
```

Accetta il codice (IPA per i titolari, slug o UUID per le organizzazioni) oppure
il nome, anche parziale. Il livello si imposta da solo e la riga si apre già
espansa. Aprendo una riga l'indirizzo si aggiorna, quindi si copia dalla barra del
browser.

GitHub Pages serve solo file statici, ma la query string arriva comunque al
browser: la risoluzione avviene lato client, senza rewrite lato server.

## Pubblicazione

*Settings → Pages → Deploy from a branch → `main` / `docs`*. Serve
`docs/.nojekyll`, altrimenti Pages passa i file a Jekyll e pubblica il README al
posto di `index.html`.

## Titoli leggibili degli enti

L'etichetta delle organizzazioni viene risolta in cascata: `mqa/org_titles.json`
se presente, poi l'API CKAN di dati.gov.it, poi come fallback la titolazione dello
slug (`comune-di-milano` → "Comune di Milano"), che copre bene ma perde gli
accenti (`Citta Metropolitana di Napoli`).

Per rigenerare il file dei titoli:

```bash
curl -s "https://www.dati.gov.it/opendata/api/3/action/organization_list?all_fields=true&limit=1000" \
  | python3 -c "import json,sys; d=json.load(sys.stdin)['result']; \
    json.dump({o['name']: o.get('title') or o['name'] for o in d}, \
    open('mqa/org_titles.json','w'), ensure_ascii=False, indent=1, sort_keys=True)"
```

L'API può rispondere 403 da alcuni IP: in quel caso lo script prosegue con i
titoli già presenti o con il fallback.

## Limiti noti

- Il livello SPARQL copre 61.510 dataset contro i 64.656 dello scroll: la
  differenza sono quelli privi di misure di qualità nel triplestore. Le medie
  restano confrontabili, i conteggi assoluti no.
- L'endpoint SPARQL è pubblico e senza SLA: rifiuta le query la cui stima di
  esecuzione supera i 60 secondi. Nel workflow lo step è `continue-on-error`,
  così un rifiuto non blocca il resto.
- Gli editori sono identificati per nome testuale: una PA che si rinomina risulta
  "sparita + nuova". Titolari e organizzazioni usano chiavi stabili (codice IPA e
  UUID).
