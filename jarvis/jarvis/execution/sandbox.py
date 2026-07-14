"""Sandbox: perimetro di esecuzione delle azioni.

Applica i confini a runtime, indipendentemente da cosa dichiara l'azione:
    - timeout per step;
    - confinamento dei percorsi (lettura/scrittura solo nelle radici consentite);
    - limite alla dimensione dell'output.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from jarvis.config import Config


class SandboxViolation(Exception):
    """Violazione dei confini della sandbox."""


class Sandbox:
    """Perimetro di esecuzione configurabile."""

    def __init__(self, config: Config) -> None:
        section = config.section("execution")
        self.step_timeout = float(section.get("step_timeout_seconds", 30.0))
        self.max_output_bytes = int(section.get("sandbox.max_output_bytes", 262144))
        base = config.source.parent.parent if config.source else Path.cwd()
        self._read_roots = [
            (base / p).resolve() if not Path(p).is_absolute() else Path(p).resolve()
            for p in section.get("sandbox.allowed_read_roots", ["."])
        ]
        self._write_roots = [
            (base / p).resolve() if not Path(p).is_absolute() else Path(p).resolve()
            for p in section.get("sandbox.allowed_write_roots", [])
        ]
        for root in self._write_roots:
            root.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------------- path

    def check_read_path(self, raw: str) -> Path:
        """Risolve e autorizza un percorso in lettura."""
        return self._check(raw, self._read_roots, "lettura")

    def check_write_path(self, raw: str) -> Path:
        """Risolve e autorizza un percorso in scrittura."""
        return self._check(raw, self._write_roots, "scrittura")

    def _check(self, raw: str, roots: list[Path], mode: str) -> Path:
        resolved = Path(raw).expanduser().resolve()
        for root in roots:
            if resolved == root or resolved.is_relative_to(root):
                return resolved
        raise SandboxViolation(
            f"Percorso fuori dalla sandbox in {mode}: {resolved}"
        )

    # ---------------------------------------------------------------- run

    async def run(self, fn: Callable[[], Awaitable[Any]]) -> Any:
        """Esegue una coroutine dentro il perimetro (timeout + limite output)."""
        try:
            result = await asyncio.wait_for(fn(), timeout=self.step_timeout)
        except asyncio.TimeoutError as exc:
            raise SandboxViolation(
                f"Timeout dello step ({self.step_timeout}s)"
            ) from exc
        self._check_output_size(result)
        return result

    def _check_output_size(self, result: Any) -> None:
        try:
            size = len(json.dumps(result, default=str).encode("utf-8"))
        except (TypeError, ValueError):
            return  # output non serializzabile: il broker lo tronca comunque
        if size > self.max_output_bytes:
            raise SandboxViolation(
                f"Output oltre il limite di sandbox ({size} > {self.max_output_bytes} byte)"
            )
