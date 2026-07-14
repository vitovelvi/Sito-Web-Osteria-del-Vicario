"""Memory System di JARVIS: memorie separate con backend sostituibili."""

from jarvis.memory.base import MemoryBackend, MemoryRecord
from jarvis.memory.manager import MemoryManager

__all__ = ["MemoryBackend", "MemoryRecord", "MemoryManager"]
