# tools

Utilità di sviluppo per l'ecosistema JCP.

## `jcp_validate.py`

Esegue i controlli di conformità della specifica contro un backend reale o
simulato. Restituisce `0` se conforme, `1` altrimenti: utilizzabile in
integrazione continua senza interpretare l'output.

```bash
python tools/jcp_validate.py --url ws://127.0.0.1:8765
python tools/jcp_validate.py --scenario nominale --json
```

## `jarvis-sim`

Installato dal pacchetto `jarvis-sim`: server JCP autonomo guidato da scenari
riproducibili.

```bash
jarvis-sim --list                        # elenca gli scenari
jarvis-sim --scenario tempesta           # avvia il server
jarvis-sim --scenario nominale --export scenario.json
jarvis-sim --file scenario.json --seed 42
```
