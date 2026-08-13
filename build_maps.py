#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_maps.py - genera docs/maps_data.json per le due mappe del monitoraggio MQA.

  1) Mappa puntuale COMUNI      -> livello TITOLARI (dct:rightsHolder + dct:identifier)
  2) Mappa coropletica REGIONI  -> livello ORGANIZZAZIONI, ristretto ai cataloghi
                                   regionali effettivamente federati su dati.gov.it
                                   (fonte: harvest_source_list)

Enti centrali, agenzie, partecipate, universita', ASL, consorzi: esclusi.

Dipendenze: solo stdlib.
Input : docs/data.json, docs/comuni_coords.json
Output: docs/maps_data.json
"""

import json
import os
import time
import re
import sys
import unicodedata
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "docs")
DATA_JSON = os.path.join(DOCS, "data.json")
COORDS_JSON = os.path.join(DOCS, "comuni_coords.json")
OUT_JSON = os.path.join(DOCS, "maps_data.json")

HARVEST_API = "https://dati.gov.it/opendata/api/3/action/harvest_source_list"

# Titolare comunale con codice IPA formalmente valido: c_ + catastale (lettera + 3 cifre)
RE_IPA_COMUNE = re.compile(r"^c_[a-z]\d{3}$", re.I)
# Titolare il cui nome dichiara un comune ma il cui identificativo e' fuori standard
RE_NOME_COMUNE = re.compile(r"^(comune|citta|citt\u00e0)\b", re.I)
# Le Citta' metropolitane sono enti di area vasta, non comuni: fuori dalla mappa
RE_AREA_VASTA = re.compile(r"^citt[a\u00e0]\s+metropolitana", re.I)

# Sorgenti di harvest regionali/PA -> territorio della mappa.
# La chiave e' il "title" della sorgente su dati.gov.it.
CATALOGHI_REGIONALI = {
    "Regione Piemonte": "Piemonte",
    "Regione Lombardia": "Lombardia",
    "Provincia Autonoma di Trento": "P.A. Trento",
    "Provincia Bolzano": "P.A. Bolzano",
    "Regione Veneto": "Veneto",
    "Regione Friuli Venezia-Giulia": "Friuli-Venezia Giulia",
    "Regione Liguria": "Liguria",
    "Regione Emilia-Romagna": "Emilia-Romagna",
    "Regione Toscana": "Toscana",
    "Regione Umbria": "Umbria",
    "Regione Marche": "Marche",
    "Regione Lazio": "Lazio",
    "Regione Campania": "Campania",
    "Regione Puglia": "Puglia",
    "Regione Basilicata": "Basilicata",
    "Regione Calabria": "Calabria",
    "Regione Siciliana": "Sicilia",
}

# Il titolo della sorgente di harvest non sempre coincide con il nome
# dell'organizzazione in data.json.
ALIAS_ORGANIZZAZIONE = {
    "Provincia Bolzano": "Provincia Autonoma di Bolzano",
    "Regione Emilia-Romagna": "Regione Emilia Romagna",
    "Regione Friuli Venezia-Giulia": "Regione Friuli Venezia Giulia",
}

# Chiavi del geojson regioni_split.geojson (proprieta' "terr")
TERRITORI = [
    "Piemonte", "Valle d'Aosta/Vall\u00e9e d'Aoste", "Lombardia",
    "P.A. Trento", "P.A. Bolzano", "Veneto", "Friuli-Venezia Giulia",
    "Liguria", "Emilia-Romagna", "Toscana", "Umbria", "Marche", "Lazio",
    "Abruzzo", "Molise", "Campania", "Puglia", "Basilicata", "Calabria",
    "Sicilia", "Sardegna",
]

# Comuni soppressi o denominazioni non risolvibili: mappatura manuale.
# None = da escludere (ente non piu' esistente).
OVERRIDE_COMUNI = {
    "comune di genova - musei e biblioteche": "c_d969",
    "comune di vodo di cadore": "c_m108",
    "comune di lentiai": None,          # fuso in Borgo Valbelluna (2019)
    "comune di castellavazzo": None,    # fuso in Longarone (2016)
    "comune di santa caterina d'este": None,  # non e' un comune
}

# Codici IPA errati riscontrati sui titolari: correzione verso il codice reale.
# None = ente soppresso, il dato non viene mappato.
OVERRIDE_CODICI = {
    "c_l390": "c_i390",   # San Vincenzo (LI)
    "c_l344": "c_i344",   # Sant'Ippolito (PU)
    "c_f633": "c_f653",   # Monte Urano (FM)
    "c_e667": "c_m312",   # Lonato del Garda (BS)
    "c_f474": None,       # Monteciccardo, fuso in Pesaro (2024)
    "c_969": "c_d969",    # Genova
    "c_cp112": "c_m323",  # Castelfranco Piandiscò
}


def norm(s):
    """Normalizzazione per il confronto fra denominazioni."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", s.lower())


