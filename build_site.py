#!/usr/bin/env python3
"""
Ricostruisce la serie storica dagli snapshot per dataset e prepara i dati
per la pagina pubblica.

Lo storico NON viene appeso: viene ricalcolato ogni volta leggendo
mqa/dataset/<catalogo>_<data>.csv.gz. Un run fallito o ripetuto non lascia
righe duplicate, e cancellare uno snapshot lo toglie anche dallo storico.

Calcola entrambi i livelli (organizzazione ed editore) dagli stessi snapshot,
senza riscaricare nulla da data.europa.eu.

Produce:
    mqa/storico.csv     una riga per ente per livello per rilevazione
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
    """[(org_uuid, org_slug, publisher, scoring), ...] dai dataset con scoring."""
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
            out.append((r.get("org_uuid") or "", r.get("org_slug") or "",
                        (r.get("publisher") or "").strip(), s))
    return out


def costruisci_storico(outdir, catalog, titoli, livello):
    """{data: {chiave: riga}} ordinato per data, al livello richiesto."""
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
        etichette = {}
        for uuid, slug, pub, s in leggi_snapshot(path):
            if livello == "organization":
                chiave = uuid or ("slug:" + slug if slug else "(sconosciuto)")
                if slug:
                    slugs[chiave] = slug
            else:
                chiave = pub or "(senza editore)"
                etichette[chiave] = chiave
            scores[chiave].append(s)
        righe = {}
        for chiave, vals in scores.items():
            vals.sort()
            n = len(vals)
            media = sum(vals) / float(n)
            slug = slugs.get(chiave, "")
            etich = etichette.get(chiave) or titoli.get(slug) or titolizza(slug)
            righe[chiave] = {
                "data": day,
                "chiave": chiave,
                "slug": slug,
                "etichetta": etich,
                "n_dataset": n,
                "media": round(media, 2),
                "mediana": vals[n // 2],
                "min": vals[0],
                "max": vals[-1],
                "rating": bucket(media),
            }
        storico[day] = righe
    return storico


CAMPI = ["data", "livello", "chiave", "slug", "etichetta", "n_dataset", "media",
         "mediana", "min", "max", "rating"]


def salva_storico(storici, outdir):
    path = os.path.join(outdir, "storico.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPI)
        w.writeheader()
        for livello in sorted(storici):
            for day in sorted(storici[livello]):
                for r in sorted(storici[livello][day].values(),
                                key=lambda x: -x["media"]):
                    r = dict(r, livello=livello)
                    w.writerow(r)
    return path


def blocco_livello(storico, date):
    """Prepara enti + totali + serie del catalogo per un singolo livello."""
    pos = dict((d, i) for i, d in enumerate(date))
    voci = {}
    for day in date:
        for chiave, r in storico[day].items():
            v = voci.setdefault(chiave, {"nome": r["etichetta"], "slug": r["slug"],
                                         "punti": {}})
            v["nome"] = r["etichetta"]
            v["slug"] = r["slug"]
            v["punti"][pos[day]] = [round(r["media"], 1), r["n_dataset"]]

    ultimo_i = len(date) - 1
    lista = []
    for chiave, v in voci.items():
        ultimo = v["punti"].get(ultimo_i)
        if not ultimo:
            continue  # non piu presente nell'ultima rilevazione
        prec = v["punti"].get(ultimo_i - 1)
        lista.append({
            "id": chiave, "nome": v["nome"], "slug": v["slug"],
            "media": ultimo[0], "n": ultimo[1],
            "delta": round(ultimo[0] - prec[0], 1) if prec else None,
            "rating": bucket(ultimo[0]),
            "serie": [[i, v["punti"][i][0], v["punti"][i][1]]
                      for i in sorted(v["punti"])],
        })
    lista.sort(key=lambda x: -x["media"])

    tot_n = sum(x["n"] for x in lista)
    serie_cat = []
    for day in date:
        righe = storico[day].values()
        n = sum(r["n_dataset"] for r in righe)
        serie_cat.append(round(
            sum(r["media"] * r["n_dataset"] for r in righe) / max(n, 1), 1))
    return {
        "totali": {"enti": len(lista), "dataset": tot_n,
                   "media": serie_cat[-1] if serie_cat else 0},
        "serie_catalogo": serie_cat,
        "enti": lista,
    }


def salva_json(storici, catalog, docsdir, max_rilevazioni):
    date = sorted(set().union(*[set(s) for s in storici.values()]))
    if not date:
        raise SystemExit("nessuno snapshot trovato: lancia prima mqa_monitor.py")
    date = date[-max_rilevazioni:]

    livelli = {}
    for livello, storico in storici.items():
        livelli[livello] = blocco_livello(storico, date)

    os.makedirs(docsdir, exist_ok=True)
    path = os.path.join(docsdir, "data.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "catalogo": catalog,
            "aggiornato": date[-1],
            "max_score": MAX_SCORE,
            "date": date,
            "livelli": livelli,
        }, f, ensure_ascii=False, separators=(",", ":"))
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="dati-gov-it")
    ap.add_argument("--outdir", default="./mqa")
    ap.add_argument("--docsdir", default="./docs")
    ap.add_argument("--ckan-url", default="")
    ap.add_argument("--max-rilevazioni", type=int, default=104,
                    help="quante rilevazioni tenere in docs/data.json")
    args = ap.parse_args()

    print("[1/3] leggo gli snapshot ...")
    titoli = carica_titoli(args.outdir, args.ckan_url)
    storici = {}
    for livello in ("organization", "publisher"):
        storici[livello] = costruisci_storico(
            args.outdir, args.catalog, titoli, livello)
        ultimo = sorted(storici[livello])[-1] if storici[livello] else None
        print("  %-13s %d rilevazioni, %d voci nell'ultima"
              % (livello, len(storici[livello]),
                 len(storici[livello][ultimo]) if ultimo else 0))
    print("[2/3] salvo lo storico ...")
    p1 = salva_storico(storici, args.outdir)
    print("[3/3] preparo i dati della pagina ...")
    p2 = salva_json(storici, args.catalog, args.docsdir, args.max_rilevazioni)
    print("\nOK\n  %s\n  %s" % (p1, p2))


if __name__ == "__main__":
    main()
