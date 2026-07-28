# jarvis-docs

Documentazione di JARVIS OS. Quattro documenti, quattro domande diverse.

| Documento | Risponde a | Per chi |
|---|---|---|
| [`00-architettura-proposta.md`](00-architettura-proposta.md) | **perché** è fatto così | chi valuta o mette in discussione una scelta |
| [`01-jcp-specifica.md`](01-jcp-specifica.md) | **cosa** deve fare un backend | chi implementa il protocollo |
| [`02-sdk.md`](02-sdk.md) | **come** si estende | chi scrive un adapter o un plugin |
| [`03-simulazione-e-replay.md`](03-simulazione-e-replay.md) | come si **prova** e si **riproduce** un difetto | chi sviluppa o diagnostica |
| [`04-riferimento-tecnico.md`](04-riferimento-tecnico.md) | **com'è fatto** | chi lavora sul codice |

## Da dove cominciare

**Devo collegare il mio backend.** `01` per il contratto, `02 §1` per
l'adapter, poi `python tools/jcp_validate.py --url …` per il verdetto.

**Devo scrivere un backend da zero.** `examples/minimal-backend/backend.py` è
il riferimento di ciò che è obbligatorio; `jarvis-sim` di ciò che è possibile.
`01 §10` elenca i punti di conformità.

**Devo lavorare sull'interfaccia.** `04` per la mappa, `03` per far succedere a
comando ciò che serve vedere.

**Devo capire perché una cosa è così.** `00`. Ogni decisione ha la sua
motivazione accanto, e le alternative scartate sono dichiarate.

## Una regola di scrittura

Questi documenti dicono anche ciò che **non** funziona: il caricatore dei
plugin non è ancora nell'applicazione, il dialetto di OpenClaw è provvisorio,
i plugin girano senza sandbox. Una documentazione che tace i limiti si scopre
inaffidabile nel momento peggiore, cioè quando qualcuno ci ha già costruito
sopra.
