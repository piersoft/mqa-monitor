# Mappe territoriali — mqa-monitor

Due mappe aggiunte al cruscotto, servite come pagina statica su GitHub Pages.

## File

| File | Ruolo | Rigenerato |
|---|---|---|
| `build_maps.py` | genera i dati delle mappe | a ogni run |
| `docs/mappe.html` | pagina Leaflet | mai |
| `docs/comuni_coords.json` | centroidi e denominazioni degli 7.899 comuni | una tantum |
| `docs/regioni_split.geojson` | confini regionali, TN e BZ separati | una tantum |
| `docs/maps_data.json` | output di `build_maps.py` | a ogni run |

`comuni_coords.json` e `regioni_split.geojson` sono cache statiche: vanno committate
una volta e non toccate dal cron. Si rigenerano solo quando ISTAT modifica i confini
comunali, cioè in pratica a ogni fusione.

## Cron

Aggiungere una riga dopo `build_site.py`:

    python3 /home/piersoft/mqaedp/mqa-monitor/build_maps.py

Costo: una chiamata HTTP a `harvest_source_list` (~170 KB), nessuna query SPARQL.

## Metodo

**Comuni — livello titolari.** `dct:rightsHolder` più `dct:identifier` è l'unico livello
che attribuisce il dataset all'ente titolare anche quando il dataset vive dentro il
catalogo di una regione. Codice IPA `c_` + catastale ricondotto al centroide via
`com_catasto_code` dei confini openpolis, senza passare dal codice ISTAT.

Il 26% dei dataset comunali sta su titolari con identificativo fuori standard
(Torino usa la partita IVA, i comuni veneti la denominazione estesa): vengono
recuperati per confronto sul nome, con match univoco e nessuna omonimia.

**Regioni — livello organizzazioni.** L'elenco dei cataloghi federati viene da
`harvest_source_list` di dati.gov.it, non da EDP: la gerarchia `dct:hasPart` non
sopravvive all'harvesting verso data.europa.eu. `catalog.ttl` esporrebbe lo stesso
dato ma è paginato su 659 pagine, circa 400 MB di scarico per una lista di 321 righe.

Le due mappe non si sommano: un dataset comunale dentro un catalogo regionale è
contato una volta per titolarità e una volta per federazione.

## Correzioni applicate

Codici IPA errati sui titolari, corretti in `OVERRIDE_CODICI`:

| Dichiarato | Reale | Ente |
|---|---|---|
| `c_l390` | `c_i390` | San Vincenzo (LI) |
| `c_l344` | `c_i344` | Sant'Ippolito (PU) |
| `c_f633` | `c_f653` | Monte Urano (FM) |
| `c_e667` | `c_m312` | Lonato del Garda (BS) |
| `c_969` | `c_d969` | Genova |
| `c_cp112` | `c_m323` | Castelfranco Piandiscò |
| `c_f474` | — | Monteciccardo, fuso in Pesaro nel 2024 |

Sono candidati per `correggi_titolare.py` alla fonte.

Esclusi dalla mappa comunale: 4 titolari per 22 dataset, tutti comuni soppressi o
denominazioni inesistenti (Lentiai, Castellavazzo, Santa Caterina d'Este,
Monteciccardo). Escluse anche le Città metropolitane, che sono enti di area vasta.
