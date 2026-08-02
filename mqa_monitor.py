#!/usr/bin/env python3
"""
Monitoraggio settimanale dello scoring MQA (data.europa.eu).

Aggrega per ORGANIZZAZIONE CKAN del catalogo di origine (il "catalogo padre":
Comune di Milano, INPS, Regione Toscana...) e non per dct:publisher, che su
dati.gov.it e' rumoroso (uffici, redazioni, denominazioni interne).

La chiave e' l'UUID dell'organizzazione, ricavato da contact_point.resource
(https://www.dati.gov.it/organization/<uuid>): resta stabile anche se l'ente
cambia denominazione.

Uso:
    python3 mqa_monitor.py
    python3 mqa_monitor.py --group-by publisher
    python3 mqa_monitor.py --catalog dati-gov-it --outdir ./mqa --min-datasets 5
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
from collections import defaultdict

BASE = "https://data.europa.eu/api/hub/search"
CKAN = "https://www.dati.gov.it/opendata"
MAX_SCORE = 405
BUCKETS = [("Excellent", 351), ("Good", 221), ("Sufficient", 121), ("Bad", 0)]
ORG_RE = re.compile(r"/organization/([0-9a-fA-F-]{8,})")

MINUSCOLE = {
    "di", "del", "dello", "della", "dei", "degli", "delle", "e", "ed", "in",
    "da", "dal", "a", "al", "per", "con", "su", "il", "lo", "la", "i", "gli",
    "le", "l", "d", "dell", "sull", "all",
}
ACRONIMI = {
    "agcm", "agcom", "agid", "anac", "anpal", "arera", "asl", "ast", "ats",
    "cnr", "consob", "crui", "enea", "inail", "inps", "ipzs", "istat",
    "ivass", "mef", "mit", "mur", "rai", "sose", "unar", "usl", "ust", "aci",
}


def bucket(score):
    for name, lo in BUCKETS:
        if score >= lo:
            return name
    return "Bad"


def titolizza(slug):
    """comune-di-milano -> Comune di Milano (fallback se manca il titolo CKAN)."""
    if not slug:
        return "(sconosciuto)"
    if slug.lower() in ACRONIMI:
        return slug.upper()
    out = []
    for i, p in enumerate(slug.replace("_", "-").split("-")):
        if not p:
            continue
        low = p.lower()
        if low in ACRONIMI:
            out.append(p.upper())
        elif i > 0 and low in MINUSCOLE:
            out.append(low)
        else:
            out.append(p.capitalize())
    testo = " ".join(out)
    return re.sub(r"\b(dell|sull|all|nell|d|l) ([A-Z\u00c0\u00c8\u00c9\u00cc\u00d2\u00d9])",
                  r"\1'\2", testo)


def _get(url, params=None, tries=5, timeout=120):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    hdr = {"User-Agent": "mqa-monitor/2.0", "Accept": "application/json"}
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=hdr)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * (i + 1))
    raise RuntimeError("richiesta fallita: %s (%s)" % (last, url))


def fetch_catalog(catalog, page_size=1000, verbose=True):
    """[(dataset_id, org_uuid, org_slug, publisher, scoring|None), ...]"""
    t0 = time.time()
    d = _get(BASE + "/search", {
        "filter": "dataset",
        "facets": json.dumps({"catalog": [catalog]}),
        "limit": page_size,
        "scroll": "true",
        "includes": "id,publisher.name,quality_meas.scoring,contact_point",
    })
    res = d["result"]
    total, sid = res["count"], res["scrollId"]
    raw = list(res["results"])
    while True:
        d = _get(BASE + "/scroll", {"scrollId": sid})
        r = d["result"]
        sid = r.get("scrollId") or sid
        batch = r.get("results") or []
        if not batch:
            break
        raw.extend(batch)
        if verbose and len(raw) % 10000 < page_size:
            print("  %d/%d (%.0fs)" % (len(raw), total, time.time() - t0), flush=True)
    if verbose:
        print("  scaricati %d/%d dataset in %.0fs" % (len(raw), total, time.time() - t0))

    rows = []
    for r in raw:
        uuid = slug = None
        for cp in r.get("contact_point") or []:
            m = ORG_RE.search(cp.get("resource") or "")
            if m:
                uuid, slug = m.group(1), cp.get("name")
                break
        rows.append((
            r.get("id"), uuid or "", slug or "",
            ((r.get("publisher") or {}).get("name") or "").strip(),
            (r.get("quality_meas") or {}).get("scoring"),
        ))
    return rows


def carica_titoli(outdir, ckan_url, verbose=True):
    """slug -> titolo leggibile. File locale, poi CKAN, poi fallback."""
    path = os.path.join(outdir, "org_titles.json")
    titoli = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            titoli = json.load(f)
        if verbose:
            print("  titoli da %s (%d enti)" % (path, len(titoli)))
    if not ckan_url:
        return titoli
    try:
        got, offset = {}, 0
        while True:
            d = _get(ckan_url.rstrip("/") + "/api/3/action/organization_list",
                     {"all_fields": "true", "limit": 1000, "offset": offset},
                     tries=2, timeout=60)
            orgs = d.get("result") or []
            if not orgs:
                break
            for o in orgs:
                if o.get("name"):
                    got[o["name"]] = o.get("title") or o["name"]
            if len(orgs) < 1000:
                break
            offset += 1000
        if got:
            titoli.update(got)
            os.makedirs(outdir, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(titoli, f, ensure_ascii=False, indent=1, sort_keys=True)
            if verbose:
                print("  titoli aggiornati da CKAN (%d enti)" % len(got))
    except Exception as e:  # noqa: BLE001
        if verbose:
            print("  CKAN non raggiungibile (%s) - uso i titoli disponibili"
                  % type(e).__name__)
    return titoli


FIELDS = ["chiave", "etichetta", "slug", "n_dataset", "media", "pct", "mediana",
          "min", "max", "rating", "n_excellent", "n_bad", "n_publisher"]


def aggregate(rows, group_by, titoli):
    scores, meta, pubs = defaultdict(list), {}, defaultdict(set)
    for _id, uuid, slug, pub, score in rows:
        if group_by == "organization":
            chiave = uuid or ("slug:" + slug if slug else "(sconosciuto)")
            etich = titoli.get(slug) or titolizza(slug)
            s = slug
        else:
            chiave = etich = pub or "(senza publisher)"
            s = ""
        meta[chiave] = (etich, s)
        if pub:
            pubs[chiave].add(pub)
        if score is not None:
            scores[chiave].append(score)

    agg = {}
    for chiave, vals in scores.items():
        vals.sort()
        n = len(vals)
        media = sum(vals) / float(n)
        etich, s = meta[chiave]
        agg[chiave] = {
            "chiave": chiave, "etichetta": etich, "slug": s, "n_dataset": n,
            "media": round(media, 2), "pct": round(media / MAX_SCORE * 100, 2),
            "mediana": vals[n // 2], "min": vals[0], "max": vals[-1],
            "rating": bucket(media),
            "n_excellent": sum(1 for x in vals if x >= 351),
            "n_bad": sum(1 for x in vals if x < 121),
            "n_publisher": len(pubs[chiave]),
        }
    return agg


def save_snapshot(agg, rows, outdir, day, catalog, group_by):
    os.makedirs(os.path.join(outdir, "aggregato"), exist_ok=True)
    os.makedirs(os.path.join(outdir, "dataset"), exist_ok=True)
    agg_path = os.path.join(outdir, "aggregato",
                            "%s_%s_%s.csv" % (catalog, group_by, day))
    with open(agg_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in sorted(agg.values(), key=lambda x: -x["media"]):
            w.writerow(r)
    ds_path = os.path.join(outdir, "dataset", "%s_%s.csv.gz" % (catalog, day))
    with gzip.open(ds_path, "wt", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["dataset_id", "org_uuid", "org_slug", "publisher", "scoring"])
        w.writerows(rows)
    return agg_path, ds_path


def load_snapshot(path):
    with open(path, encoding="utf-8") as f:
        return dict((r["chiave"], r) for r in csv.DictReader(f))


def previous_snapshot(outdir, catalog, group_by, current):
    files = sorted(glob.glob(os.path.join(
        outdir, "aggregato", "%s_%s_*.csv" % (catalog, group_by))))
    files = [f for f in files if os.path.abspath(f) != os.path.abspath(current)]
    return files[-1] if files else None


def build_report(agg, prev, day, catalog, group_by, min_datasets, top):
    L = []
    livello = ("organizzazione (catalogo di origine)" if group_by == "organization"
               else "publisher (dct:publisher)")
    tot = sum(v["n_dataset"] for v in agg.values())
    media = sum(v["media"] * v["n_dataset"] for v in agg.values()) / max(tot, 1)
    L.append("# MQA `%s` - snapshot %s\n" % (catalog, day))
    L.append("Livello di aggregazione: **%s**\n" % livello)
    L.append("- Enti monitorati: **%d**" % len(agg))
    L.append("- Dataset con scoring: **%d**" % tot)
    L.append("- Media catalogo: **%.1f/%d** (%.1f%%)\n"
             % (media, MAX_SCORE, media / MAX_SCORE * 100))

    if not prev:
        L.append("_Primo snapshot a questo livello: nessun confronto disponibile._\n")
    else:
        deltas, nuovi = [], []
        for k, cur in agg.items():
            if cur["n_dataset"] < min_datasets:
                continue
            old = prev.get(k)
            if not old:
                nuovi.append(cur)
                continue
            dm = cur["media"] - float(old["media"])
            dn = cur["n_dataset"] - int(old["n_dataset"])
            if abs(dm) >= 0.01 or dn:
                deltas.append((dm, dn, cur, old))
        spariti = [prev[k]["etichetta"] for k in prev
                   if k not in agg and int(prev[k]["n_dataset"]) >= min_datasets]

        def tbl(items, titolo):
            L.append("\n## %s\n" % titolo)
            if not items:
                L.append("_nessuno_")
                return
            L.append("| Ente | Media prec. | Media att. | \u0394 | \u0394 dataset | Rating |")
            L.append("|---|---:|---:|---:|---:|---|")
            for dm, dn, cur, old in items:
                L.append("| %s | %.1f | %.1f | %+.1f | %+d | %s |"
                         % (cur["etichetta"], float(old["media"]), cur["media"],
                            dm, dn, cur["rating"]))

        tbl(sorted([d for d in deltas if d[0] < 0], key=lambda x: x[0])[:top],
            "In calo (top %d)" % top)
        tbl(sorted([d for d in deltas if d[0] > 0], key=lambda x: -x[0])[:top],
            "In crescita (top %d)" % top)

        L.append("\n## Movimenti anagrafici\n")
        L.append("- Nuovi enti: **%d**%s" % (
            len(nuovi),
            (" - " + ", ".join(p["etichetta"] for p in nuovi[:10])) if nuovi else ""))
        L.append("- Enti spariti: **%d**%s" % (
            len(spariti), (" - " + ", ".join(spariti[:10])) if spariti else ""))

    peggiori = sorted([v for v in agg.values() if v["n_dataset"] >= min_datasets],
                      key=lambda x: x["media"])[:top]
    L.append("\n## Peggiori %d in assoluto (>=%d dataset)\n" % (top, min_datasets))
    L.append("| Ente | Dataset | Media | Rating | Bad |")
    L.append("|---|---:|---:|---|---:|")
    for v in peggiori:
        L.append("| %s | %d | %.1f | %s | %d |"
                 % (v["etichetta"], v["n_dataset"], v["media"], v["rating"], v["n_bad"]))
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="dati-gov-it")
    ap.add_argument("--outdir", default="./mqa")
    ap.add_argument("--group-by", choices=["organization", "publisher"],
                    default="organization")
    ap.add_argument("--min-datasets", type=int, default=5)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--page-size", type=int, default=1000)
    ap.add_argument("--ckan-url", default=CKAN, help="'' per non interrogare CKAN")
    args = ap.parse_args()

    day = dt.date.today().isoformat()
    print("[1/5] scarico catalogo %s ..." % args.catalog)
    rows = fetch_catalog(args.catalog, args.page_size)
    print("[2/5] risolvo i titoli degli enti ...")
    titoli = carica_titoli(args.outdir, args.ckan_url)
    print("[3/5] aggrego per %s ..." % args.group_by)
    agg = aggregate(rows, args.group_by, titoli)
    print("      %d enti" % len(agg))
    print("[4/5] salvo snapshot ...")
    agg_path, ds_path = save_snapshot(agg, rows, args.outdir, day,
                                      args.catalog, args.group_by)
    prev_path = previous_snapshot(args.outdir, args.catalog, args.group_by, agg_path)
    prev = load_snapshot(prev_path) if prev_path else None
    print("      confronto con: %s" % (prev_path or "nessuno"))
    print("[5/5] genero report ...")
    rep_path = os.path.join(args.outdir,
                            "report_%s_%s_%s.md" % (args.catalog, args.group_by, day))
    with open(rep_path, "w", encoding="utf-8") as f:
        f.write(build_report(agg, prev, day, args.catalog, args.group_by,
                             args.min_datasets, args.top))
    print("\nOK\n  %s\n  %s\n  %s" % (agg_path, ds_path, rep_path))


if __name__ == "__main__":
    main()
