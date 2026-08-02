# Monitoraggio MQA — data.europa.eu

Rilevazione settimanale dello scoring MQA (Metadata Quality Assessment) di
[data.europa.eu](https://data.europa.eu/data/combined) **per publisher**, con
confronto automatico rispetto alla settimana precedente.

Nasce per il catalogo `dati-gov-it`, ma funziona con qualsiasi catalogo del portale.

## Come funziona

L'API di ricerca di data.europa.eu espone lo scoring in `quality_meas.scoring`
(scala 0–405). La paginazione classica si ferma a 10.000 risultati: per scorrere
un catalogo intero serve il parametro `scroll=true`, che restituisce uno
`scrollId` da riusare su `/api/hub/search/scroll`.

Lo script:

1. scorre l'intero catalogo (~65.000 dataset per `dati-gov-it`, ~25 secondi);
2. aggrega per publisher — n. dataset, media, mediana, min, max, rating MQA,
   quanti dataset *Excellent* e quanti *Bad*;
3. salva due snapshot datati:
   - `mqa/publisher/<catalogo>_<data>.csv` — l'aggregato,
   - `mqa/dataset/<catalogo>_<data>.csv.gz` — il dettaglio per dataset,
     utile per capire *quali* dataset hanno fatto scendere un publisher;
4. confronta con lo snapshot precedente e genera
   `mqa/report_<catalogo>_<data>.md` con chi sale, chi scende, i nuovi
   publisher e quelli spariti.

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
- I publisher sono identificati per **nome testuale**: se una PA cambia
  denominazione nel catalogo di origine, risulterà come "sparito + nuovo".
