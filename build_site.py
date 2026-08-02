#!/usr/bin/env python3
"""
Ricostruisce la serie storica dagli snapshot per dataset e prepara i dati
per la pagina pubblica.

Lo storico NON viene appeso: viene ricalcolato ogni volta leggendo
mqa/dataset/<catalogo>_<data>.csv.gz. Un run fallito o ripetuto non lascia
righe duplicate, e cancellare uno snapshot lo toglie anche dallo storico.

Produce:
    mqa/storico.csv     una riga per ente per rilevazione
    docs/data.json      dati compatti per docs/index.html

Uso:
    python3 build_site.py --catalog dati-gov-it
"""

import argparse
import csv
import glob
import gzip
import json
import os
import re
from collections import defaultdict

from mqa_monitor import MAX_SCORE, bucket, carica_titoli, titolizza

DATA_RE = re.compile(r"_(\d{4}-\d{2}-\d{2})\.csv\.gz$")


def leggi_snapshot(path):
    """[(org_uuid, org_slug, scoring), ...] dai dataset con scoring."""
    out = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            s = r.get("scoring")
            if not s:
                continue
            try:
                s = int(float(s))
            except ValueError:
                continue
            out.append((r.get("org_uuid") or "", r.get("org_slug") or "", s))
    return out


def costruisci_storico(outdir, catalog, titoli):
    """{data: {uuid: riga}} ordinato per data."""
    files = sorted(glob.glob(os.path.join(
        outdir, "dataset", "%s_*.csv.gz" % catalog)))
    storico = {}
    for path in files:
        m = DATA_RE.search(os.path.basename(path))
        if not m:
            continue
        day = m.group(1)
        scores = defaultdict(list)
        slugs = {}
        for uuid, slug, s in leggi_snapshot(path):
            chiave = uuid or ("slug:" + slug if slug else "(sconosciuto)")
            scores[chiave].append(s)
            if slug:
                slugs[chiave] = slug
        righe = {}
        for chiave, vals in scores.items():
            vals.sort()
            n = len(vals)
            media = sum(vals) / float(n)
            slug = slugs.get(chiave, "")
            righe[chiave] = {
                "data": day,
                "chiave": chiave,
                "slug": slug,
                "etichetta": titoli.get(slug) or titolizza(slug),
                "n_dataset": n,
                "media": round(media, 2),
                "mediana": vals[n // 2],
                "min": vals[0],
                "max": vals[-1],
                "rating": bucket(media),
            }
        storico[day] = righe
        print("  %s: %d enti" % (day, len(righe)))
    return storico


CAMPI = ["data", "chiave", "slug", "etichetta", "n_dataset", "media",
         "mediana", "min", "max", "rating"]


def salva_storico(storico, outdir):
    path = os.path.join(outdir, "storico.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPI)
        w.writeheader()
        for day in sorted(storico):
            for r in sorted(storico[day].values(), key=lambda x: -x["media"]):
                w.writerow(r)
    return path


def salva_json(storico, catalog, docsdir):
    date = sorted(storico)
    if not date:
        raise SystemExit("nessuno snapshot trovato: lancia prima mqa_monitor.py")
    ultima = date[-1]

    enti = {}
    for i, day in enumerate(date):
        for chiave, r in storico[day].items():
            e = enti.setdefault(chiave, {
                "id": chiave, "nome": r["etichetta"], "slug": r["slug"],
                "punti": {},
            })
            e["nome"] = r["etichetta"]
            e["slug"] = r["slug"]
            e["punti"][i] = [r["media"], r["n_dataset"]]

    lista = []
    for e in enti.values():
        idx = sorted(e["punti"])
        serie = [[i, e["punti"][i][0], e["punti"][i][1]] for i in idx]
        ultimo = e["punti"].get(len(date) - 1)
        if not ultimo:
            continue  # ente non piu presente nell'ultima rilevazione
        prec = e["punti"].get(len(date) - 2)
        lista.append({
            "id": e["id"],
            "nome": e["nome"],
            "slug": e["slug"],
            "media": ultimo[0],
            "n": ultimo[1],
            "delta": round(ultimo[0] - prec[0], 2) if prec else None,
            "delta_n": ultimo[1] - prec[1] if prec else None,
            "rating": bucket(ultimo[0]),
            "serie": serie,
        })
    lista.sort(key=lambda x: -x["media"])

    tot_n = sum(x["n"] for x in lista)
    media_cat = sum(x["media"] * x["n"] for x in lista) / max(tot_n, 1)
    serie_cat = []
    for i, day in enumerate(date):
        righe = storico[day].values()
        n = sum(r["n_dataset"] for r in righe)
        serie_cat.append(round(
            sum(r["media"] * r["n_dataset"] for r in righe) / max(n, 1), 2))

    os.makedirs(docsdir, exist_ok=True)
    path = os.path.join(docsdir, "data.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "catalogo": catalog,
            "aggiornato": ultima,
            "max_score": MAX_SCORE,
            "date": date,
            "totali": {
                "enti": len(lista),
                "dataset": tot_n,
                "media": round(media_cat, 2),
            },
            "serie_catalogo": serie_cat,
            "enti": lista,
        }, f, ensure_ascii=False, separators=(",", ":"))
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="dati-gov-it")
    ap.add_argument("--outdir", default="./mqa")
    ap.add_argument("--docsdir", default="./docs")
    ap.add_argument("--ckan-url", default="")
    args = ap.parse_args()

    print("[1/3] leggo gli snapshot ...")
    titoli = carica_titoli(args.outdir, args.ckan_url)
    storico = costruisci_storico(args.outdir, args.catalog, titoli)
    print("[2/3] salvo lo storico ...")
    p1 = salva_storico(storico, args.outdir)
    print("[3/3] preparo i dati della pagina ...")
    p2 = salva_json(storico, args.catalog, args.docsdir)
    print("\nOK\n  %s\n  %s" % (p1, p2))


if __name__ == "__main__":
    main()
