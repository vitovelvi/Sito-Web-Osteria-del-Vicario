"""Registrazione e replay delle sessioni JCP.

**La simulazione reagisce, il replay riproduce.** È la distinzione che governa
questo modulo e va tenuta ferma: uno scenario di simulazione risponde a ciò che
il client fa; una registrazione è una sequenza fissa e la ripete identica anche
se il client si comporta in modo diverso. Confonderli porta a fidarsi di un
replay come se fosse una prova funzionale, che non è.

A cosa serve il replay, allora: a **riprodurre un difetto dell'interfaccia**.
Una segnalazione smette di essere "ogni tanto la coda resta appesa" e diventa un
file da riaprire, che mostra esattamente gli stessi messaggi negli stessi
istanti.

Formato JCPL (*JCP Lines*): una riga JSON per record, la prima è l'intestazione.
Testuale di proposito — si legge con ``head``, si filtra con ``grep``, si
versiona in una segnalazione. Il costo in byte è irrilevante rispetto al valore
di poterlo aprire ovunque.

.. code-block:: text

    {"jcpl":1,"recorded_at":1730000000.0,"client":"jarvis-desktop 0.4.0", ...}
    {"t":0.000,"dir":"out","env":{"v":"1.0","t":"session.hello", ...}}
    {"t":0.412,"dir":"in","env":{"v":"1.0","t":"session.welcome", ...}}
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, TextIO

from jarvis_protocol.envelope import Envelope
from jarvis_protocol.errors import ProtocolError
from jarvis_protocol.messages import MessageType

__all__ = [
    "JCPL_VERSION",
    "Direction",
    "RecordedMessage",
    "Recording",
    "SessionRecorder",
    "SessionReplayer",
    "redact_envelope",
]

#: Versione del formato. Un lettore rifiuta ciò che non sa interpretare.
JCPL_VERSION: Final[int] = 1

#: ``out`` = dal client al backend, ``in`` = dal backend al client.
Direction = str

#: Campi il cui contenuto non finisce mai in una registrazione.
#:
#: Una registrazione nasce per essere allegata a una segnalazione, cioè per
#: uscire dalla macchina su cui è stata prodotta. Il token dell'handshake e i
#: blocchi audio non hanno motivo di viaggiare con essa: il primo è un segreto,
#: i secondi sono megabyte che non aiutano a capire nulla.
_REDACTED_PATHS: Final[tuple[tuple[str, ...], ...]] = (
    ("auth", "token"),
    ("client", "instance_id"),
)

#: Sostituto del contenuto redatto.
_REDACTED: Final[str] = "«redatto»"

#: Oltre questa dimensione il payload di uno stream viene sostituito dalla sola
#: lunghezza: conserva l'informazione utile (quanti byte, in che sequenza)
#: senza gonfiare il file.
_MAX_STREAM_CHARS: Final[int] = 64

_SECRET_KEY = re.compile(r"(?i)(token|secret|password|api[_-]?key)")


def redact_envelope(envelope: Envelope) -> Envelope:
    """Restituisce una copia della busta priva di segreti e di audio grezzo.

    Non è una funzione di sicurezza — chi ha accesso alla memoria del processo
    ha già tutto. È una funzione di **igiene**: impedisce che un segreto finisca
    per distrazione in un file destinato a essere condiviso.
    """
    payload = json.loads(json.dumps(envelope.payload))  # copia profonda

    for path in _REDACTED_PATHS:
        cursore: Any = payload
        for chiave in path[:-1]:
            if not isinstance(cursore, dict):
                break
            cursore = cursore.get(chiave)
        if isinstance(cursore, dict) and path[-1] in cursore:
            cursore[path[-1]] = _REDACTED

    # Qualunque chiave che *sembri* un segreto, ovunque si trovi.
    def scava(nodo: Any) -> None:
        if not isinstance(nodo, dict):
            return
        for chiave, valore in nodo.items():
            if isinstance(valore, str) and _SECRET_KEY.search(chiave):
                nodo[chiave] = _REDACTED
            else:
                scava(valore)

    scava(payload)

    if envelope.type == MessageType.STREAM_DATA:
        dati = payload.get("data")
        if isinstance(dati, str) and len(dati) > _MAX_STREAM_CHARS:
            payload["data"] = ""
            payload["_omitted_chars"] = len(dati)

    return Envelope(
        v=envelope.version, id=envelope.id, t=envelope.type, ts=envelope.ts,
        p=payload, c=envelope.corr,
    )


@dataclass(frozen=True, slots=True)
class RecordedMessage:
    """Una busta con il momento e la direzione in cui è transitata."""

    offset: float
    """Secondi dall'inizio della registrazione."""

    direction: Direction
    envelope: Envelope

    def to_line(self) -> str:
        return json.dumps(
            {"t": round(self.offset, 4), "dir": self.direction, "env": self.envelope.to_wire()},
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @classmethod
    def from_line(cls, line: str) -> RecordedMessage:
        """:raises ProtocolError: se la riga non è un record valido."""
        try:
            data = json.loads(line)
            return cls(
                offset=float(data["t"]),
                direction=str(data["dir"]),
                envelope=Envelope.from_wire(data["env"]),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ProtocolError(f"Record JCPL non valido: {exc}") from exc


@dataclass
class Recording:
    """Una sessione registrata, in memoria."""

    messages: list[RecordedMessage] = field(default_factory=list)
    recorded_at: float = field(default_factory=time.time)
    client: str = "sconosciuto"
    backend: str = "sconosciuto"
    note: str = ""

    @property
    def duration(self) -> float:
        return self.messages[-1].offset if self.messages else 0.0

    def inbound(self) -> list[RecordedMessage]:
        """Solo i messaggi provenienti dal backend: quelli che il replay ripete."""
        return [m for m in self.messages if m.direction == "in"]

    def summary(self) -> dict[str, Any]:
        """Riepilogo per gli strumenti di ispezione."""
        conteggi: dict[str, int] = {}
        for messaggio in self.messages:
            conteggi[messaggio.envelope.type] = conteggi.get(messaggio.envelope.type, 0) + 1
        return {
            "messaggi": len(self.messages),
            "durata_s": round(self.duration, 2),
            "in": len(self.inbound()),
            "out": len(self.messages) - len(self.inbound()),
            "tipi": dict(sorted(conteggi.items(), key=lambda kv: -kv[1])),
            "client": self.client,
            "backend": self.backend,
            "note": self.note,
        }

    # -- persistenza ------------------------------------------------------- #

    def save(self, path: Path) -> None:
        """Scrive la registrazione in formato JCPL."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            handle.write(self._header_line() + "\n")
            for messaggio in self.messages:
                handle.write(messaggio.to_line() + "\n")

    def _header_line(self) -> str:
        return json.dumps(
            {
                "jcpl": JCPL_VERSION,
                "recorded_at": self.recorded_at,
                "client": self.client,
                "backend": self.backend,
                "note": self.note,
                "messages": len(self.messages),
                "duration": round(self.duration, 3),
            },
            ensure_ascii=False,
        )

    @classmethod
    def load(cls, path: Path) -> Recording:
        """Legge una registrazione JCPL.

        Le righe illeggibili vengono **saltate**, non fanno fallire il
        caricamento: una registrazione troncata — perché il processo è stato
        ucciso, che è proprio il caso interessante — deve restare utilizzabile
        fino al punto in cui arriva.

        :raises ProtocolError: se manca l'intestazione o la versione è ignota.
        """
        with path.open("r", encoding="utf-8") as handle:
            return cls.read(handle)

    @classmethod
    def read(cls, handle: TextIO) -> Recording:
        """Come :meth:`load`, da un flusso già aperto."""
        prima = handle.readline()
        if not prima.strip():
            raise ProtocolError("Registrazione vuota: manca l'intestazione")

        try:
            header = json.loads(prima)
        except json.JSONDecodeError as exc:
            raise ProtocolError(f"Intestazione JCPL non valida: {exc}") from exc

        versione = header.get("jcpl")
        if versione != JCPL_VERSION:
            raise ProtocolError(
                f"Formato JCPL versione {versione}: questa build legge la {JCPL_VERSION}"
            )

        recording = cls(
            recorded_at=float(header.get("recorded_at", time.time())),
            client=str(header.get("client", "sconosciuto")),
            backend=str(header.get("backend", "sconosciuto")),
            note=str(header.get("note", "")),
        )
        for riga in handle:
            if not riga.strip():
                continue
            try:
                recording.messages.append(RecordedMessage.from_line(riga))
            except ProtocolError:
                continue  # riga troncata o corrotta: si prosegue
        return recording

    def __iter__(self) -> Iterator[RecordedMessage]:
        return iter(self.messages)

    def __len__(self) -> int:
        return len(self.messages)


class SessionRecorder:
    """Registra le buste che attraversano il canale.

    Thread-safe: il servizio di rete registra dal proprio thread mentre
    l'interfaccia legge il riepilogo dal thread GUI.
    """

    def __init__(
        self,
        *,
        client: str = "jarvis-desktop",
        backend: str = "sconosciuto",
        redact: bool = True,
        limit: int = 20_000,
    ) -> None:
        """
        :param redact: rimuove segreti e blocchi audio. Disattivarlo ha senso
            solo per una registrazione che non lascerà la macchina.
        :param limit: tetto ai messaggi conservati. Uno stream audio ne produce
            sedici al secondo: senza limite, una sessione lunga esaurirebbe la
            memoria proprio mentre si cerca di diagnosticarla.
        """
        self._recording = Recording(client=client, backend=backend)
        self._redact = redact
        self._limit = limit
        self._started = 0.0
        self._active = False
        self._truncated = False
        self._lock = threading.Lock()

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._active

    @property
    def truncated(self) -> bool:
        """Vero se il tetto è stato raggiunto e alcuni messaggi sono stati persi."""
        with self._lock:
            return self._truncated

    def start(self, note: str = "") -> None:
        """Avvia una nuova registrazione, scartando la precedente."""
        with self._lock:
            self._recording = Recording(
                client=self._recording.client, backend=self._recording.backend, note=note
            )
            self._started = time.monotonic()
            self._active = True
            self._truncated = False

    def stop(self) -> Recording:
        """Ferma la registrazione e restituisce ciò che è stato raccolto."""
        with self._lock:
            self._active = False
            return self._recording

    def record(self, direction: Direction, envelope: Envelope) -> None:
        """Registra una busta. Non solleva mai."""
        with self._lock:
            if not self._active:
                return
            if len(self._recording.messages) >= self._limit:
                self._truncated = True
                return
            offset = time.monotonic() - self._started
            busta = redact_envelope(envelope) if self._redact else envelope
            self._recording.messages.append(RecordedMessage(offset, direction, busta))

    def set_backend(self, backend: str) -> None:
        """Annota il backend, noto solo dopo l'handshake."""
        with self._lock:
            self._recording.backend = backend

    @property
    def current(self) -> Recording:
        with self._lock:
            return self._recording


class SessionReplayer:
    """Riproduce una registrazione come se fosse un backend.

    Implementa il contratto del trasporto, quindi il resto dell'applicazione non
    distingue un replay da una connessione — che è il punto: si sta osservando
    l'interfaccia, non il canale.

    **Non reagisce.** I messaggi inviati dal client vengono contati e scartati.
    Se durante il replay si preme un pulsante che in origine non era stato
    premuto, non succede nulla: la sequenza registrata prosegue identica. È un
    limite intrinseco, non un difetto da correggere — per la reattività esiste
    la simulazione.
    """

    def __init__(
        self,
        recording: Recording,
        *,
        speed: float = 1.0,
        loop: bool = False,
        max_gap: float = 3.0,
    ) -> None:
        """
        :param speed: moltiplicatore del tempo. 0 riproduce senza attese.
        :param loop: ricomincia da capo alla fine.
        :param max_gap: attesa massima fra due messaggi. Una pausa di quaranta
            secondi nella registrazione originale non ha valore diagnostico e
            rende il replay inutilizzabile: la si comprime.
        """
        self._recording = recording
        self._speed = max(0.0, speed)
        self._loop = loop
        self._max_gap = max_gap
        self._connected = False
        self._sent_by_client = 0
        self._position = 0

    # -- contratto del trasporto ------------------------------------------ #

    @property
    def endpoint(self) -> str:
        return f"replay://{len(self._recording)} messaggi"

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        self._connected = True
        self._position = 0
        self._sent_by_client = 0

    async def close(self) -> None:
        self._connected = False

    async def send(self, message: dict[str, Any]) -> None:
        """Conta il messaggio e lo scarta: un replay non risponde."""
        self._sent_by_client += 1

    async def receive(self) -> AsyncIterator[dict[str, Any]]:
        """Riproduce i messaggi in ingresso rispettando la temporizzazione."""
        import asyncio

        while True:
            precedente = 0.0
            for messaggio in self._recording.inbound():
                if not self._connected:
                    return

                if self._speed > 0:
                    attesa = min((messaggio.offset - precedente) / self._speed, self._max_gap)
                    if attesa > 0:
                        await asyncio.sleep(attesa)
                precedente = messaggio.offset

                self._position += 1
                yield messaggio.envelope.to_wire()

            if not self._loop:
                return

    # -- introspezione ----------------------------------------------------- #

    @property
    def progress(self) -> float:
        """Frazione riprodotta, fra 0 e 1."""
        totale = len(self._recording.inbound())
        return self._position / totale if totale else 1.0

    @property
    def client_messages_ignored(self) -> int:
        """Messaggi inviati dal client e scartati.

        Un valore alto durante un replay è atteso e va mostrato, non nascosto:
        ricorda a chi guarda che l'interfaccia sta parlando a un registratore.
        """
        return self._sent_by_client