def norm_comune(s):
    """Normalizzazione specifica per i nomi di comune."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"^(comune|citta|city)\s+(di|del|della|dello|delle|dei|d')?\s*", "", s.strip())
    s = re.sub(r"\s*-\s*(istituzione|servizio|ufficio|settore|direzione|area|dipartimento).*$", "", s)
    return re.sub(r"[^a-z]", "", s)


def carica_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def scarica_harvest():
    """Elenco dei cataloghi federati su dati.gov.it, con copia locale.

    L'API risponde 500 a intermittenza, e quando succede le mappe non venivano
    piu' rigenerate: l'elenco dei cataloghi federati cambia pero' di rado — sono
    17 e restano tali per mesi — quindi si conserva l'ultima risposta buona in
    docs/harvest.json e la si riusa quando la chiamata fallisce. Se non c'e' ne'
    rete ne' copia, allora si esce con errore: proseguire senza elenco
    produrrebbe una mappa con tutte le regioni in grigio.
    """
    copia = os.path.join(HERE, "mqa", "harvest.json")
    try:
        req = urllib.request.Request(HARVEST_API,
                                     headers={"User-Agent": "mqa-monitor/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            elenco = json.load(resp)["result"]
        with open(copia, "w", encoding="utf-8") as fh:
            json.dump(elenco, fh, ensure_ascii=False)
        return elenco
    except Exception as e:  # noqa: BLE001
        if not os.path.exists(copia):
            raise
        eta = (time.time() - os.path.getmtime(copia)) / 86400
        print("  elenco non raggiungibile (%s): uso la copia locale, %d giorni"
              % (type(e).__name__, eta))
        with open(copia, encoding="utf-8") as fh:
            return json.load(fh)


# --------------------------------------------------------------------------
# Mappa 1 - comuni (livello titolari)
# --------------------------------------------------------------------------

def costruisci_comuni(data, coords):
    enti = data["livelli"]["holder"]["enti"]

    per_nome = {}
    for cod, v in coords.items():
        per_nome.setdefault(norm_comune(v[2]), []).append(cod)

    acc = {}
    scartati = []

    def risolvi(ente):
        ident = ente["id"].strip()
        low = ident.lower()

        if low in OVERRIDE_CODICI:
            return OVERRIDE_CODICI[low], "codice_corretto"
        if RE_IPA_COMUNE.match(ident):
            return (low, "codice_ipa") if low in coords else (None, "codice_ignoto")

        if RE_AREA_VASTA.match(ente["nome"].strip()):
            return None, "non_comune"
        if not RE_NOME_COMUNE.match(ente["nome"].strip()):
            return None, "non_comune"

        chiave = ente["nome"].strip().lower()
        if chiave in OVERRIDE_COMUNI:
            return OVERRIDE_COMUNI[chiave], "override_nome"

        cand = per_nome.get(norm_comune(ente["nome"]), [])
        if len(cand) == 1:
            return cand[0], "nome"
        return None, "ambiguo" if cand else "non_risolto"

    for ente in enti:
        cod, motivo = risolvi(ente)
        if cod is None:
            if motivo not in ("non_comune", "codice_ignoto"):
                scartati.append({"id": ente["id"], "nome": ente["nome"],
                                 "n": ente["n"], "motivo": motivo})
            continue

        lat, lon, nome, reg, prov = coords[cod]
        rec = acc.setdefault(cod, {
            "cod": cod, "nome": nome, "reg": reg, "prov": prov,
            "lat": lat, "lon": lon, "n": 0, "somma": 0.0, "fonti": [],
            "reg_cat": None,
        })
        rec["n"] += ente["n"]
        rec["somma"] += ente["media"] * ente["n"]
        rec["fonti"].append({"id": ente["id"], "n": ente["n"],
                             "mqa": ente["media"], "via": motivo})
        # se anche uno solo dei titolari ricondotti al comune arriva dal
        # catalogo della propria Regione, il comune vi e' federato
        if ente.get("reg"):
            rec["reg_cat"] = ente["reg"]

    comuni = []
    for rec in acc.values():
        if rec["n"] <= 0:
            continue
        mqa = round(rec["somma"] / rec["n"], 1)
        comuni.append({
            "cod": rec["cod"], "nome": rec["nome"], "reg": rec["reg"],
            "prov": rec["prov"], "lat": rec["lat"], "lon": rec["lon"],
            "n": rec["n"], "mqa": mqa, "rating": rating(mqa),
            "fonti": len(rec["fonti"]), "cat": rec["reg_cat"],
        })

    comuni.sort(key=lambda x: -x["n"])
    return comuni, scartati


# --------------------------------------------------------------------------
# Mappa 2 - regioni (livello organizzazioni, cataloghi federati)
# --------------------------------------------------------------------------

def costruisci_regioni(data, harvest):
    orgs = data["livelli"]["organization"]["enti"]
    per_nome = {norm(o["nome"]): o for o in orgs}

    trovati = {}
    for src in harvest:
        terr = CATALOGHI_REGIONALI.get((src.get("title") or "").strip())
        if not terr:
            continue
        titolo_org = ALIAS_ORGANIZZAZIONE.get(src["title"], src["title"])
        org = per_nome.get(norm(titolo_org))
        if org is None:
            print("  [!] catalogo federato senza organizzazione: %s" % src["title"],
                  file=sys.stderr)
            continue
        dominio = re.sub(r"^https?://", "", src["url"]).split("/")[0]
        trovati[terr] = {
            "terr": terr, "catalogo": src["title"], "dominio": dominio,
            "url": src["url"], "attivo": bool(src.get("active")),
            "n": org["n"], "mqa": org["media"], "rating": org["rating"],
            "dim": org.get("dim", {}), "org": org["nome"],
        }

    regioni = []
    for terr in TERRITORI:
        if terr in trovati:
            regioni.append(trovati[terr])
        else:
            regioni.append({"terr": terr, "catalogo": None, "dominio": None,
                            "url": None, "attivo": False, "n": 0, "mqa": None,
                            "rating": None, "dim": {}, "org": None})
    return regioni


def rating(mqa):
    if mqa is None:
        return None
    if mqa >= 351:
        return "Excellent"
    if mqa >= 221:
        return "Good"
    if mqa >= 121:
        return "Sufficient"
    return "Bad"


def main():
    print("build_maps.py - generazione dati mappe")

    data = carica_json(DATA_JSON)
    coords = carica_json(COORDS_JSON)
    print("  data.json aggiornato al %s | coordinate: %d comuni"
          % (data.get("aggiornato"), len(coords)))

    print("  scarico l'elenco dei cataloghi federati...")
    harvest = scarica_harvest()
    print("  sorgenti di harvest: %d (%d attive)"
          % (len(harvest), sum(1 for s in harvest if s.get("active"))))

    comuni, scartati = costruisci_comuni(data, coords)
    regioni = costruisci_regioni(data, harvest)

    federati = [r for r in regioni if r["catalogo"]]
    out = {
        "aggiornato": data.get("aggiornato"),
        "catalogo": data.get("catalogo"),
        "max_score": data.get("max_score", 405),
        "comuni": comuni,
        "regioni": regioni,
        "scartati": scartati,
        "totali": {
            "comuni": len(comuni),
            "dataset_comuni": sum(c["n"] for c in comuni),
            "regioni_federate": len(federati),
            "regioni_totali": len(regioni),
            "dataset_regioni": sum(r["n"] for r in federati),
        },
    }

    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))

    t = out["totali"]
    print("  comuni mappati      : %d (%d dataset)" % (t["comuni"], t["dataset_comuni"]))
    print("  territori federati  : %d/%d (%d dataset)"
          % (t["regioni_federate"], t["regioni_totali"], t["dataset_regioni"]))
    print("  titolari non mappati: %d" % len(scartati))
    print("  scritto %s (%.0f KB)" % (OUT_JSON, os.path.getsize(OUT_JSON) / 1024))


if __name__ == "__main__":
    main()
