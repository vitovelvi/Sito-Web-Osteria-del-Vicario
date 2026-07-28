"""Vocabolario visivo condiviso dai pannelli operativi.

Le corrispondenze stato→testo e rischio→colore vivono qui e non nei singoli
widget. Se ogni pannello traducesse per conto proprio, la stessa azione
apparirebbe "in coda" in un punto e "in attesa" in un altro — e nessuno
saprebbe quale delle due è quella giusta.
"""

from __future__ import annotations

from typing import Final

from jarvis_protocol.missions import ActionStatus, MissionStatus, RiskLevel

__all__ = [
    "ACTION_LABEL",
    "ACTION_TOKEN",
    "MISSION_LABEL",
    "MISSION_TOKEN",
    "RISK_LABEL",
    "RISK_TOKEN",
    "format_duration",
]

ACTION_LABEL: Final[dict[str, str]] = {
    ActionStatus.QUEUED.value: "in coda",
    ActionStatus.WAITING_CONFIRMATION.value: "attende conferma",
    ActionStatus.RUNNING.value: "in esecuzione",
    ActionStatus.OK.value: "completata",
    ActionStatus.ERROR.value: "fallita",
    ActionStatus.CANCELLED.value: "annullata",
    ActionStatus.DENIED.value: "negata",
    ActionStatus.UNKNOWN.value: "esito ignoto",
}

ACTION_TOKEN: Final[dict[str, str]] = {
    ActionStatus.QUEUED.value: "text.muted",
    ActionStatus.WAITING_CONFIRMATION.value: "state.warning",
    ActionStatus.RUNNING.value: "state.thinking",
    ActionStatus.OK.value: "state.success",
    ActionStatus.ERROR.value: "state.error",
    ActionStatus.CANCELLED.value: "text.muted",
    ActionStatus.DENIED.value: "state.warning",
    ActionStatus.UNKNOWN.value: "state.offline",
}

MISSION_LABEL: Final[dict[str, str]] = {
    MissionStatus.RUNNING.value: "in corso",
    MissionStatus.COMPLETED.value: "completata",
    MissionStatus.FAILED.value: "fallita",
    MissionStatus.CANCELLED.value: "annullata",
    MissionStatus.UNKNOWN.value: "esito ignoto",
}

MISSION_TOKEN: Final[dict[str, str]] = {
    MissionStatus.RUNNING.value: "state.thinking",
    MissionStatus.COMPLETED.value: "state.success",
    MissionStatus.FAILED.value: "state.error",
    MissionStatus.CANCELLED.value: "text.muted",
    MissionStatus.UNKNOWN.value: "state.offline",
}

RISK_LABEL: Final[dict[str, str]] = {
    RiskLevel.LOW.value: "basso",
    RiskLevel.MEDIUM.value: "medio",
    RiskLevel.HIGH.value: "alto",
    RiskLevel.DESTRUCTIVE.value: "distruttivo",
}

RISK_TOKEN: Final[dict[str, str]] = {
    RiskLevel.LOW.value: "text.muted",
    RiskLevel.MEDIUM.value: "state.warning",
    RiskLevel.HIGH.value: "state.error",
    RiskLevel.DESTRUCTIVE.value: "state.error",
}


def format_duration(ms: float | None) -> str:
    """Durata leggibile.

    Le unità cambiano con la scala: "1247 ms" e "1,2 s" sono lo stesso numero,
    ma solo il secondo si confronta a colpo d'occhio con "18 s".
    """
    if ms is None:
        return "—"
    if ms < 1000:
        return f"{ms:.0f} ms"
    if ms < 60_000:
        return f"{ms / 1000:.1f} s".replace(".", ",")
    minuti, secondi = divmod(ms / 1000, 60)
    return f"{int(minuti)}m {int(secondi)}s"
