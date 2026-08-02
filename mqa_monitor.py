#!/usr/bin/env python3
"""
Monitoraggio settimanale dello scoring MQA (data.europa.eu) per publisher.

- Scorre l'intero catalogo via scroll API (nessun limite dei 10.000 risultati)
- Aggrega quality_meas.scoring per publisher
- Salva uno snapshot datato e confronta con il precedente
- Produce un report Markdown con chi sale e chi scende

Uso:
    python3 mqa_monitor.py                    # catalogo dati-gov-it
    python3 mqa_monitor.py --catalog dati-gov-it --outdir ./mqa
    python3 mqa_monitor.py --min-datasets 5   # ignora publisher con pochi dataset
"""

import argparse
import csv
import datetime as dt
import glob
import gzip
import json
import os
import time
import urllib.parse
import urllib.request
from collections import defaultdict

BASE = "https://data.europa.eu/api/hub/search"
MAX_SCORE = 405
# soglie ufficiali MQA
BUCKETS = [("Excellent", 351), ("Good", 221), ("Sufficient", 121), ("Bad", 0)]


def bucket(score):
    for name, lo in BUCKETS:
        if score >= lo:
            return name
    return "Bad"


def _get(url, params, tries=5, timeout=120):
    q = urllib.parse.urlencode(params)
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(
                f"{url}?{q}", headers={"User-Agent": "mqa-monitor/1.0"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"richiesta fallita: {last}")


def fetch_catalog(catalog, page_size=1000, verbose=True):
    """Restituisce [(dataset_id, publisher, scoring|None), ...] per l'intero catalogo."""
    t0 = time.time()
    d = _get(
        f"{BASE}/search",
        {
            "filter": "dataset",
            "facets": json.dumps({"catalog": [catalog]}),
            "limit": page_size,
            "scroll": "true",
            "includes": "id,publisher.name,quality_meas.scoring",
        },
    )
    res = d["result"]
    total, sid = res["count"], res["scrollId"]
    rows = list(res["results"])
    while True:
        d = _get(f"{BASE}/scroll", {"scrollId": sid})
        r = d["result"]
        sid = r.get("scrollId") or sid
        batch = r.get("results") or []
        if not batch:
            break
        rows.extend(batch)
        if verbose and len(rows) % 10000 < page_size:
            print(f"  {len(rows)}/{total} ({time.time()-t0:.0f}s)", flush=True)
    if verbose:
        print(f"  scaricati {len(rows)}/{total} dataset in {time.time()-t0:.0f}s")
    out = []
    for r in rows:
        out.append(
            (
                r.get("id"),
                ((r.get("publisher") or {}).get("name") or "(senza publisher)").strip(),
                (r.get("quality_meas") or {}).get("scoring"),
            )
        )
    return out


def aggregate(rows):
    per = defaultdict(list)
    for _id, pub, score in rows:
        if score is not None:
            per[pub].append(score)
    agg = {}
    for pub, scores in per.items():
        scores.sort()
        n = len(scores)
        mean = sum(scores) / n
        agg[pub] = {
            "publisher": pub,
            "n_dataset": n,
            "media": round(mean, 2),
            "pct": round(mean / MAX_SCORE * 100, 2),
            "mediana": scores[n // 2],
            "min": scores[0],
            "max": scores[-1],
            "rating": bucket(mean),
            "n_excellent": sum(1 for s in scores if s >= 351),
            "n_bad": sum(1 for s in scores if s < 121),
        }
    return agg


FIELDS = [
    "publisher", "n_dataset", "media", "pct", "mediana",
    "min", "max", "rating", "n_excellent", "n_bad",
]


def save_snapshot(agg, rows, outdir, day, catalog):
    os.makedirs(f"{outdir}/publisher", exist_ok=True)
    os.makedirs(f"{outdir}/dataset", exist_ok=True)
    pub_path = f"{outdir}/publisher/{catalog}_{day}.csv"
    with open(pub_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in sorted(agg.values(), key=lambda x: -x["media"]):
            w.writerow(r)
    ds_path = f"{outdir}/dataset/{catalog}_{day}.csv.gz"
    with gzip.open(ds_path, "wt", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["dataset_id", "publisher", "scoring"])
        w.writerows(rows)
    return pub_path, ds_path


def load_snapshot(path):
    with open(path, encoding="utf-8") as f:
        return {r["publisher"]: r for r in csv.DictReader(f)}


def previous_snapshot(outdir, catalog, current_path):
    files = sorted(glob.glob(f"{outdir}/publisher/{catalog}_*.csv"))
    files = [f for f in files if os.path.abspath(f) != os.path.abspath(current_path)]
    return files[-1] if files else None


def build_report(agg, prev, day, catalog, min_datasets, top):
    L = []
    tot_ds = sum(v["n_dataset"] for v in agg.values())
    media_cat = sum(v["media"] * v["n_dataset"] for v in agg.values()) / max(tot_ds, 1)
    L.append(f"# MQA `{catalog}` — snapshot {day}\n")
    L.append(f"- Publisher monitorati: **{len(agg)}**")
    L.append(f"- Dataset con scoring: **{tot_ds}**")
    L.append(f"- Media catalogo: **{media_cat:.1f}/{MAX_SCORE}** ({media_cat/MAX_SCORE*100:.1f}%)\n")

    if not prev:
        L.append("_Primo snapshot: nessun confronto disponibile._\n")
    else:
        deltas, nuovi = [], []
        for pub, cur in agg.items():
            if cur["n_dataset"] < min_datasets:
                continue
            old = prev.get(pub)
            if not old:
                nuovi.append(cur)
                continue
            d_media = cur["media"] - float(old["media"])
            d_n = cur["n_dataset"] - int(old["n_dataset"])
            if abs(d_media) >= 0.01 or d_n:
                deltas.append((d_media, d_n, cur, old))
        spariti = [p for p in prev if p not in agg and int(prev[p]["n_dataset"]) >= min_datasets]

        saliti = sorted([d for d in deltas if d[0] > 0], key=lambda x: -x[0])[:top]
        scesi = sorted([d for d in deltas if d[0] < 0], key=lambda x: x[0])[:top]

        def tbl(items, title):
            L.append(f"\n## {title}\n")
            if not items:
                L.append("_nessuno_")
                return
            L.append("| Publisher | Media prec. | Media att. | Δ | Δ dataset | Rating |")
            L.append("|---|---:|---:|---:|---:|---|")
            for dm, dn, cur, old in items:
                L.append(
                    f"| {cur['publisher']} | {float(old['media']):.1f} | {cur['media']:.1f} "
                    f"| {dm:+.1f} | {dn:+d} | {cur['rating']} |"
                )

        tbl(scesi, f"In calo (top {top})")
        tbl(saliti, f"In crescita (top {top})")

        L.append("\n## Movimenti anagrafici\n")
        L.append(f"- Nuovi publisher: **{len(nuovi)}**"
                 + (" — " + ", ".join(p["publisher"] for p in nuovi[:10]) if nuovi else ""))
        L.append(f"- Publisher spariti: **{len(spariti)}**"
                 + (" — " + ", ".join(spariti[:10]) if spariti else ""))

    peggiori = sorted(
        [v for v in agg.values() if v["n_dataset"] >= min_datasets],
        key=lambda x: x["media"],
    )[:top]
    L.append(f"\n## Peggiori {top} publisher assoluti (≥{min_datasets} dataset)\n")
    L.append("| Publisher | Dataset | Media | Rating | Bad |")
    L.append("|---|---:|---:|---|---:|")
    for v in peggiori:
        L.append(f"| {v['publisher']} | {v['n_dataset']} | {v['media']:.1f} | {v['rating']} | {v['n_bad']} |")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="dati-gov-it")
    ap.add_argument("--outdir", default="./mqa")
    ap.add_argument("--min-datasets", type=int, default=3)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--page-size", type=int, default=1000)
    args = ap.parse_args()

    day = dt.date.today().isoformat()
    print(f"[1/4] scarico catalogo {args.catalog} …")
    rows = fetch_catalog(args.catalog, args.page_size)
    print("[2/4] aggrego per publisher …")
    agg = aggregate(rows)
    print(f"      {len(agg)} publisher")
    print("[3/4] salvo snapshot …")
    pub_path, ds_path = save_snapshot(agg, rows, args.outdir, day, args.catalog)
    prev_path = previous_snapshot(args.outdir, args.catalog, pub_path)
    prev = load_snapshot(prev_path) if prev_path else None
    print(f"      confronto con: {prev_path or 'nessuno'}")
    print("[4/4] genero report …")
    report = build_report(agg, prev, day, args.catalog, args.min_datasets, args.top)
    rep_path = f"{args.outdir}/report_{args.catalog}_{day}.md"
    with open(rep_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\nOK\n  {pub_path}\n  {ds_path}\n  {rep_path}")


if __name__ == "__main__":
    main()
