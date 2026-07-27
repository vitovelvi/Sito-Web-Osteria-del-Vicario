"""Implementazioni del trasporto."""

from network.transport.base import ITransport
from network.transport.websocket import WebSocketTransport

__all__ = ["ITransport", "WebSocketTransport"]
