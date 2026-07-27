"""Comunicazione con il backend OpenClaw.

Il pacchetto è organizzato per responsabilità crescente: ``transport`` sposta
buste senza interpretarle, ``dispatcher`` le traduce in eventi di dominio,
``service`` governa sessione, heartbeat e riconnessione. La GUI conosce solo
quest'ultimo, e nemmeno i suoi dettagli.
"""

from network.service import NetworkService

__all__ = ["NetworkService"]
