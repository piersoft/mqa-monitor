#!/usr/bin/env python3
"""
Rilevazione per TITOLARE e per ORGANIZZAZIONE via SPARQL di data.europa.eu.

L'API di ricerca non espone il titolare: un dataset del Comune di Montemesola
pubblicato sul catalogo regionale pugliese arriva su EDP con publisher
"Redazione OD" e contact point "regione-puglia". Il titolare reale sopravvive
solo nel triplestore, insieme alle cinque dimensioni MQA.

Due query aggregate (~45 secondi in tutto), nessun carico su dati.gov.it.
Entrambi i livelli arrivano con le cinque dimensioni MQA, che l'API di ricerca
non espone.

Nota: EDP appiattisce la gerarchia dei cataloghi in harvesting. I sotto-catalogi
dichiarati da dati.gov.it come dct:hasPart non esistono nel triplestore: il grafo
del catalogo contiene solo dcat:dataset, dcat:record e dcat:service. Il legame con
l'organizzazione passa quindi da dcat:contactPoint, che e un URI diretto
(https://www.dati.gov.it/organization/<uuid>) e si raggruppa nativamente.

Uso:
    python3 mqa_sparql.py --catalog dati-gov-it
"""

import argparse
import csv
import datetime as dt
import json
import os
import time
import glob
import gzip
import re
import urllib.parse
import urllib.request

from mqa_monitor import titolizza

ENDPOINT = "https://data.europa.eu/sparql"
GRAFO = "http://data.europa.eu/88u/catalogue/%s"

# nomi brevi delle metriche piveau
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

QUERY_TITOLARI = """PREFIX dcat: <http://www.w3.org/ns/dcat#>
PREFIX dct: <http://purl.org/dc/terms/>
PREFIX dqv: <http://www.w3.org/ns/dqv#>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>
PREFIX voc: <https://piveau.eu/ns/voc#>
SELECT ?id (SAMPLE(?nome) AS ?titolare) ?metrica
       (COUNT(DISTINCT ?ds) AS ?n) (AVG(?v) AS ?media)
WHERE {
  GRAPH <%s> { ?c dcat:dataset ?ds }
  GRAPH ?ds { ?ds dct:rightsHolder ?h . ?h foaf:name ?nome ; dct:identifier ?id }
  GRAPH ?mg { ?ds dqv:hasQualityMeasurement ?m .
              ?m dqv:isMeasurementOf ?metrica ; dqv:value ?v }
  FILTER(?metrica IN (voc:scoring, voc:findabilityScoring, voc:accessibilityScoring,
                      voc:interoperabilityScoring, voc:reusabilityScoring,
                      voc:contextualityScoring))
}
GROUP BY ?id ?metrica"""

QUERY_ORGANIZZAZIONI = """PREFIX dcat: <http://www.w3.org/ns/dcat#>
PREFIX dqv: <http://www.w3.org/ns/dqv#>
PREFIX voc: <https://piveau.eu/ns/voc#>
SELECT ?id ?metrica (COUNT(DISTINCT ?ds) AS ?n) (AVG(?v) AS ?media)
WHERE {
  GRAPH <%s> { ?c dcat:dataset ?ds }
  GRAPH ?ds { ?ds dcat:contactPoint ?id }
  GRAPH ?mg { ?ds dqv:hasQualityMeasurement ?m .
              ?m dqv:isMeasurementOf ?metrica ; dqv:value ?v }
  FILTER(?metrica IN (voc:scoring, voc:findabilityScoring, voc:accessibilityScoring,
                      voc:interoperabilityScoring, voc:reusabilityScoring,
                      voc:contextualityScoring))
}
GROUP BY ?id ?metrica"""

ORG_RE = re.compile(r"/organization/([0-9a-fA-F-]{8,})")


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


def interroga(query, tries=3, timeout=300):
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": query})
    ultimo = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "Accept": "application/sparql-results+json",
                "User-Agent": "mqa-monitor/3.0",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:  # noqa: BLE001
            ultimo = e
            time.sleep(5 * (i + 1))
    raise RuntimeError("SPARQL non ha risposto: %s" % ultimo)


CAMPI = ["id", "slug", "titolare", "n_dataset", "scoring", "pct", "findability",
         "accessibility", "interoperability", "reusability", "contextuality"]


def rileva(catalog, query, chiave_uri=False, verbose=True):
    t0 = time.time()
    d = interroga(query % (GRAFO % catalog))
    righe = d["results"]["bindings"]
    if verbose:
        print("  %d misure in %.0fs" % (len(righe), time.time() - t0))

    enti = {}
    for b in righe:
        chiave = b["id"]["value"]
        if chiave_uri:
            m = ORG_RE.search(chiave)
            if not m:
                continue
            chiave = m.group(1)
        e = enti.setdefault(chiave, {
            "id": chiave,
            "titolare": b["titolare"]["value"] if "titolare" in b else "",
        })
        breve = METRICHE.get(b["metrica"]["value"].split("#")[-1])
        if not breve:
            continue
        e[breve] = round(float(b["media"]["value"]), 2)
        e["n_dataset"] = max(e.get("n_dataset", 0), int(b["n"]["value"]))

    out = []
    for e in enti.values():
        if "scoring" not in e:
            continue
        e["pct"] = round(e["scoring"] / MASSIMI["scoring"] * 100, 2)
        out.append(e)
    out.sort(key=lambda x: -x["scoring"])
    return out


def salva(righe, outdir, catalog, day, cartella="titolari"):
    cartella = os.path.join(outdir, cartella)
    os.makedirs(cartella, exist_ok=True)
    path = os.path.join(cartella, "%s_%s.csv" % (catalog, day))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPI, extrasaction="ignore")
        w.writeheader()
        for r in righe:
            w.writerow(r)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="dati-gov-it")
    ap.add_argument("--outdir", default="./mqa")
    args = ap.parse_args()

    day = dt.date.today().isoformat()

    print("[1/4] titolari (dct:rightsHolder) ...")
    tit = rileva(args.catalog, QUERY_TITOLARI)
    print("      %d titolari" % len(tit))
    p1 = salva(tit, args.outdir, args.catalog, day, "titolari")

    print("[2/4] organizzazioni (dcat:contactPoint) ...")
    org = rileva(args.catalog, QUERY_ORGANIZZAZIONI, chiave_uri=True)
    print("      %d organizzazioni" % len(org))

    print("[3/4] risolvo i nomi delle organizzazioni ...")
    mappa = nomi_organizzazioni(args.outdir, args.catalog)
    mancanti = 0
    for e in org:
        slug, nome = mappa.get(e["id"], ("", ""))
        if not nome:
            mancanti += 1
            nome = e["id"][:8]
        e["slug"], e["titolare"] = slug, nome
    if mancanti:
        print("      %d senza nome (manca lo snapshot dell'API)" % mancanti)

    print("[4/4] salvo ...")
    p2 = salva(org, args.outdir, args.catalog, day, "organizzazioni")

    for etichetta, righe, path in (("titolari", tit, p1),
                                   ("organizzazioni", org, p2)):
        n = sum(r["n_dataset"] for r in righe)
        media = sum(r["scoring"] * r["n_dataset"] for r in righe) / max(n, 1)
        print("\n%-15s %s\n%-15s %d dataset, media %.1f/405"
              % (etichetta, path, "", n, media))


if __name__ == "__main__":
    main()
