"""Test del service registry e della configurazione stratificata."""

from __future__ import annotations

import json

import pytest

from core.errors import ServiceError
from core.eventbus import EventBus
from core.registry import ServiceRegistry
from core.service import BaseService, ServiceState
from core.settings import AppSettings, SettingsStore, load_settings

# --------------------------------------------------------------------------- #
# Service registry
# --------------------------------------------------------------------------- #


class _Servizio(BaseService):
    def __init__(self, name: str, *, fallisce: bool = False) -> None:
        super().__init__(name)
        self.fallisce = fallisce
        self.avvii = 0

    def _on_start(self) -> None:
        self.avvii += 1
        if self.fallisce:
            raise RuntimeError("avvio fallito")


def test_risoluzione_e_singleton() -> None:
    registry = ServiceRegistry()
    registry.register(_Servizio, lambda _: _Servizio("a"))

    assert registry.resolve(_Servizio) is registry.resolve(_Servizio)


def test_chiave_non_registrata() -> None:
    with pytest.raises(ServiceError, match="Nessun componente"):
        ServiceRegistry().resolve(_Servizio)


def test_try_resolve_restituisce_none() -> None:
    assert ServiceRegistry().try_resolve(_Servizio) is None


def test_dipendenza_circolare_intercettata() -> None:
    """Senza questo controllo si otterrebbe una ricorsione infinita."""

    class A:
        pass

    class B:
        pass

    registry = ServiceRegistry()
    registry.register(A, lambda r: r.resolve(B))
    registry.register(B, lambda r: r.resolve(A))

    with pytest.raises(ServiceError, match="circolare"):
        registry.resolve(A)


def test_ordine_di_avvio_topologico() -> None:
    """L'ordine deriva dalle dipendenze dichiarate, non dall'ordine di scrittura."""
    avviati: list[str] = []

    class Base(BaseService):
        def _on_start(self) -> None:
            avviati.append(self.name)

    class Rete(Base):
        pass

    class Audio(Base):
        pass

    registry = ServiceRegistry()
    registry.register(Audio, lambda _: Audio("audio"), depends_on=[Rete])
    registry.register(Rete, lambda _: Rete("rete"))

    registry.start_all()

    assert avviati == ["rete", "audio"]


def test_servizio_non_critico_che_fallisce_non_ferma_gli_altri() -> None:
    """Traduzione operativa di "se un modulo fallisce, gli altri continuano"."""

    class Webcam(_Servizio):
        pass

    class Rete(_Servizio):
        pass

    registry = ServiceRegistry()
    registry.register(Webcam, lambda _: Webcam("webcam", fallisce=True))
    registry.register(Rete, lambda _: Rete("rete"))

    falliti = registry.start_all()

    assert falliti == ["webcam"]
    assert registry.resolve(Rete).health().state is ServiceState.RUNNING


def test_servizio_critico_che_fallisce_interrompe() -> None:
    registry = ServiceRegistry()
    registry.register(_Servizio, lambda _: _Servizio("nucleo", fallisce=True), critical=True)

    with pytest.raises(ServiceError, match="critico"):
        registry.start_all()


def test_stop_in_ordine_inverso() -> None:
    ordine: list[str] = []

    class Base(BaseService):
        def _on_start(self) -> None:
            pass

        def _on_stop(self) -> None:
            ordine.append(self.name)

    class Uno(Base):
        pass

    class Due(Base):
        pass

    registry = ServiceRegistry()
    registry.register(Uno, lambda _: Uno("uno"))
    registry.register(Due, lambda _: Due("due"), depends_on=[Uno])

    registry.start_all()
    registry.stop_all()

    assert ordine == ["due", "uno"]


def test_restart_conta_i_riavvii(bus: EventBus) -> None:
    registry = ServiceRegistry(bus)
    registry.register(_Servizio, lambda _: _Servizio("rete"))
    registry.start_all()

    assert registry.restart(_Servizio)
    assert registry.restart_count("rete") == 1
    assert registry.resolve(_Servizio).avvii == 2


def test_disabled_non_e_un_guasto() -> None:
    """Distinguere 'spento per scelta' da 'rotto' evita falsi allarmi in HUD."""
    servizio = _Servizio("visione")
    servizio.mark_disabled("webcam non richiesta")
    assert servizio.health().state is ServiceState.DISABLED
    assert not servizio.health().is_usable


# --------------------------------------------------------------------------- #
# Configurazione
# --------------------------------------------------------------------------- #


def test_default_caricati(temp_paths) -> None:
    settings = load_settings(temp_paths)
    assert settings.ui.target_fps == 60
    assert settings.audio.tts_mode == "backend"  # decisione architetturale, non caso


def test_preferenze_utente_sovrascrivono_i_default(temp_paths) -> None:
    temp_paths.user_settings.write_text(
        json.dumps({"ui": {"target_fps": 30}}), encoding="utf-8"
    )
    settings = load_settings(temp_paths)

    assert settings.ui.target_fps == 30
    assert settings.ui.quality == "auto"  # le altre chiavi seguono i default


def test_configurazione_corrotta_non_impedisce_l_avvio(temp_paths) -> None:
    """Un settings.json rotto non deve bloccare un'app che parte al login."""
    temp_paths.user_settings.write_text("{{{ non json", encoding="utf-8")
    assert load_settings(temp_paths).ui.target_fps == 60


def test_valore_fuori_range_ricade_sui_default(temp_paths) -> None:
    temp_paths.user_settings.write_text(
        json.dumps({"ui": {"target_fps": 5000}}), encoding="utf-8"
    )
    assert load_settings(temp_paths) == AppSettings()


def test_override_da_ambiente(temp_paths, monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_BACKEND__URL", "ws://192.168.1.10:9000/j")
    monkeypatch.setenv("JARVIS_UI__TARGET_FPS", "30")

    settings = load_settings(temp_paths)

    assert settings.backend.url == "ws://192.168.1.10:9000/j"
    assert settings.ui.target_fps == 30


def test_store_salva_solo_le_differenze(temp_paths) -> None:
    store = SettingsStore(temp_paths)
    cambiate = store.update({"ui": {"target_fps": 30}})

    assert "ui.target_fps" in cambiate
    assert store.current.ui.target_fps == 30
    assert json.loads(temp_paths.user_settings.read_text()) == {"ui": {"target_fps": 30}}
