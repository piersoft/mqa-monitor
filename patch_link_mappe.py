#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_link_mappe.py - aggiunge il collegamento alle mappe nell'header di docs/index.html.

Idempotente: se il collegamento c'e' gia', non tocca nulla.
"""

import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, "docs", "index.html")

ANCORA_CSS = "/* ---------- controlli ---------- */"
CSS = """/* ---------- collegamento alle mappe ---------- */
.vai-mappe{
  display:inline-flex;align-items:baseline;gap:11px;margin-top:22px;
  padding:11px 16px;background:#fff;border:1px solid var(--inchiostro);
  color:var(--inchiostro);text-decoration:none
}
.vai-mappe .voce{font-family:var(--condensato);font-size:16px;font-weight:600;letter-spacing:.005em}
.vai-mappe .glossa{font-family:var(--mono);font-size:10.5px;letter-spacing:.09em;
  text-transform:uppercase;color:var(--tenue)}
.vai-mappe .freccia{font-family:var(--mono);font-size:14px;line-height:1;margin-left:2px}
.vai-mappe:hover,.vai-mappe:focus-visible{background:var(--inchiostro);color:#fff}
.vai-mappe:hover .glossa,.vai-mappe:focus-visible .glossa{color:#b9c6cd}
.vai-mappe:focus-visible{outline:2px solid var(--inchiostro);outline-offset:2px}
@media (max-width:520px){
  .vai-mappe{flex-wrap:wrap;gap:4px 10px}
}

"""

ANCORA_HTML = '  <div class="misure">'
HTML = """  <a class="vai-mappe" href="mappe.html">
    <span class="voce">Guarda le mappe</span>
    <span class="glossa">Comuni e cataloghi regionali</span>
    <span class="freccia" aria-hidden="true">&rarr;</span>
  </a>
"""


def main():
    if not os.path.exists(INDEX):
        sys.exit("non trovo %s" % INDEX)

    with io.open(INDEX, encoding="utf-8") as fh:
        testo = fh.read()

    if "vai-mappe" in testo:
        print("il collegamento c'e' gia', nessuna modifica")
        return

    for ancora in (ANCORA_CSS, ANCORA_HTML):
        if testo.count(ancora) != 1:
            sys.exit("ancora non univoca in index.html: %r (%d occorrenze)"
                     % (ancora, testo.count(ancora)))

    testo = testo.replace(ANCORA_CSS, CSS + ANCORA_CSS, 1)
    testo = testo.replace(ANCORA_HTML, HTML + ANCORA_HTML, 1)

    with io.open(INDEX, "w", encoding="utf-8") as fh:
        fh.write(testo)

    print("aggiunto il collegamento alle mappe in docs/index.html")


if __name__ == "__main__":
    main()
