"""Identity Service: chi e' questa installazione, e chi e' il backend.

Due identita' distinte, spesso confuse:

* **identita' locale** — questa installazione della GUI: un ``instance_id``
  stabile fra i riavvii, il nome della macchina, la piattaforma, la versione.
  Serve a OpenClaw per riconoscere il client fra una sessione e l'altra;
* **identita' remota** — chi risponde: nome dell'assistente, versione del
  backend, modello attivo, persona, colore d'accento.

La regola che governa questo modulo: **la GUI e' il volto visivo di Jarvis e
non inventa nulla**. Il nome "J.A.R.V.I.S." mostrato in HUD e' un valore di
ripiego usato finche' il backend non ha parlato; appena arriva ``server.hello``
viene sostituito da quanto dichiarato. Alla disconnessione l'identita' remota
viene **azzerata** (:meth:`IdentityService.forget_remote`): continuare a
mostrare "modello X" mentre il canale e' caduto significherebbe affermare
qualcosa che non e' piu' verificato.
"""

from __future__ import annotations

import json
import platform
import socket
import threading
import uuid
from dataclasses import replace

from core.eventbus import EventBus
from core.events import BackendIdentity, EventType
from core.jcp.capabilities import CLIENT_CAPABILITIES
from core.jcp.messages import ClientInfo, ProtocolField, SessionHelloPayload, SessionWelcomePayload
from core.jcp.version import PROTOCOL_VERSION
from core.logging_setup import LogCategory, get_logger
from core.paths import AppPaths, app_paths

__all__ = ["ClientIdentity", "IdentityService"]

_log = get_logger(LogCategory.APP, "identity")

#: Versione della GUI dichiarata nell'handshake.
CLIENT_VERSION = "0.3.0"

#: Identita' mostrata prima che il backend si sia presentato. Non e' una
#: pretesa: e' un segnaposto, e l'HUD lo mostra come "non confermato".
_PLACEHOLDER = BackendIdentity(
    assistant_name="J.A.R.V.I.S.",
    backend_name="OpenClaw",
    backend_version=None,
    model=None,
)


class ClientIdentity:
    """Identita' persistente di questa installazione.

    L'``instance_id`` sopravvive ai riavvii perche' e' salvato su disco. Se il
    file non e' scrivibile si genera un id volatile: l'applicazione parte
    comunque, perdendo solo la continuita' fra sessioni.
    """

    __slots__ = ("device_name", "instance_id", "persistent", "platform_name", "version")

    def __init__(self, paths: AppPaths | None = None) -> None:
        resolved = paths or app_paths()
        self.device_name = self._device_name()
        self.platform_name = f"{platform.system()} {platform.release()}".strip()
        self.version = CLIENT_VERSION
        self.instance_id, self.persistent = self._load_or_create(resolved)

    @staticmethod
    def _device_name() -> str:
        try:
            return socket.gethostname() or "sconosciuto"
        except OSError:  # pragma: no cover - dipende dalla rete locale
            return "sconosciuto"

    @staticmethod
    def _load_or_create(paths: AppPaths) -> tuple[str, bool]:
        """Legge l'id salvato, altrimenti ne crea uno e prova a persisterlo."""
        path = paths.identity_file
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            stored = data.get("instance_id")
            if isinstance(stored, str) and stored:
                return stored, True
        except FileNotFoundError:
            pass
        except (json.JSONDecodeError, OSError) as exc:
            _log.warning("Identita' locale illeggibile (%s): se ne genera una nuova", exc)

        generated = uuid.uuid4().hex
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"instance_id": generated}, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            _log.warning("Identita' locale non persistita (%s): id volatile", exc)
            return generated, False
        return generated, True

    def to_hello(self, auth: dict[str, str] | None = None) -> SessionHelloPayload:
        """Costruisce il messaggio ``session.hello``."""
        return SessionHelloPayload(
            protocol=ProtocolField(
                major=PROTOCOL_VERSION.major, minor=PROTOCOL_VERSION.minor
            ),
            client=ClientInfo(
                version=self.version,
                instance_id=self.instance_id,
                device=self.device_name,
                platform=self.platform_name,
            ),
            capabilities=sorted(CLIENT_CAPABILITIES),
            auth=auth or {"scheme": "none"},  # type: ignore[arg-type]
        )

    def __repr__(self) -> str:  # pragma: no cover - diagnostica
        return (
            f"<ClientIdentity device={self.device_name!r} "
            f"instance={self.instance_id[:8]}… persistent={self.persistent}>"
        )


