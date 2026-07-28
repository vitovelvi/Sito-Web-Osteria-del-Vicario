"""Adapter di backend: traducono fra JCP e il dialetto di un backend specifico."""

from network.adapters.base import IBackendAdapter
from network.adapters.native import NativeJcpAdapter
from network.adapters.openclaw import OpenClawAdapter

__all__ = ["IBackendAdapter", "NativeJcpAdapter", "OpenClawAdapter"]
