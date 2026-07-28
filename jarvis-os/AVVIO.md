# Avviare J.A.R.V.I.S.

Serve **Python 3.11 o superiore**. Nient'altro: il backend simulato è incluso,
quindi Jarvis parte e funziona anche senza OpenClaw.

Controlla la versione:

```bash
python --version        # su Linux/macOS spesso è python3 --version
```

Se è più vecchia di 3.11, installala da [python.org](https://www.python.org/downloads/)
— su Windows spunta **"Add Python to PATH"** durante l'installazione.

---

## 1. Prendere il codice

```bash
git clone https://github.com/vitovelvi/Sito-Web-Osteria-del-Vicario.git
cd Sito-Web-Osteria-del-Vicario
git checkout claude/jarvis-desktop-interface-bvpdlj
cd jarvis-os/jarvis-desktop
```

## 2. Installare

I cinque pacchetti sono locali e non stanno su PyPI: vanno installati insieme,
in un solo comando.

**Windows (PowerShell o cmd)**

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ..\jarvis-protocol -e ..\jarvis-sdk -e ..\jarvis-sim -e ..\openclaw-adapter -e .
```

**macOS / Linux**

```bash
python3 -m venv .venv
.venv/bin/pip install -e ../jarvis-protocol -e ../jarvis-sdk -e ../jarvis-sim -e ../openclaw-adapter -e .
```

Scarica Qt: la prima volta sono qualche centinaio di megabyte.

## 3. Avviare

**Windows**

```powershell
.venv\Scripts\jarvis
```

**macOS / Linux**

```bash
.venv/bin/jarvis
```

È tutto. Parte in circa mezzo secondo, si collega al backend simulato e dopo un
attimo la striscia in basso scrive **JARVIS ONLINE**.

---

## Cosa si può fare da subito

| Tasto | Cosa apre |
|---|---|
| **F9** | barra operativa: missioni, coda di esecuzione, cronologia |
| **F12** | Developer Console: eventi, servizi, metriche, traffico JCP, sessione |

La finestra è senza cornice: si sposta trascinando la barra in alto, si
ridimensiona dai bordi. Il pulsante **⇧** la tiene sempre in primo piano.

> **Nota onesta**: non c'è ancora un campo dove scrivere. La chat è la fase 4;
> oggi Jarvis mostra tutto ciò che il backend dichiara ma non ha ancora un modo
> per riceverne l'input. Per vederlo lavorare si usano gli scenari di
> simulazione (sotto).

## Vederlo lavorare

```bash
.venv/bin/jarvis --transport sim --scenario tempesta
```

Gli scenari sono situazioni riproducibili — rete che cade, backend che non
risponde, conferme distruttive, carico:

```bash
.venv/bin/jarvis-sim --list
```

## Collegarlo a OpenClaw (quando sarà pronto)

```bash
.venv/bin/jarvis --url ws://127.0.0.1:8765/jarvis
```

Se OpenClaw non parla JCP nativamente serve l'adapter:

```bash
.venv/bin/jarvis --url ws://... --transport websocket
# e in settings.json: "backend": { "adapter": "openclaw" }
```

Per sapere se un backend è conforme prima ancora di collegarlo:

```bash
.venv/bin/python ../tools/jcp_validate.py --url ws://127.0.0.1:8765
```

---

## Se qualcosa non va

**"No module named 'PySide6'"** — hai lanciato il Python di sistema invece di
quello dell'ambiente. Usa il percorso completo (`.venv\Scripts\jarvis` o
`.venv/bin/jarvis`), oppure attiva l'ambiente: `.venv\Scripts\activate` su
Windows, `source .venv/bin/activate` altrove.

**"Could not load the Qt platform plugin xcb"** (solo Linux) — mancano le
librerie di sistema di Qt, e l'errore non dice quali:

```bash
sudo apt-get install -y libxcb-cursor0 libxkbcommon-x11-0 libegl1 libgl1 \
                        libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xkb1
```

**La finestra è nera o con bordi strani** — compositing assente o driver
grafico datato:

```bash
.venv/bin/jarvis --no-translucent
```

**Resta su "Connessione a Jarvis…"** — è il comportamento previsto quando il
backend non risponde: l'interfaccia non si blocca e continua a riprovare. F12 →
**Diagnostica** dice a che punto è, F12 → **Traffico JCP** se qualcosa è
davvero arrivato.

**Voglio vedere cosa succede** — i log stanno in
`%LOCALAPPDATA%\Jarvis\log` (Windows), `~/Library/Logs/Jarvis` (macOS),
`~/.local/state/Jarvis/log` (Linux). Con `--log-level DEBUG` diventano
verbosi.

## Dove finiscono i tuoi file

Configurazione e log **non** stanno nella cartella del programma: usano le
directory standard del sistema, così un aggiornamento non li cancella e
l'installazione può stare in sola lettura.

| | Configurazione | Log |
|---|---|---|
| Windows | `%APPDATA%\Jarvis` | `%LOCALAPPDATA%\Jarvis\log` |
| macOS | `~/Library/Application Support/Jarvis` | `~/Library/Logs/Jarvis` |
| Linux | `~/.config/Jarvis` | `~/.local/state/Jarvis/log` |

Nessuna chiave API sta nel codice o nella configurazione: i segreti vivono nel
portachiavi del sistema operativo.
