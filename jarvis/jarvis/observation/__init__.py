"""Observation System di JARVIS: sensori continui che emettono eventi."""

from jarvis.observation.base import Observer
from jarvis.observation.system import SystemObserver, collect_system_metrics
from jarvis.observation.filesystem import FilesystemObserver

__all__ = [
    "Observer",
    "SystemObserver",
    "FilesystemObserver",
    "collect_system_metrics",
]
