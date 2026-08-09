#!/usr/bin/env python3
"""
Rilevazione per TITOLARE e per ORGANIZZAZIONE via SPARQL di data.europa.eu.

L'API di ricerca non espone il titolare: un dataset del Comune di Montemesola
pubblicato sul catalogo regionale pugliese arriva su EDP con publisher
"Redazione OD" e contact point "regione-puglia". Il titolare reale sopravvive
solo nel triplestore, insieme alle cinque dimensioni MQA.

## Perche le organizzazioni si interrogano una alla volta

Il gateway di data.europa.eu chiude la connessione a 60 secondi. Una query
aggregata su tutte le organizzazioni raggruppa 64.000 dataset per un URI lungo
e ripetuto: ha funzionato per un giorno (9 s), poi Virtuoso ha cambiato piano di
esecuzione e ha smesso di rientrare nel limite, anche spezzata per singola
metrica. Fissando invece l'URI dell'organizzazione, l'indice viene usato e la
risposta arriva in meno di un secondo — anche per Regione Toscana, 12.575
dataset. 398 richieste leggere battono una richiesta pesante: se una fallisce si
ritenta solo quella, e nessuna sfiora il limite del gateway.

La query sui titolari resta unica (~45 s) perche 1.614 richieste sarebbero
troppe, ma e vicina al limite: se fallisce, il livello viene saltato e si
riprova il giorno dopo. Le due fasi sono indipendenti, quella che riesce si
salva comunque.

Uso:
    python3 mqa_sparql.py --catalog dati-gov-it
    python3 mqa_sparql.py --solo organizzazioni
"""

import argparse
import csv
import datetime as dt
import glob
import gzip
import json
import os
import re
import time
import urllib.parse
import urllib.request

from mqa_monitor import titolizza

ENDPOINT = "https://data.europa.eu/sparql"
GRAFO = "http://data.europa.eu/88u/catalogue/%s"
ORG_RE = re.compile(r"/organization/([0-9a-fA-F-]{8,})")

METRICHE = {
    "scoring": "scoring",
    "findabilityScoring": "findability",
    "accessibilityScoring": "accessibility",
    "interoperabilityScoring": "interoperability",
    "reusabilityScoring": "reusability",
    "contextualityScoring": "contextuality",
}
MASSIMI = {"scoring": 405, "findability": 100, "accessibility": 100,
           "interoperability": 110, "reusability": 75, "contextuality": 20}

FILTRO = """  FILTER(?metrica IN (voc:scoring, voc:findabilityScoring,
                      voc:accessibilityScoring, voc:interoperabilityScoring,
                      voc:reusabilityScoring, voc:contextualityScoring))"""

PREFISSI = """PREFIX dcat: <http://www.w3.org/ns/dcat#>
PREFIX dct: <http://purl.org/dc/terms/>
PREFIX dqv: <http://www.w3.org/ns/dqv#>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>
PREFIX voc: <https://piveau.eu/ns/voc#>"""

QUERY_TITOLARI = PREFISSI + """
SELECT ?id ?metrica (COUNT(DISTINCT ?ds) AS ?n) (AVG(?v) AS ?media)
WHERE {
  GRAPH <%s> { ?c dcat:dataset ?ds }
  GRAPH ?ds { ?ds dct:rightsHolder ?h . ?h dct:identifier ?id }
  GRAPH ?mg { ?ds dqv:hasQualityMeasurement ?m .
              ?m dqv:isMeasurementOf ?metrica ; dqv:value ?v }
""" + FILTRO + """
}
GROUP BY ?id ?metrica"""

# Denominazioni dei titolari con la loro frequenza (~3 secondi).
#
# foaf:name e testo libero compilato da ogni redattore: 1.514 titolari su 1.614
# hanno piu di una denominazione. Il Comune di Matera ne ha sei, fra cui
# "cittadinanza" e "comunita-di-pratica"; la Provincia di Bolzano ne ha 117.
# Prendere un nome a caso (SAMPLE) o il primo alfabetico (MIN) produce etichette
# sbagliate: si sceglie quello usato dal maggior numero di dataset, perche gli
# errori sono minoritari per costruzione.
QUERY_NOMI = PREFISSI + """
SELECT ?id ?nome (COUNT(DISTINCT ?ds) AS ?n) WHERE {
  GRAPH <%s> { ?c dcat:dataset ?ds }
  GRAPH ?ds { ?ds dct:rightsHolder ?h . ?h dct:identifier ?id ; foaf:name ?nome }
} GROUP BY ?id ?nome"""

