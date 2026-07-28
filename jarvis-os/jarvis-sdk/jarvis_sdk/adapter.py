"""Base per scrivere un adapter di backend.

Un adapter traduce fra il dialetto di un backend e JCP. Scriverne uno da zero
significa riscrivere ogni volta le stesse quattro cose: due tabelle di
corrispondenza dei tipi, la tolleranza ai messaggi sconosciuti, la gestione
dello stato di traduzione e il riepilogo per la diagnostica.

:class:`BaseAdapter` le fornisce. Chi lo estende dichiara le tabelle e scrive
solo le traduzioni di payload che una tabella non sa esprimere — che nella
pratica sono poche.

**Ciò che un adapter non deve fare**, ed è la parte che conta: non decide, non
conserva stato di dominio, non tocca il bus dell'applicazione. Può avere stato
*tecnico* — una mappa di identificativi, un contatore di sequenza. La
distinzione è fra stato di traduzione e stato di dominio, e il momento in cui
si confonde è il momento in cui la sostituibilità del backend è persa.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from jarvis_protocol.envelope import Envelope

__all__ = ["BaseAdapter"]

_log = logging.getLogger("jarvis_sdk.adapter")


class BaseAdapter(ABC):
    """Scheletro di un adapter guidato da tabelle.

    Uso minimo::

        class MioAdapter(BaseAdapter):
            name = "mio-backend"
            TO_BACKEND = {MessageType.CHAT_SEND: "invia"}
            FROM_BACKEND = {"risposta": MessageType.CHAT_DELTA}

            def translate_outgoing(self, envelope):
                if envelope.type == MessageType.CHAT_SEND:
                    return {"testo": envelope.payload["text"]}
                return dict(envelope.payload)

            def translate_incoming(self, jcp_type, data):
                if jcp_type == MessageType.CHAT_DELTA:
                    return {"text": data["frammento"], "message_id": data["id"]}
                return dict(data)
    """

    #: Nome del backend supportato. Compare nella diagnostica.
    name: ClassVar[str] = "adapter"

    #: JCP → dialetto. I tipi assenti non hanno corrispondenza e non si inviano.
    TO_BACKEND: ClassVar[dict[str, str]] = {}

    #: Dialetto → JCP. I tipi assenti si ignorano.
    FROM_BACKEND: ClassVar[dict[str, str]] = {}

    #: Chiave con cui il backend correla richiesta e risposta, se ne usa una.
    CORRELATION_KEY: ClassVar[str | None] = None

    # ------------------------------------------------------------------ #
    # Da implementare
    # ------------------------------------------------------------------ #

    @abstractmethod
    def translate_outgoing(self, envelope: Envelope) -> dict[str, Any]:
        """Converte il payload JCP nella forma attesa dal backend."""

    @abstractmethod
    def translate_incoming(self, jcp_type: str, data: dict[str, Any]) -> dict[str, Any] | None:
        """Converte il payload del backend nella forma prevista da JCP.

        :returns: ``None`` per scartare il messaggio. Va usato quando il
            contenuto non è traducibile — uno stato sconosciuto, per esempio.
            Restituire un payload inventato sarebbe peggio: la GUI mostrerebbe
            con sicurezza qualcosa che nessuno ha dichiarato.
        """

    # ------------------------------------------------------------------ #
    # Contratto dell'adapter
    # ------------------------------------------------------------------ #

    def to_backend(self, envelope: Envelope) -> list[dict[str, Any]]:
        """Traduce una busta JCP in zero o più messaggi del backend."""
        backend_type = self.TO_BACKEND.get(envelope.type)
        if backend_type is None:
            _log.debug("[%s] nessuna corrispondenza in uscita per '%s'", self.name, envelope.type)
            return []

        try:
            data = self.translate_outgoing(envelope)
        except Exception:
            _log.exception("[%s] traduzione in uscita fallita per '%s'", self.name, envelope.type)
            return []

        messaggio: dict[str, Any] = {"type": backend_type, "data": data}
        if self.CORRELATION_KEY:
            messaggio[self.CORRELATION_KEY] = envelope.id
        return [messaggio]

    def from_backend(self, raw: dict[str, Any]) -> list[Envelope]:
        """Traduce un messaggio del backend in zero o più buste JCP.

        La cardinalità **non è uno a uno**: un backend che invia blocchi audio
        senza aprire lo stream ne richiede due per il primo blocco. Le
        sottoclassi che hanno questo caso sovrascrivono il metodo e chiamano
        :meth:`envelope` più volte.
        """
        backend_type = raw.get("type")
        if not isinstance(backend_type, str):
            _log.warning("[%s] messaggio senza tipo: scartato", self.name)
            return []

        jcp_type = self.FROM_BACKEND.get(backend_type)
        if jcp_type is None:
            _log.debug("[%s] nessuna corrispondenza in ingresso per '%s'", self.name, backend_type)
            return []

        data = raw.get("data")
        data = data if isinstance(data, dict) else {}

        try:
            payload = self.translate_incoming(jcp_type, data)
        except Exception:
            _log.exception("[%s] traduzione in ingresso fallita per '%s'", self.name, backend_type)
            return []

        if payload is None:
            return []
        return [self.envelope(jcp_type, payload, corr=self._correlation(raw))]

    def _correlation(self, raw: dict[str, Any]) -> str | None:
        if not self.CORRELATION_KEY:
            return None
        valore = raw.get(self.CORRELATION_KEY)
        return valore if isinstance(valore, str) else None

    @staticmethod
    def envelope(
        type_: str, payload: dict[str, Any], *, corr: str | None = None
    ) -> Envelope:
        """Costruisce una busta JCP. Comodità per le sottoclassi."""
        return Envelope.make(type_, payload, corr=corr)

    # ------------------------------------------------------------------ #
    # Ciclo di vita e diagnostica
    # ------------------------------------------------------------------ #

    def reset(self) -> None:  # noqa: B027 - volutamente non astratto
        """Azzera lo stato di traduzione alla caduta della sessione.

        Le sottoclassi con stato tecnico — stream aperti, contatori — devono
        sovrascriverla. Non farlo produce difetti che si manifestano solo alla
        **seconda** connessione, che sono fra i più fastidiosi da trovare.
        """

    def describe(self) -> dict[str, Any]:
        """Informazioni per gli strumenti di ispezione."""
        return {
            "name": self.name,
            "translates": True,
            "message_types_out": len(self.TO_BACKEND),
            "message_types_in": len(self.FROM_BACKEND),
        }

    def coverage(self, required: set[str]) -> set[str]:
        """Tipi JCP richiesti che questo adapter **non** sa tradurre.

        Serve alla verifica di conformità: un adapter che non mappa
        ``session.hello`` non potrà mai completare un handshake, e vale la pena
        scoprirlo prima di collegarlo a un backend reale.
        """
        return required - set(self.TO_BACKEND) - set(self.FROM_BACKEND.values())
