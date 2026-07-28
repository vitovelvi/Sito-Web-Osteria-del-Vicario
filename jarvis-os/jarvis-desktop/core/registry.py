"""Service Registry: catalogo dei sottosistemi e iniezione delle dipendenze.

Fa due lavori che nella pratica sono lo stesso lavoro:

* **catalogo** — chi esiste, in che ordine si avvia, com'e' messo in salute;
* **composizione** — chi dipende da chi, e come si costruisce.

Perche' non usare semplicemente dei singleton globali? Perche' un singleton e'
una dipendenza nascosta: una classe che chiama ``EventBus.instance()`` non
dichiara di dipendere dal bus, non e' testabile in isolamento e non e'
sostituibile. E' il punto in cui SOLID si rompe per primo in un progetto Python
di questa dimensione. Qui le dipendenze si passano al costruttore, e il registry
sa come procurarle.

L'ordine di avvio e' calcolato per **ordinamento topologico** delle dipendenze
dichiarate, non fissato a mano: aggiungere un servizio non richiede di rileggere
la sequenza di boot.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, TypeVar

from core.errors import ServiceError
from core.eventbus import EventBus
from core.events import EventType
from core.events import ServiceStatus as ServiceStatusPayload
from core.logging_setup import LogCategory, get_logger
from core.service import Health, IService, ServiceState

__all__ = ["ServiceDescriptor", "ServiceRegistry"]

_log = get_logger(LogCategory.APP, "registry")

T = TypeVar("T")

#: Una factory riceve il registry per risolvere le proprie dipendenze.
Factory = Callable[["ServiceRegistry"], Any]


@dataclass(slots=True)
class ServiceDescriptor:
    """Come costruire un componente e cosa serve prima di lui."""

    key: type[Any]
    factory: Factory
    name: str
    depends_on: tuple[type[Any], ...] = ()
    critical: bool = False
    """Se ``True``, il fallimento interrompe l'avvio. Da riservare al minimo
    indispensabile: bus, configurazione, stato. Un'interfaccia che non parte
    perche' manca la webcam e' un'interfaccia progettata male."""

    lazy: bool = True
    """Se ``True`` l'istanza si crea alla prima richiesta, non all'avvio."""

    instance: Any | None = field(default=None, repr=False)


