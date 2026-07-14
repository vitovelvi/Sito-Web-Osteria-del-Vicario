"""Utility condivise dai test."""

from __future__ import annotations

from typing import Any

from jarvis.config import Config


def test_config(**overrides: Any) -> Config:
    """Configurazione minimale per i test: tutto volatile e silenzioso."""
    data: dict[str, Any] = {
        "identity": {
            "name": "JARVIS-TEST",
            "personality": {"traits": ["preciso"], "philosophy": "test",
                            "tone": {"register": "neutro"}},
            "operating_rules": ["Mai operazioni distruttive senza conferma."],
            "priorities": ["sicurezza"],
            "autonomy": {"default_level": "supervised"},
        },
        "logging": {"level": "WARNING", "console": False, "file": None},
        "memory": {"backend": "memory", "data_dir": "runtime/test-memory"},
        "events": {"history_size": 100, "queue_size": 512},
        "observation": {
            "system": {"enabled": False},
            "filesystem": {"enabled": False, "watch_paths": []},
            "integrations": {},
        },
        "llm": {
            "providers": {
                "ollama": {"enabled": False},
                "free": {"enabled": False},
                "claude": {"enabled": False},
            },
            "routing": {"prefer_local": True},
        },
        "execution": {
            "step_timeout_seconds": 10.0,
            "sandbox": {"allowed_read_roots": ["."],
                        "allowed_write_roots": ["runtime/test-sandbox"],
                        "max_output_bytes": 262144},
        },
        "security": {"confirmation_required_from_level": 2,
                     "auto_deny_when_unattended": True},
        "voice": {"enabled": False},
        "tasks": {"max_history": 50},
        "healing": {"max_retries": 2, "base_backoff_seconds": 0.01,
                    "backoff_multiplier": 2.0},
        "dashboard": {"enabled": False},
    }
    data.update(overrides)
    return Config(data)
