# Passaggi per il trasferimento su repository AgID

Da fare **quando** il codice viene trasferito nella repository ufficiale AgID.
Fino ad allora la dashboard resta su `piersoft/mqa-monitor` e su GitHub Pages.

## 1. Riferimenti a `piersoft`

Vanno cambiati tutti gli indirizzi che puntano al repository o alle Pages
personali. I punti noti:

- `docs/index.html` — collegamento nelle note in fondo
  (`github.com/piersoft/mqa-monitor`)
- `docs/mappe.html` — stesso collegamento nel piè di pagina
- `docs/incorpora.html` — l'esempio di `iframe` e il controllo `ev.origin`
  (`https://piersoft.github.io`), piu' i riferimenti nel testo
- `README.md` — indirizzo della pagina pubblica e tutti gli esempi di link
  diretti (`https://piersoft.github.io/mqa-monitor/?titolare=...`)
- `.github/workflows/mqa-weekly.yml` — nessun riferimento esplicito, ma va
  verificato che i permessi e il nome del bot restino validi

Verifica con:

    grep -rn "piersoft" --include="*.html" --include="*.md" --include="*.yml" .

Attenzione: cambiando dominio cambia anche l'indirizzo citabile dato alle PA
per vedere i propri dati. Se qualcuno li ha gia' salvati, vale la pena tenere
un redirect dalle vecchie Pages.

## 2. Crediti

Da aggiungere nelle note in fondo di entrambe le pagine e nel README.
Da definire la formula esatta con AgID: chi ha scritto il codice, chi lo
mantiene, la licenza.

Nel repository di Cruscotto Italia la licenza del codice e' AGPL-3.0 e quella
dei contenuti CC-BY 4.0: conviene allinearsi, se non c'e' una ragione contraria.

## 3. Testata istituzionale

Aggiungere la `.mini-mast` con il logo AgID, come in
`AgID/cruscotto-italia/frontend` (`css/base.css`, classi `.mini-mast`,
`.mini-brand`, `.mini-agid`, `.mini-agid-logo`, `.mini-agid-claim`).

Da valutare in quel momento: la `.mini-mast` include anche la ricerca comune di
Cruscotto, che qui non serve. Va presa la sola parte di intestazione.

## 4. Font self-hosted — solo se il codice entra in dati.gov.it

Oggi Titillium Web e Roboto Mono arrivano da Google Fonts. Se la pagina viene
inclusa in dati.gov.it, vanno serviti dallo stesso dominio come fa Cruscotto
Italia: WOFF2 in `vendor/fonts/`, dichiarati con `@font-face` e con gli hash
SRI gia' presenti in `frontend/css/tokens.css`.

Motivo: dentro il portale una chiamata a un dominio esterno per i font e' una
dipendenza in piu' e un ritardo di rendering, oltre a un tema di privacy.
Finche' la pagina resta autonoma su Pages, Google Fonts va bene.

## Nota sui token

Lo stile e' gia' allineato a `frontend/css/tokens.css` di Cruscotto Italia, con
due scostamenti voluti per WCAG 2.1 AA, documentati nel commento in cima al CSS:

- i bordi dei controlli usano `--mute` e non `--border` (#e3e7eb sta a 1,24:1,
  sotto il 3:1 del criterio 1.4.11)
- "Sufficient" usa #8a5300 invece di `--warning` #a66300, che su fondo #f5f6f7
  si ferma a 4,40:1

Entrambi valgono anche per Cruscotto Italia, dove `--mute-soft` (#8a95a1, 3,05:1)
e' usato per metadati testuali: sotto la soglia per il testo.