class ServiceRegistry:
    """Contenitore di componenti con ciclo di vita e dipendenze dichiarate."""

    def __init__(self, bus: EventBus | None = None) -> None:
        """
        :param bus: se fornito, ogni cambio di stato dei servizi viene pubblicato
            come :data:`~core.events.EventType.SERVICE_STATUS_CHANGED`, cosi'
            l'HUD riflette la realta' senza interrogare nessuno.
        """
        self._bus = bus
        self._descriptors: dict[type[Any], ServiceDescriptor] = {}
        self._lock = threading.RLock()
        self._resolving: list[type[Any]] = []
        self._started: list[type[Any]] = []
        self._restarts: dict[str, int] = {}

    # ------------------------------------------------------------------ #
    # Registrazione
    # ------------------------------------------------------------------ #

    def register(
        self,
        key: type[T],
        factory: Callable[[ServiceRegistry], T],
        *,
        name: str | None = None,
        depends_on: Iterable[type[Any]] = (),
        critical: bool = False,
        lazy: bool = True,
    ) -> None:
        """Registra un componente costruibile.

        :param key: tipo usato come chiave di risoluzione. Se e' un'interfaccia
            (``Protocol`` o ABC), l'implementazione concreta resta sostituibile —
            e' cosi' che ``MockBackend`` prende il posto del trasporto reale nei
            test senza che nessun chiamante se ne accorga.
        :param depends_on: chiavi che devono essere avviate prima.
        :param critical: se il suo fallimento debba impedire l'avvio.
        :param lazy: se costruirlo solo alla prima richiesta.
        """
        with self._lock:
            if key in self._descriptors:
                raise ServiceError(f"Componente gia' registrato per {key.__name__}")
            self._descriptors[key] = ServiceDescriptor(
                key=key,
                factory=factory,  # type: ignore[arg-type]
                name=name or key.__name__,
                depends_on=tuple(depends_on),
                critical=critical,
                lazy=lazy,
            )
        _log.debug("Registrato '%s'", name or key.__name__)

    def register_instance(self, key: type[T], instance: T, *, name: str | None = None) -> None:
        """Registra un oggetto gia' costruito (bus, config, state manager)."""
        with self._lock:
            self._descriptors[key] = ServiceDescriptor(
                key=key,
                factory=lambda _: instance,
                name=name or key.__name__,
                instance=instance,
                lazy=False,
            )

    # ------------------------------------------------------------------ #
    # Risoluzione
    # ------------------------------------------------------------------ #

    def resolve(self, key: type[T]) -> T:
        """Restituisce l'istanza registrata per ``key``, costruendola se serve.

        :raises ServiceError: se la chiave non e' registrata o se le dipendenze
            formano un ciclo.
        """
        with self._lock:
            descriptor = self._descriptors.get(key)
            if descriptor is None:
                raise ServiceError(
                    f"Nessun componente registrato per {key.__name__}. "
                    "Registrarlo nel bootstrap prima dell'uso."
                )
            if descriptor.instance is not None:
                return descriptor.instance  # type: ignore[return-value]

            # Il ciclo va intercettato qui: senza questo controllo si ottiene
            # una ricorsione infinita e uno stack trace illeggibile.
            if key in self._resolving:
                chain = " → ".join(k.__name__ for k in [*self._resolving, key])
                raise ServiceError(f"Dipendenza circolare: {chain}")

            self._resolving.append(key)
            try:
                instance = descriptor.factory(self)
                descriptor.instance = instance
            finally:
                self._resolving.pop()

        _log.debug("Costruito '%s'", descriptor.name)
        return instance  # type: ignore[return-value]

    def try_resolve(self, key: type[T]) -> T | None:
        """Come :meth:`resolve`, ma restituisce ``None`` invece di sollevare.

        Utile per le dipendenze opzionali: un pannello che sa funzionare anche
        senza il servizio di visione non deve far fallire l'avvio.
        """
        try:
            return self.resolve(key)
        except ServiceError:
            return None

    def has(self, key: type[Any]) -> bool:
        """Indica se una chiave e' registrata."""
        with self._lock:
            return key in self._descriptors

    # ------------------------------------------------------------------ #
    # Ordine di avvio
    # ------------------------------------------------------------------ #

    @staticmethod
    def _display_name(descriptor: ServiceDescriptor) -> str:
        """Nome con cui il servizio si presenta.

        Un servizio ha **una** identita': se l'istanza espone un ``name``, e'
        quello che compare in HUD, nei log e nel conteggio dei riavvii. Il nome
        del descrittore (per default quello della classe) e' solo un ripiego per
        i componenti non ancora costruiti — usarli entrambi come chiave
        produrrebbe due contabilita' parallele dello stesso servizio.
        """
        instance = descriptor.instance
        if isinstance(instance, IService):
            return instance.name
        return descriptor.name

    def _startup_order(self) -> list[ServiceDescriptor]:
        """Ordina i descrittori per dipendenza (ordinamento topologico).

        Un ciclo qui e' un errore di progettazione, non un caso da gestire: si
        segnala esplicitamente invece di produrre un ordine arbitrario.
        """
        with self._lock:
            descriptors = dict(self._descriptors)

        ordered: list[ServiceDescriptor] = []
        visited: dict[type[Any], int] = {}  # 0 = in corso, 1 = completato

        def visit(key: type[Any], chain: tuple[type[Any], ...]) -> None:
            mark = visited.get(key)
            if mark == 1:
                return
            if mark == 0:
                names = " → ".join(k.__name__ for k in [*chain, key])
                raise ServiceError(f"Dipendenza circolare fra servizi: {names}")

            descriptor = descriptors.get(key)
            if descriptor is None:
                return  # dipendenza esterna al registry: si ignora

            visited[key] = 0
            for dependency in descriptor.depends_on:
                visit(dependency, (*chain, key))
            visited[key] = 1
            ordered.append(descriptor)

        for key in descriptors:
            visit(key, ())
        return ordered

    # ------------------------------------------------------------------ #
    # Ciclo di vita
    # ------------------------------------------------------------------ #

    def start_all(self) -> list[str]:
        """Avvia tutti i servizi in ordine di dipendenza.

        Il fallimento di un servizio non critico viene registrato e l'avvio
        prosegue: e' la traduzione operativa di "se un modulo fallisce, mostrane
        lo stato e continua".

        :returns: nomi dei servizi che non sono partiti.
        :raises ServiceError: solo se fallisce un servizio ``critical``.
        """
        failed: list[str] = []

        for descriptor in self._startup_order():
            try:
                instance = self.resolve(descriptor.key)
            except ServiceError as exc:
                if descriptor.critical:
                    raise
                _log.error("Costruzione di '%s' fallita: %s", descriptor.name, exc)
                failed.append(descriptor.name)
                self._publish(descriptor.name, ServiceState.FAILED, str(exc))
                continue

            if not isinstance(instance, IService):
                continue  # componente senza ciclo di vita (config, tema, ...)

            name = self._display_name(descriptor)
            try:
                instance.start()
            except Exception as exc:
                _log.exception("Avvio di '%s' fallito", name)
                failed.append(name)
                self._publish(name, ServiceState.FAILED, str(exc))
                if descriptor.critical:
                    raise ServiceError(
                        f"Servizio critico '{name}' non avviato: {exc}"
                    ) from exc
            else:
                self._started.append(descriptor.key)
                self._publish(name, instance.health().state)

        if failed:
            _log.warning("Servizi non avviati: %s", ", ".join(failed))
        return failed

    def stop_all(self) -> None:
        """Ferma i servizi avviati, in ordine inverso.

        Ogni arresto e' isolato: un servizio che solleva in chiusura non deve
        impedire agli altri di rilasciare le proprie risorse.
        """
        for key in reversed(self._started):
            descriptor = self._descriptors.get(key)
            if descriptor is None or descriptor.instance is None:
                continue
            if not isinstance(descriptor.instance, IService):
                continue
            try:
                descriptor.instance.stop()
                self._publish(self._display_name(descriptor), ServiceState.STOPPED)
            except Exception:
                _log.exception("Arresto di '%s' fallito", self._display_name(descriptor))
        self._started.clear()

    def restart(self, key: type[Any]) -> bool:
        """Riavvia un singolo servizio. Usato dal supervisor.

        :returns: ``True`` se il servizio e' tornato operativo.
        """
        descriptor = self._descriptors.get(key)
        if descriptor is None or not isinstance(descriptor.instance, IService):
            return False

        service = descriptor.instance
        name = self._display_name(descriptor)
        self._restarts[name] = self._restarts.get(name, 0) + 1
        try:
            service.stop()
        except Exception:
            _log.exception("Arresto di '%s' fallito durante il riavvio", name)

        try:
            service.start()
        except Exception as exc:
            _log.error("Riavvio di '%s' fallito: %s", name, exc)
            self._publish(name, ServiceState.FAILED, str(exc))
            return False

        _log.info("Servizio '%s' riavviato", name)
        self._publish(name, service.health().state)
        return True

    # ------------------------------------------------------------------ #
    # Introspezione
    # ------------------------------------------------------------------ #

    def services(self) -> tuple[tuple[type[Any], IService], ...]:
        """Componenti costruiti che espongono un ciclo di vita."""
        with self._lock:
            return tuple(
                (d.key, d.instance)
                for d in self._descriptors.values()
                if isinstance(d.instance, IService)
            )

    def health_report(self) -> dict[str, Health]:
        """Salute corrente di ogni servizio, per il pannello di diagnostica."""
        report: dict[str, Health] = {}
        for _, service in self.services():
            try:
                report[service.name] = service.health()
            except Exception as exc:
                report[service.name] = Health(ServiceState.FAILED, f"health(): {exc}")
        return report

    def restart_count(self, name: str) -> int:
        """Numero di riavvii effettuati su un servizio."""
        return self._restarts.get(name, 0)

    def _publish(self, name: str, state: ServiceState, detail: str | None = None) -> None:
        """Pubblica un cambio di stato, se il bus e' disponibile."""
        if self._bus is None:
            return
        self._bus.publish(
            EventType.SERVICE_STATUS_CHANGED,
            ServiceStatusPayload(
                name=name,
                status=state.value,
                detail=detail,
                restarts=self._restarts.get(name, 0),
            ),
            source="registry",
        )

    def __iter__(self) -> Iterator[ServiceDescriptor]:
        with self._lock:
            return iter(list(self._descriptors.values()))

    def __len__(self) -> int:
        with self._lock:
            return len(self._descriptors)