class IdentityService:
    """Custodisce l'identita' locale e quella dichiarata dal backend."""

    def __init__(self, bus: EventBus, paths: AppPaths | None = None) -> None:
        self._bus = bus
        self._lock = threading.RLock()
        self._client = ClientIdentity(paths)
        self._backend: BackendIdentity = _PLACEHOLDER
        self._confirmed = False
        self._session_id: str | None = None
        _log.info(
            "Identita' locale: %s su %s (id %s…)",
            self._client.device_name,
            self._client.platform_name,
            self._client.instance_id[:8],
        )

    # ------------------------------------------------------------------ #
    # Identita' locale
    # ------------------------------------------------------------------ #

    @property
    def client(self) -> ClientIdentity:
        """Identita' di questa installazione."""
        return self._client

    def hello_payload(self, auth: dict[str, str] | None = None) -> SessionHelloPayload:
        """Payload di ``session.hello`` da inviare all'apertura del canale."""
        return self._client.to_hello(auth)

    # ------------------------------------------------------------------ #
    # Identita' remota
    # ------------------------------------------------------------------ #

    @property
    def backend(self) -> BackendIdentity:
        """Identita' del backend. Prima dell'handshake e' il segnaposto."""
        with self._lock:
            return self._backend

    @property
    def is_confirmed(self) -> bool:
        """Vero solo dopo un handshake riuscito.

        L'HUD deve distinguere "J.A.R.V.I.S." confermato dal segnaposto: sono
        due affermazioni diverse, e mostrarle uguali sarebbe una bugia.
        """
        with self._lock:
            return self._confirmed

    @property
    def session_id(self) -> str | None:
        """Identificativo di sessione assegnato dal backend, se fornito."""
        with self._lock:
            return self._session_id

    @property
    def display_name(self) -> str:
        """Nome da mostrare in HUD."""
        with self._lock:
            return self._backend.assistant_name

    def apply_welcome(self, payload: SessionWelcomePayload) -> BackendIdentity:
        """Registra l'identita' dichiarata in ``session.welcome`` e la pubblica.

        :returns: l'identita' risultante.
        """
        server = payload.server
        identity = BackendIdentity(
            assistant_name=server.assistant_name or _PLACEHOLDER.assistant_name,
            backend_name=server.name or _PLACEHOLDER.backend_name,
            backend_version=server.version,
            model=server.model,
            persona=server.persona,
            accent_color=server.accent_color,
            instance_id=server.instance_id,
        )

        with self._lock:
            self._backend = identity
            self._confirmed = True
            self._session_id = payload.session_id

        _log.info(
            "Backend confermato: %s %s (modello %s)",
            identity.backend_name,
            identity.backend_version or "versione ignota",
            identity.model or "non dichiarato",
        )
        self._bus.publish(EventType.IDENTITY_UPDATED, identity, source="identity")
        return identity

    def forget_remote(self) -> None:
        """Azzera l'identita' remota alla caduta del canale.

        Deliberato: senza connessione la GUI non sa piu' quale modello sia
        attivo, e non deve continuare ad affermarlo. Il nome dell'assistente
        resta come segnaposto perche' e' l'identita' del prodotto, non un dato
        di sessione.
        """
        with self._lock:
            if not self._confirmed and self._backend == _PLACEHOLDER:
                return
            name = self._backend.assistant_name
            self._backend = replace(_PLACEHOLDER, assistant_name=name)
            self._confirmed = False
            self._session_id = None
            identity = self._backend

        _log.info("Identita' del backend azzerata: canale non disponibile")
        self._bus.publish(EventType.IDENTITY_UPDATED, identity, source="identity")