# elenco delle organizzazioni presenti nel catalogo (~6 secondi)
QUERY_ELENCO_ORG = PREFISSI + """
SELECT DISTINCT ?cp WHERE {
  GRAPH <%s> { ?c dcat:dataset ?ds }
  GRAPH ?ds { ?ds dcat:contactPoint ?cp }
}"""

# una organizzazione alla volta: l'URI fissato fa usare l'indice (<1 secondo)
QUERY_ORG = PREFISSI + """
SELECT ?metrica (COUNT(*) AS ?n) (AVG(?v) AS ?media) WHERE {
  GRAPH ?ds { ?ds dcat:contactPoint <%s> }
  GRAPH ?mg { ?ds dqv:hasQualityMeasurement ?m .
              ?m dqv:isMeasurementOf ?metrica ; dqv:value ?v }
""" + FILTRO + """
} GROUP BY ?metrica"""


class SparqlNonDisponibile(Exception):
    pass


def interroga(query, tries=5, timeout=90, attese=(20, 45, 90, 150), verbose=False):
    """Le attese sono lunghe di proposito: l'endpoint si degrada dopo richieste
    ravvicinate e recupera solo dopo qualche minuto di quiete."""
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": query})
    ultimo = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "Accept": "application/sparql-results+json",
                "User-Agent": "mqa-monitor/5.0",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:  # noqa: BLE001
            ultimo = e
            if i < tries - 1:
                attesa = attese[min(i, len(attese) - 1)]
                if verbose:
                    print("      %s, riprovo tra %ds" % (type(e).__name__, attesa),
                          flush=True)
                time.sleep(attesa)
    raise SparqlNonDisponibile("%s" % ultimo)


def _accumula(enti, chiave, etichetta, righe):
    e = enti.setdefault(chiave, {"id": chiave, "titolare": etichetta})
    for b in righe:
        breve = METRICHE.get(b["metrica"]["value"].split("#")[-1])
        if not breve:
            continue
        e[breve] = round(float(b["media"]["value"]), 2)
        e["n_dataset"] = max(e.get("n_dataset", 0), int(b["n"]["value"]))
    return e


# ------------------------------------------------------------------ titolari

def nomi_titolari(catalog, verbose=True):
    """id -> (denominazione piu usata, quante denominazioni diverse)."""
    d = interroga(QUERY_NOMI % (GRAFO % catalog), timeout=90)
    varianti = {}
    for b in d["results"]["bindings"]:
        chiave, nome = b["id"]["value"], b["nome"]["value"]
        n = int(b["n"]["value"])
        varianti.setdefault(chiave, {})
        varianti[chiave][nome] = max(varianti[chiave].get(nome, 0), n)
    out = {}
    for chiave, v in varianti.items():
        # a parita di frequenza il piu lungo: preferisce la forma estesa
        modale = sorted(v.items(), key=lambda x: (-x[1], -len(x[0])))[0][0]
        out[chiave] = (modale, len(v))
    if verbose:
        confusi = sum(1 for _, n in out.values() if n > 1)
        print("      %d denominazioni risolte, %d titolari con piu di una"
              % (len(out), confusi))
    return out


def rileva_titolari(catalog, verbose=True):
    t0 = time.time()
    nomi = nomi_titolari(catalog, verbose)
    d = interroga(QUERY_TITOLARI % (GRAFO % catalog), timeout=120, verbose=verbose)
    righe = d["results"]["bindings"]
    if verbose:
        print("      %d misure in %.0fs" % (len(righe), time.time() - t0))
    enti = {}
    for b in righe:
        chiave = b["id"]["value"]
        nome, n_nomi = nomi.get(chiave, (chiave, 0))
        e = enti.setdefault(chiave, {"id": chiave, "titolare": nome,
                                     "n_nomi": n_nomi})
        breve = METRICHE.get(b["metrica"]["value"].split("#")[-1])
        if not breve:
            continue
        e[breve] = round(float(b["media"]["value"]), 2)
        e["n_dataset"] = max(e.get("n_dataset", 0), int(b["n"]["value"]))
    return completa(enti.values())


# ------------------------------------------------------------ organizzazioni

def elenco_organizzazioni(catalog):
    d = interroga(QUERY_ELENCO_ORG % (GRAFO % catalog), timeout=90)
    uri = [b["cp"]["value"] for b in d["results"]["bindings"]]
    return sorted(u for u in uri if ORG_RE.search(u))


