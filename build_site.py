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
import datetime as dt
import glob
import gzip
import json
import os
import re
from collections import defaultdict

from mqa_monitor import MAX_SCORE, bucket, carica_titoli, titolizza

DATA_RE = re.compile(r"_(\d{4}-\d{2}-\d{2})\.csv\.gz$")
DATA_CSV_RE = re.compile(r"_(\d{4}-\d{2}-\d{2})\.csv$")
DIMENSIONI = ["findability", "accessibility", "interoperability",
              "reusability", "contextuality"]


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


def storico_sparql(outdir, catalog, cartella):
    """Livelli da SPARQL: leggono le rilevazioni in mqa/<cartella>/."""
    storico = {}
    for path in sorted(glob.glob(os.path.join(
            outdir, cartella, "%s_*.csv" % catalog))):
        m = DATA_CSV_RE.search(os.path.basename(path))
        if not m:
            continue
        day = m.group(1)
        righe = {}
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                media = float(r["scoring"])
                chiave = r["id"].lower()
                if chiave in righe:  # stesso codice, maiuscole diverse
                    a = righe[chiave]
                    na, nb = a["n_dataset"], int(r["n_dataset"])
                    tot = max(na + nb, 1)
                    a["media"] = round((a["media"] * na + media * nb) / tot, 2)
                    for k in DIMENSIONI:
                        if r.get(k):
                            a["dim"][k] = round(
                                (a["dim"].get(k, 0) * na + float(r[k]) * nb) / tot, 2)
                    a["n_dataset"] = na + nb
                    a["rating"] = bucket(a["media"])
                    if len(r["titolare"]) > len(a["etichetta"]):
                        a["etichetta"] = r["titolare"]
                    continue
                righe[chiave] = {
                    "data": day, "chiave": chiave,
                    "slug": r.get("slug") or chiave,
                    "etichetta": r["titolare"],
                    "n_dataset": int(r["n_dataset"]),
                    "media": round(media, 2), "mediana": "", "min": "", "max": "",
                    "rating": bucket(media),
                    "dim": dict((d, float(r[d])) for d in DIMENSIONI if r.get(d)),
                    "n_nomi": int(r["n_nomi"]) if r.get("n_nomi") else 0,
                    "ipa": {
                        "in": r.get("in_ipa") == "1",
                        "nome": r.get("ipa_nome") or "",
                        "prov": r.get("ipa_prov") or "",
                        "reg": r.get("ipa_reg") or "",
                    } if r.get("in_ipa") is not None else None,
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
                    r.pop("dim", None)
                    r.pop("n_nomi", None)
                    r.pop("ipa", None)
                    w.writerow(r)
    return path


def indice_riferimento(date, ultimo_i, giorni=7):
    """Indice della rilevazione piu vicina a `giorni` giorni prima dell'ultima.

    Con la cadenza giornaliera il confronto con la rilevazione precedente e
    rumore: un server che non risponde per un'ora fa scendere l'accessibility
    e risalire il giorno dopo.
    """
    if ultimo_i <= 0:
        return None
    bersaglio = dt.date.fromisoformat(date[ultimo_i]) - dt.timedelta(days=giorni)
    migliore, scarto = None, None
    for i in range(ultimo_i):
        d = abs((dt.date.fromisoformat(date[i]) - bersaglio).days)
        if scarto is None or d < scarto:
            migliore, scarto = i, d
    return migliore


def blocco_livello(storico, date):
    """Prepara enti e totali per un singolo livello.

    Non si calcola piu' la media del catalogo: e' la media dei punteggi dei
    singoli dataset, che non coincide ne' con il punteggio che data.europa.eu
    pubblica per il catalogo ne' con il monitoraggio dinamico di dati.gov.it.
    Tre numeri diversi per la stessa cosa confondono e basta; l'andamento
    complessivo sta gia' nel monitoraggio nazionale.
    """
    pos = dict((d, i) for i, d in enumerate(date))
    voci = {}
    for day in date:
        if day not in storico:
            continue
        for chiave, r in storico[day].items():
            v = voci.setdefault(chiave, {"nome": r["etichetta"], "slug": r["slug"],
                                         "punti": {}})
            v["nome"] = r["etichetta"]
            v["slug"] = r["slug"]
            v["punti"][pos[day]] = [round(r["media"], 1), r["n_dataset"]]
            if r.get("dim"):
                v["dim"] = dict((k, round(x, 1)) for k, x in r["dim"].items())
            if r.get("n_nomi"):
                v["n_nomi"] = r["n_nomi"]
            if r.get("ipa") is not None:
                v["ipa"] = r["ipa"]

    presenti = [i for i, d in enumerate(date) if d in storico]
    ultimo_i = presenti[-1] if presenti else len(date) - 1
    rif = indice_riferimento(date, ultimo_i)
    if rif is not None and rif not in presenti:
        candidati = [i for i in presenti if i < ultimo_i]
        rif = candidati[-1] if candidati else None
    lista = []
    for chiave, v in voci.items():
        ultimo = v["punti"].get(ultimo_i)
        if not ultimo:
            continue  # non piu presente nell'ultima rilevazione
        prec = v["punti"].get(rif) if rif is not None else None
        voce = {
            "id": chiave, "nome": v["nome"], "slug": v["slug"],
            "media": ultimo[0], "n": ultimo[1],
            "delta": round(ultimo[0] - prec[0], 1) if prec else None,
            "rating": bucket(ultimo[0]),
            "serie": [[i, v["punti"][i][0], v["punti"][i][1]]
                      for i in sorted(v["punti"])],
        }
        if v.get("dim"):
            voce["dim"] = v["dim"]
        if v.get("n_nomi", 0) > 1:
            voce["n_nomi"] = v["n_nomi"]
        ipa = v.get("ipa")
        if ipa is not None:
            if not ipa["in"]:
                voce["ipa_ko"] = True
            elif ipa["nome"] and ipa["nome"].lower() != v["nome"].lower():
                voce["ipa_nome"] = ipa["nome"]
                if ipa["prov"]:
                    voce["ipa_luogo"] = "%s (%s)" % (ipa["reg"], ipa["prov"]) \
                        if ipa["reg"] else ipa["prov"]
        lista.append(voce)
    lista.sort(key=lambda x: -x["media"])

    return {
        "totali": {"enti": len(lista),
                   "dataset": sum(x["n"] for x in lista),
                   "data": date[ultimo_i] if date else None},
        "enti": lista,
    }


def assottiglia(date, giorni_pieni=60, passo=7):
    """Tiene tutte le rilevazioni recenti, poi una ogni `passo` giorni.

    Con la rilevazione giornaliera lo storico completo gonfierebbe data.json
    (~30 KB per rilevazione con 2.000 enti). Lo storico integrale resta in
    mqa/storico.csv e negli snapshot.
    """
    if not date:
        return date
    limite = dt.date.fromisoformat(date[-1]) - dt.timedelta(days=giorni_pieni)
    recenti = [d for d in date if dt.date.fromisoformat(d) > limite]
    vecchie, ultima = [], None
    for d in date:
        if d in recenti:
            continue
        g = dt.date.fromisoformat(d)
        if ultima is None or (g - ultima).days >= passo:
            vecchie.append(d)
            ultima = g
    return vecchie + recenti


def salva_json(storici, catalog, docsdir, max_rilevazioni):
    usati = [storici[k] for k in ("holder", "organization") if storici.get(k)]
    date = sorted(set().union(*[set(s) for s in usati])) if usati else []
    if not date:
        raise SystemExit("nessuno snapshot trovato: lancia prima mqa_monitor.py")
    date = assottiglia(date)[-max_rilevazioni:]

    livelli = {}
    for livello in ("holder", "organization"):
        if storici.get(livello):
            livelli[livello] = blocco_livello(storici[livello], date)

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
    storici = {
        "holder": storico_sparql(args.outdir, args.catalog, "titolari"),
        "organization": storico_sparql(args.outdir, args.catalog, "organizzazioni"),
        # publisher resta nello storico per analisi, ma fuori dalla pagina
        "publisher": costruisci_storico(
            args.outdir, args.catalog, titoli, "publisher"),
    }
    for livello in ("holder", "organization", "publisher"):
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
