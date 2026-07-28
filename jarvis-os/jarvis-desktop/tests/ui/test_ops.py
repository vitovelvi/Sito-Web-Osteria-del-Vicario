"""Test del livello operativo: missioni, azioni, coda."""

from __future__ import annotations

import pytest

from core.events import ActionSnapshot
from ui.ops.mission_panel import _ActionRow
from ui.theme.theme import Theme, load_theme


@pytest.fixture
def theme() -> Theme:
    return load_theme()


def _azione(status: str, **overrides) -> ActionSnapshot:
    base = {
        "action_id": "a1",
        "tool": "fs.write_file",
        "title": "Aggiorna il rapporto",
        "status": status,
        "risk": "high",
        "duration_ms": 363.0,
    }
    base.update(overrides)
    return ActionSnapshot(**base)


def test_il_rischio_colora_solo_finche_l_esito_e_aperto(qt_app, theme: Theme) -> None:
    """Un'azione riuscita non si mostra in rosso perché lo strumento è rischioso.

    Il colore è la prima cosa che si legge: su un'azione conclusa il colore del
    rischio direbbe il contrario di quello che è successo.
    """
    riga = _ActionRow(theme)
    rosso = theme.color("state.error").name()

    riga.update_from(_azione("running"))
    assert rosso in riga._meta.styleSheet()

    riga.update_from(_azione("ok"))
    assert rosso not in riga._meta.styleSheet()


def test_lo_stile_del_rischio_non_resta_sulla_riga_riusata(qt_app, theme: Theme) -> None:
    """Le righe si riusano: senza azzeramento, il rosso passa all'azione dopo."""
    riga = _ActionRow(theme)

    riga.update_from(_azione("running"))
    riga.update_from(_azione("running", tool="web.search", risk="low", action_id="a2"))

    assert riga._meta.styleSheet() == ""


def test_il_pallino_segue_sempre_l_esito(qt_app, theme: Theme) -> None:
    """Il segnale di esito resta leggibile qualunque sia il rischio."""
    riga = _ActionRow(theme)

    riga.update_from(_azione("ok"))
    assert theme.color("state.success").name() in riga._status.styleSheet()

    riga.update_from(_azione("error"))
    assert theme.color("state.error").name() in riga._status.styleSheet()
