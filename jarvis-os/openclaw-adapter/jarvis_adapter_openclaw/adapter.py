"""Adapter per OpenClaw.

.. warning::

   **Il dialetto qui assunto è provvisorio.** Il protocollo reale di OpenClaw
   non mi è stato ancora comunicato: questo adapter codifica un dialetto
   plausibile, tratto dalle convenzioni comuni ai backend conversazionali —
   busta piatta ``{type, data, request_id}``, vocabolario di stato diverso da
   JCP, audio con messaggi propri invece di stream generici.

   Quando il protocollo reale sarà noto, **si modifica solo questo file**. È
   esattamente la ragione per cui l'adapter layer esiste: il resto
   dell'applicazione parla JCP e non si accorgerà della differenza.

   Le tre tabelle in cima al modulo (tipi, stati, capability) coprono la
   maggior parte dell'adattamento; il codice sotto gestisce i due punti dove
   una tabella non basta.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from jarvis_protocol.capabilities import Capability
from jarvis_protocol.envelope import Envelope
from jarvis_protocol.messages import MessageType
from jarvis_protocol.missions import MissionType
from jarvis_protocol.version import PROTOCOL_VERSION

__all__ = ["OpenClawAdapter"]

_log = logging.getLogger("jarvis_adapter_openclaw")

#: JCP → OpenClaw. I tipi assenti non hanno corrispondenza e non vengono inviati.
_TO_BACKEND: Final[dict[str, str]] = {
    MessageType.SESSION_HELLO: "connect",
    MessageType.CHAT_SEND: "message",
    MessageType.CHAT_CANCEL: "interrupt",
    MessageType.VOICE_START: "listen_start",
    MessageType.VOICE_STOP: "listen_stop",
    MessageType.PING: "ping",
    MessageType.SESSION_CLOSE: "disconnect",
    MissionType.ACTION_CONFIRM_REPLY: "approval_reply",
    MissionType.ACTION_CANCEL: "tool_abort",
    MissionType.MISSION_CANCEL: "mission_abort",
}

#: OpenClaw → JCP.
_FROM_BACKEND: Final[dict[str, str]] = {
    "connected": MessageType.SESSION_WELCOME,
    "rejected": MessageType.SESSION_DENIED,
    "status": MessageType.AGENT_STATE,
    "token": MessageType.CHAT_DELTA,
    "message_end": MessageType.CHAT_DONE,
    "task": MessageType.TASK_UPDATE,
    "mission_start": MissionType.MISSION_STARTED,
    "mission_end": MissionType.MISSION_FINISHED,
    "tool_call": MissionType.ACTION_QUEUED,
    "tool_result": MissionType.ACTION_FINISHED,
    "approval_request": MissionType.ACTION_CONFIRM_REQUEST,
    "tools": MissionType.TOOL_REGISTRY,
    "error": MessageType.ERROR,
    "pong": MessageType.PONG,
}

#: Vocabolario degli stati. OpenClaw distingue "processing" da "tool_use"; JCP
#: li chiama "thinking" ed "executing". Tradurre qui evita che il vocabolario di
#: un backend specifico si propaghi nelle animazioni del nucleo.
_STATES: Final[dict[str, str]] = {
    "idle": "idle",
    "ready": "idle",
    "listening": "listening",
    "processing": "thinking",
    "thinking": "thinking",
    "tool_use": "executing",
    "executing": "executing",
    "responding": "speaking",
    "speaking": "speaking",
}

#: Esiti delle missioni nel dialetto OpenClaw.
_MISSION_STATUS: Final[dict[str, str]] = {
    "success": "completed",
    "done": "completed",
    "error": "failed",
    "aborted": "cancelled",
}

#: Esiti delle azioni.
_ACTION_STATUS: Final[dict[str, str]] = {
    "success": "ok",
    "error": "error",
    "aborted": "cancelled",
    "rejected": "denied",
}

#: OpenClaw chiama "features" ciò che JCP chiama capability, con nomi propri.
_CAPABILITIES: Final[dict[str, str]] = {
    "streaming": Capability.CHAT_STREAM.value,
    "interrupt": Capability.CHAT_CANCEL.value,
    "voice": Capability.TTS_STREAM.value,
    "transcription": Capability.STT_STREAM.value,
    "vision": Capability.VISION_INGEST.value,
    "tools": Capability.TASKS.value,
    "missions": Capability.MISSIONS.value,
    "tool_calls": Capability.ACTIONS.value,
    "abort": Capability.ACTIONS_CANCEL.value,
    "approvals": Capability.ACTIONS_CONFIRM.value,
    "tool_registry": Capability.TOOLS_REGISTRY.value,
}


class OpenClawAdapter:
    """Traduce fra JCP e il dialetto di OpenClaw.

    Mantiene un piccolo stato **tecnico**: gli stream audio aperti. OpenClaw
    invia i blocchi vocali senza un messaggio di apertura esplicito, mentre JCP
    lo richiede; l'adapter sintetizza ``stream.open`` al primo blocco. È stato
    di traduzione, non di dominio: nessuna decisione dipende da esso.
    """

    def __init__(self) -> None:
        self._open_streams: set[str] = set()

    @property
    def name(self) -> str:
        return "openclaw"

    # ------------------------------------------------------------------ #
    # JCP → OpenClaw
    # ------------------------------------------------------------------ #

    def to_backend(self, envelope: Envelope) -> list[dict[str, Any]]:
        backend_type = _TO_BACKEND.get(envelope.type)
        if backend_type is None:
            _log.debug("Nessuna corrispondenza in uscita per '%s'", envelope.type)
            return []

        # OpenClaw correla con 'request_id' invece che con un campo dedicato.
        message: dict[str, Any] = {
            "type": backend_type,
            "data": self._translate_outgoing(envelope),
            "request_id": envelope.id,
        }
        if envelope.corr:
            message["reply_to"] = envelope.corr
        return [message]

    def _translate_outgoing(self, envelope: Envelope) -> dict[str, Any]:
        """Rimappa il payload sui nomi attesi da OpenClaw."""
        p = envelope.payload

        if envelope.type == MessageType.SESSION_HELLO:
            client = p.get("client", {})
            auth = p.get("auth", {})
            return {
                "client": client.get("name"),
                "client_version": client.get("version"),
                "instance": client.get("instance_id"),
                "locale": client.get("locale"),
                # OpenClaw dichiara le proprie funzioni come "features": si
                # traduce anche in uscita, altrimenti la negoziazione sarebbe
                # asimmetrica e il backend ignorerebbe ciò che la GUI offre.
                "features": sorted(
                    {
                        backend
                        for backend, jcp in _CAPABILITIES.items()
                        if jcp in set(p.get("capabilities", ()))
                    }
                ),
                "token": auth.get("token"),
            }

        if envelope.type == MessageType.CHAT_SEND:
            return {"content": p.get("text", ""), "id": p.get("message_id")}

        if envelope.type == MessageType.CHAT_CANCEL:
            return {"id": p.get("message_id")}

        if envelope.type == MissionType.ACTION_CONFIRM_REPLY:
            return {
                "id": p.get("request_id"),
                "approved": bool(p.get("approved")),
                "choice": p.get("option"),
                "always": bool(p.get("remember")),
            }

        if envelope.type == MissionType.ACTION_CANCEL:
            return {"id": p.get("action_id")}

        if envelope.type == MissionType.MISSION_CANCEL:
            return {"id": p.get("mission_id")}

        return dict(p)

    # ------------------------------------------------------------------ #
    # OpenClaw → JCP
    # ------------------------------------------------------------------ #

    def from_backend(self, raw: dict[str, Any]) -> list[Envelope]:
        backend_type = raw.get("type")
        if not isinstance(backend_type, str):
            _log.warning("Messaggio senza tipo: scartato")
            return []

        data = raw.get("data")
        data = data if isinstance(data, dict) else {}
        corr_raw = raw.get("reply_to") or raw.get("request_id")
        corr = corr_raw if isinstance(corr_raw, str) else None

        # I blocchi vocali non hanno corrispondenza uno-a-uno: OpenClaw non apre
        # esplicitamente lo stream, JCP sì.
        if backend_type in ("speech", "speech_end"):
            return self._translate_speech(backend_type, data, corr)

        # OpenClaw invia un solo messaggio per l'invocazione di uno strumento;
        # JCP distingue accodamento e avvio, perche' senza quella distinzione la
        # coda dell'interfaccia mostrerebbe tutto come "in esecuzione".
        if backend_type == "tool_call":
            payload = self._translate_incoming(MissionType.ACTION_QUEUED, data)
            if payload is None:
                return []
            return [
                Envelope.make(MissionType.ACTION_QUEUED, payload, corr=corr),
                Envelope.make(
                    MissionType.ACTION_STARTED, {"action_id": payload["action_id"]}
                ),
            ]

        jcp_type = _FROM_BACKEND.get(backend_type)
        if jcp_type is None:
            _log.debug("Nessuna corrispondenza in ingresso per '%s'", backend_type)
            return []

        payload = self._translate_incoming(jcp_type, data)
        if payload is None:
            return []
        return [Envelope.make(jcp_type, payload, corr=corr)]

    def _translate_incoming(self, jcp_type: str, data: dict[str, Any]) -> dict[str, Any] | None:
        """Rimappa il payload sui nomi previsti da JCP."""
        if jcp_type == MessageType.SESSION_WELCOME:
            features = [f for f in data.get("features", []) if isinstance(f, str)]
            return {
                "protocol": {"major": PROTOCOL_VERSION.major, "minor": PROTOCOL_VERSION.minor},
                "server": {
                    "name": "OpenClaw",
                    "version": data.get("version"),
                    "assistant_name": data.get("agent") or "J.A.R.V.I.S.",
                    "model": data.get("model"),
                    "persona": data.get("persona"),
                    "instance_id": data.get("instance"),
                },
                "capabilities": sorted(
                    {_CAPABILITIES[f] for f in features if f in _CAPABILITIES}
                    | {Capability.IDENTITY.value}
                ),
                "session_id": data.get("session"),
            }

        if jcp_type == MessageType.SESSION_DENIED:
            return {
                "code": data.get("code", "auth.denied"),
                "message": data.get("reason", "Connessione rifiutata"),
                "retryable": bool(data.get("retryable", False)),
            }

        if jcp_type == MessageType.AGENT_STATE:
            backend_state = str(data.get("value", ""))
            state = _STATES.get(backend_state)
            if state is None:
                # Uno stato sconosciuto non va indovinato: si scarta il
                # messaggio e la GUI resta su quello precedente, che è
                # l'ultima cosa realmente confermata.
                _log.warning("Stato OpenClaw sconosciuto: '%s'", backend_state)
                return None
            return {"state": state, "reason": data.get("reason")}

        if jcp_type == MessageType.CHAT_DELTA:
            return {"text": data.get("content", ""), "message_id": str(data.get("id", ""))}

        if jcp_type == MessageType.CHAT_DONE:
            return {"message_id": str(data.get("id", "")), "reason": data.get("reason")}

        if jcp_type == MessageType.TASK_UPDATE:
            return {
                "task_id": str(data.get("id", "")),
                "label": data.get("name", "Operazione"),
                "status": data.get("state", "running"),
                "progress": data.get("progress"),
            }

        if jcp_type == MissionType.MISSION_STARTED:
            return {
                "mission_id": str(data.get("id", "")),
                "title": data.get("goal") or data.get("title") or "Operazione",
                "goal": data.get("goal"),
                "parent_id": data.get("parent"),
                "related_message_id": data.get("message_id"),
            }

        if jcp_type == MissionType.MISSION_FINISHED:
            return {
                "mission_id": str(data.get("id", "")),
                "status": _MISSION_STATUS.get(str(data.get("outcome", "")), "completed"),
                "summary": data.get("summary"),
                "error": data.get("error"),
            }

        if jcp_type == MissionType.ACTION_QUEUED:
            # OpenClaw non distingue accodamento e avvio: il chiamante riceve
            # entrambi (vedi from_backend), perche' JCP separa i due momenti e
            # la coda dell'interfaccia perderebbe senso senza la distinzione.
            return {
                "action_id": str(data.get("id", "")),
                "tool": str(data.get("tool", "sconosciuto")),
                "title": data.get("label") or str(data.get("tool", "Azione")),
                "mission_id": data.get("mission"),
                "args_preview": data.get("args_preview"),
                "risk": str(data.get("risk", "low")),
            }

        if jcp_type == MissionType.ACTION_FINISHED:
            return {
                "action_id": str(data.get("id", "")),
                "status": _ACTION_STATUS.get(str(data.get("outcome", "")), "ok"),
                "result_preview": data.get("preview"),
                "error": data.get("error"),
                "duration_ms": data.get("elapsed_ms"),
            }

        if jcp_type == MissionType.ACTION_CONFIRM_REQUEST:
            return {
                "request_id": str(data.get("id", "")),
                "action_id": str(data.get("tool_call", data.get("id", ""))),
                "title": data.get("label") or "Conferma richiesta",
                "detail": data.get("detail"),
                "risk": str(data.get("risk", "medium")),
                "expires_in_s": data.get("timeout_s"),
            }

        if jcp_type == MissionType.TOOL_REGISTRY:
            catalogo = data.get("available")
            if not isinstance(catalogo, list):
                return None
            return {
                "tools": [
                    {
                        "name": str(t.get("name", "")),
                        "title": t.get("label"),
                        "description": t.get("doc"),
                        "category": t.get("group"),
                        "risk": str(t.get("risk", "low")),
                    }
                    for t in catalogo
                    if isinstance(t, dict) and t.get("name")
                ]
            }

        if jcp_type == MessageType.ERROR:
            return {
                "code": data.get("kind", "internal"),
                "message": data.get("reason", "Errore del backend"),
                "severity": data.get("level", "error"),
                "detail": data.get("detail"),
            }

        return dict(data)

    def _translate_speech(
        self, backend_type: str, data: dict[str, Any], corr: str | None
    ) -> list[Envelope]:
        """Converte i messaggi vocali di OpenClaw in stream JCP.

        Il primo blocco produce **due** buste: l'apertura sintetizzata e il
        blocco stesso. Emettere solo l'apertura perderebbe il primo frammento
        di audio — un difetto che all'ascolto si nota appena, e per questo è
        tanto più insidioso.
        """
        stream_id = str(data.get("id", "")) or "speech"

        if backend_type == "speech_end":
            self._open_streams.discard(stream_id)
            return [Envelope.make(MessageType.STREAM_CLOSE, {"stream_id": stream_id})]

        produced: list[Envelope] = []
        if stream_id not in self._open_streams:
            self._open_streams.add(stream_id)
            produced.append(
                Envelope.make(
                    MessageType.STREAM_OPEN,
                    {
                        "stream_id": stream_id,
                        "kind": "audio",
                        "encoding": data.get("format", "pcm_s16le"),
                        "sample_rate": data.get("rate", 24000),
                        "channels": data.get("channels", 1),
                        "related_id": data.get("message_id"),
                    },
                )
            )

        produced.append(
            Envelope.make(
                MessageType.STREAM_DATA,
                {
                    "stream_id": stream_id,
                    "seq": int(data.get("seq", 0)),
                    "data": data.get("audio", ""),
                },
                corr=corr,
            )
        )
        return produced

    def reset(self) -> None:
        """Azzera lo stato di traduzione. Chiamata alla caduta della sessione."""
        self._open_streams.clear()

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "translates": True,
            "note": (
                "Dialetto provvisorio: da allineare al protocollo reale di "
                "OpenClaw quando sarà noto."
            ),
            "message_types_out": len(_TO_BACKEND),
            "message_types_in": len(_FROM_BACKEND) + 2,  # più speech e speech_end
            "open_streams": len(self._open_streams),
        }
