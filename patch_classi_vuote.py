#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_classi_vuote.py - le classi senza enti non partecipano ai filtri di docs/mappe.html.

Il difetto: isolando una classe venivano escluse tutte le altre, comprese
quelle con zero enti. Riaccendendone una, le vuote restavano formalmente
escluse: il pulsante di ripristino restava acceso senza che nulla fosse
davvero nascosto. Vale sia per il filtro dei colori sia per quello delle fasce.

Idempotente: se la patch c'e' gia', non tocca nulla.
"""

import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PAGINA = os.path.join(HERE, "docs", "mappe.html")

SOSTITUZIONI = [
    # 1. Helper condivisi + i due controlli "filtro attivo" ignorano le vuote
    ("""function filtroAttivo(){
  return elencoAttivo().some(function(cl){ return stato.escluse[chiaveClasse(cl)]; });
}
function filtroTagliaAttivo(){
  return CLASSI_N.some(function(cl){ return stato.escluse[chiaveTaglia(cl)]; });
}""",
     """/* Una classe senza enti non e' filtrabile: isolarla svuoterebbe la mappa, e
   soprattutto restava esclusa dopo un isolamento, tenendo acceso il pulsante
   di ripristino senza che si vedesse nulla di nascosto. */
function insiemeAttivo(){
  return stato.comuni
    ? dati.comuni
    : dati.regioni.filter(function(r){ return r.catalogo; });
}
function contaClasse(cl){
  var elenco=elencoAttivo(), perMqa=stato.metrica==="mqa";
  return insiemeAttivo().filter(function(x){
    return classe(elenco, perMqa?x.mqa:x.n)===cl;
  }).length;
}
function classiPiene(){
  return elencoAttivo().filter(function(cl){ return contaClasse(cl)>0; });
}
function contaTaglia(cl){
  return dati.comuni.filter(function(c){ return classe(CLASSI_N,c.n)===cl; }).length;
}
function tagliePiene(){
  return CLASSI_N.filter(function(cl){ return contaTaglia(cl)>0; });
}
function filtroAttivo(){
  return classiPiene().some(function(cl){ return stato.escluse[chiaveClasse(cl)]; });
}
function filtroTagliaAttivo(){
  return tagliePiene().some(function(cl){ return stato.escluse[chiaveTaglia(cl)]; });
}"""),

    # 2. La legenda dei colori usa l'helper condiviso
    ("""  var insieme = stato.comuni
    ? dati.comuni
    : dati.regioni.filter(function(r){ return r.catalogo; });
  var voce = stato.comuni ? "comuni" : "territori";""",
     """  var insieme = insiemeAttivo();
  var voce = stato.comuni ? "comuni" : "territori";"""),

    # 3. Righe dei colori: conteggio dall'helper, classi vuote non cliccabili
    ("""    var quanti=insieme.filter(function(x){
      return classe(elenco, perMqa?x.mqa:x.n)===cl;
    }).length;
    var spenta=!!stato.escluse[chiaveClasse(cl)];
    html+='<li><button type="button" class="riga-classe'+(quanti?"":" vuota")+'"'+
      ' data-classe="'+esc(cl.nome)+'" aria-pressed="'+(!spenta)+'">'+""",
     """    var quanti=contaClasse(cl);
    var spenta=!!stato.escluse[chiaveClasse(cl)];
    html+='<li><button type="button" class="riga-classe'+(quanti?"":" vuota")+'"'+
      (quanti?"":' disabled')+
      ' data-classe="'+esc(cl.nome)+'" aria-pressed="'+(!spenta)+'">'+"""),

    # 4. Righe delle fasce: stesso trattamento
    ("""      var quanti=dati.comuni.filter(function(c){ return classe(CLASSI_N,c.n)===cl; }).length;""",
     """      var quanti=contaTaglia(cl);"""),

    ("""      html+='<li><button type="button" class="riga-taglia'+(quanti?"":" vuota")+
        (spenta?" spenta":"")+'" data-taglia="'+esc(cl.nome)+'"'+
        ' aria-pressed="'+(spenta?"false":"true")+'">'+""",
     """      html+='<li><button type="button" class="riga-taglia'+(quanti?"":" vuota")+
        (spenta?" spenta":"")+'"'+(quanti?"":' disabled')+
        ' data-taglia="'+esc(cl.nome)+'"'+
        ' aria-pressed="'+(spenta?"false":"true")+'">'+"""),

    # 5. Ripristini: ripuliscono anche eventuali residui sulle vuote
    ("""  var t=e.target.closest("button[data-taglia]");
  if(t){
    var cn=CLASSI_N.filter(function(x){ return x.nome===t.dataset.taglia; })[0];
    if(!cn) return;
    var kt=chiaveTaglia(cn);
    /* stesso gesto della legenda dei colori: il primo tocco isola, i
       successivi accendono e spengono la singola fascia */
    if(!filtroTagliaAttivo()){
      CLASSI_N.forEach(function(x){ if(x!==cn) stato.escluse[chiaveTaglia(x)]=true; });
    }else if(stato.escluse[kt]){ delete stato.escluse[kt]; }""",
     """  var t=e.target.closest("button[data-taglia]");
  if(t){
    if(t.disabled) return;
    var piene=tagliePiene();
    var cn=piene.filter(function(x){ return x.nome===t.dataset.taglia; })[0];
    if(!cn) return;
    var kt=chiaveTaglia(cn);
    /* stesso gesto della legenda dei colori: il primo tocco isola, i
       successivi accendono e spengono la singola fascia */
    if(!filtroTagliaAttivo()){
      piene.forEach(function(x){ if(x!==cn) stato.escluse[chiaveTaglia(x)]=true; });
    }else if(stato.escluse[kt]){ delete stato.escluse[kt]; }"""),

    # 6. Click sui colori: solo classi popolate
    ("""  var b=e.target.closest("button[data-classe]");
  if(!b) return;
  var elenco=elencoAttivo();
  var cl=elenco.filter(function(x){ return x.nome===b.dataset.classe; })[0];
  if(!cl) return;
  var k=chiaveClasse(cl);
  /* Primo tocco quando sono tutte accese: isola la classe.
     Tocchi successivi: accende e spegne la singola classe. */
  if(!filtroAttivo()){
    elenco.forEach(function(x){
      if(x!==cl) stato.escluse[chiaveClasse(x)]=true;
    });""",
     """  var b=e.target.closest("button[data-classe]");
  if(!b || b.disabled) return;
  var piene=classiPiene();
  var cl=piene.filter(function(x){ return x.nome===b.dataset.classe; })[0];
  if(!cl) return;
  var k=chiaveClasse(cl);
  /* Primo tocco quando sono tutte accese: isola la classe.
     Tocchi successivi: accende e spegne la singola classe. */
  if(!filtroAttivo()){
    piene.forEach(function(x){
      if(x!==cl) stato.escluse[chiaveClasse(x)]=true;
    });"""),

    # 7. Niente effetto hover sui pulsanti disattivati
    (""".riga-classe:hover{background:var(--carta)}""",
     """.riga-classe:hover:not([disabled]){background:var(--carta)}
.riga-classe[disabled],.riga-taglia[disabled]{cursor:default}"""),
]


def main():
    if not os.path.exists(PAGINA):
        sys.exit("non trovo %s" % PAGINA)

    with io.open(PAGINA, encoding="utf-8") as fh:
        testo = fh.read()

    if "classiPiene" in testo:
        print("patch gia' applicata, nessuna modifica")
        return

    for n, (vecchio, _) in enumerate(SOSTITUZIONI, 1):
        quante = testo.count(vecchio)
        if quante != 1:
            sys.exit("blocco %d non univoco: %d occorrenze — nulla e' stato modificato"
                     % (n, quante))

    for vecchio, nuovo in SOSTITUZIONI:
        testo = testo.replace(vecchio, nuovo, 1)

    with io.open(PAGINA, "w", encoding="utf-8") as fh:
        fh.write(testo)

    print("applicate %d sostituzioni a docs/mappe.html" % len(SOSTITUZIONI))


if __name__ == "__main__":
    main()
