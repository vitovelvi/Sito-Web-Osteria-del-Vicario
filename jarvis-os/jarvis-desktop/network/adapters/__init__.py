"""Adapter di backend disponibili all'interfaccia.

``OpenClawAdapter`` vive nel pacchetto separato ``jarvis-adapter-openclaw``:
dipende solo dal contratto, non dalla GUI, e puo' essere riusato da qualunque
altro client JCP.
"""

from jarvis_adapter_openclaw import OpenClawAdapter

from network.adapters.base import IBackendAdapter
from network.adapters.native import NativeJcpAdapter

__all__ = ["IBackendAdapter", "NativeJcpAdapter", "OpenClawAdapter"]