def rileva_organizzazioni(catalog, pausa=0.3, verbose=True):
    t0 = time.time()
    uri = elenco_organizzazioni(catalog)
    if verbose:
        print("      %d organizzazioni da interrogare" % len(uri))
    enti, falliti = {}, []
    for i, u in enumerate(uri, 1):
        try:
            d = interroga(QUERY_ORG % u, tries=3, timeout=60, attese=(10, 30))
        except SparqlNonDisponibile:
            falliti.append(u)
            continue
        _accumula(enti, ORG_RE.search(u).group(1), "", d["results"]["bindings"])
        time.sleep(pausa)
        if verbose and i % 100 == 0:
            print("      %d/%d (%.0fs)" % (i, len(uri), time.time() - t0), flush=True)
    if verbose:
        print("      %d organizzazioni in %.0fs%s"
              % (len(enti), time.time() - t0,
                 ", %d non risolte" % len(falliti) if falliti else ""))
    if not enti:
        raise SparqlNonDisponibile("nessuna organizzazione risolta")
    return completa(enti.values())


def nomi_organizzazioni(outdir, catalog):
    """uuid -> (slug, titolo) dagli snapshot per dataset gia' presenti."""
    files = sorted(glob.glob(os.path.join(
        outdir, "dataset", "%s_*.csv.gz" % catalog)))
    if not files:
        return {}
    titoli = {}
    path = os.path.join(outdir, "org_titles.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            titoli = json.load(f)
    mappa = {}
    with gzip.open(files[-1], "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            u, slug = r.get("org_uuid"), r.get("org_slug") or ""
            if u and u not in mappa:
                mappa[u] = (slug, titoli.get(slug) or titolizza(slug))
    return mappa


# ---------------------------------------------------------------- salvataggio

CAMPI = ["id", "slug", "titolare", "n_dataset", "scoring", "pct", "findability",
         "accessibility", "interoperability", "reusability", "contextuality",
         "n_nomi"]


def completa(righe):
    out = []
    for e in righe:
        if "scoring" not in e:
            continue
        e["pct"] = round(e["scoring"] / MASSIMI["scoring"] * 100, 2)
        e.setdefault("slug", "")
        out.append(e)
    out.sort(key=lambda x: -x["scoring"])
    return out


def salva(righe, outdir, catalog, day, cartella):
    percorso = os.path.join(outdir, cartella)
    os.makedirs(percorso, exist_ok=True)
    path = os.path.join(percorso, "%s_%s.csv" % (catalog, day))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPI, extrasaction="ignore")
        w.writeheader()
        for r in righe:
            w.writerow(r)
    n = sum(r["n_dataset"] for r in righe)
    media = sum(r["scoring"] * r["n_dataset"] for r in righe) / max(n, 1)
    print("      %s  (%d voci, %d dataset, media %.1f/405)"
          % (path, len(righe), n, media))
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="dati-gov-it")
    ap.add_argument("--outdir", default="./mqa")
    ap.add_argument("--solo", choices=["titolari", "organizzazioni"],
                    help="rileva un solo livello")
    ap.add_argument("--pausa-fra-livelli", type=int, default=60,
                    help="secondi di quiete fra i due livelli")
    args = ap.parse_args()

    day = dt.date.today().isoformat()
    esiti = {}

    if args.solo != "organizzazioni":
        print("[titolari] dct:rightsHolder, query unica ...")
        try:
            righe = rileva_titolari(args.catalog)
            salva(righe, args.outdir, args.catalog, day, "titolari")
            esiti["titolari"] = len(righe)
        except SparqlNonDisponibile as e:
            print("      NON RIUSCITO: %s" % e)
            esiti["titolari"] = 0
        if args.solo is None and args.pausa_fra_livelli:
            print("      pausa di %ds" % args.pausa_fra_livelli)
            time.sleep(args.pausa_fra_livelli)

    if args.solo != "titolari":
        print("[organizzazioni] dcat:contactPoint, una query per ente ...")
        try:
            righe = rileva_organizzazioni(args.catalog)
            mappa = nomi_organizzazioni(args.outdir, args.catalog)
            for e in righe:
                slug, nome = mappa.get(e["id"], ("", ""))
                e["slug"], e["titolare"] = slug, nome or e["id"][:8]
            salva(righe, args.outdir, args.catalog, day, "organizzazioni")
            esiti["organizzazioni"] = len(righe)
        except SparqlNonDisponibile as e:
            print("      NON RIUSCITO: %s" % e)
            esiti["organizzazioni"] = 0

    riusciti = [k for k, v in esiti.items() if v]
    print("\nRilevazione %s: %s"
          % (day, ", ".join("%s %d" % (k, esiti[k]) for k in esiti) or "niente"))
    if not riusciti:
        raise SystemExit("nessun livello rilevato: l'endpoint SPARQL non risponde")


if __name__ == "__main__":
    main()
