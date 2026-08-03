#!/usr/bin/env python3
"""
Rilevazione per TITOLARE (dct:rightsHolder) via endpoint SPARQL di data.europa.eu.

L'API di ricerca non espone il titolare: un dataset del Comune di Montemesola
pubblicato sul catalogo regionale pugliese arriva su EDP con publisher
"Redazione OD" e contact point "regione-puglia". Il titolare reale sopravvive
solo nel triplestore, insieme alle cinque dimensioni MQA.

Una sola query aggregata, ~35 secondi, nessun carico su dati.gov.it.

Uso:
    python3 mqa_sparql.py --catalog dati-gov-it
"""

import argparse
import csv
import datetime as dt
import json
import os
import time
import urllib.parse
import urllib.request

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

QUERY = """PREFIX dcat: <http://www.w3.org/ns/dcat#>
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


CAMPI = ["id", "titolare", "n_dataset", "scoring", "pct", "findability",
         "accessibility", "interoperability", "reusability", "contextuality"]


def rileva(catalog, verbose=True):
    t0 = time.time()
    d = interroga(QUERY % (GRAFO % catalog))
    righe = d["results"]["bindings"]
    if verbose:
        print("  %d misure in %.0fs" % (len(righe), time.time() - t0))

    enti = {}
    for b in righe:
        chiave = b["id"]["value"]
        e = enti.setdefault(chiave, {"id": chiave,
                                     "titolare": b["titolare"]["value"]})
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


def salva(righe, outdir, catalog, day):
    cartella = os.path.join(outdir, "titolari")
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
    print("[1/2] interrogo il triplestore ...")
    righe = rileva(args.catalog)
    print("      %d titolari" % len(righe))
    print("[2/2] salvo ...")
    path = salva(righe, args.outdir, args.catalog, day)

    tot = sum(r["n_dataset"] for r in righe)
    media = sum(r["scoring"] * r["n_dataset"] for r in righe) / max(tot, 1)
    print("\nOK  %s" % path)
    print("    %d dataset, media %.1f/405" % (tot, media))


if __name__ == "__main__":
    main()
