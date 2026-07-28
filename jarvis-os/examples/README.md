# examples

Riferimenti eseguibili per chi implementa un backend JCP.

## `minimal-backend/`

Il backend più piccolo che supera la verifica di conformità: circa centoventi
righe, nessuna dipendenza oltre a `jarvis-protocol` e `websockets`.

Serve come riferimento di **ciò che è obbligatorio**: tutto quello che c'è
dentro è necessario, tutto ciò che manca è facoltativo.

```bash
python examples/minimal-backend/backend.py &
python tools/jcp_validate.py --url ws://127.0.0.1:8765
```

Per un riferimento **completo** — missioni, azioni, conferme, stream audio,
guasti di canale — c'è l'ambiente di simulazione:

```bash
jarvis-sim --list
jarvis-sim --scenario rete-instabile
```
