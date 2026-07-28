"""Rendering leggibile dei payload per la Developer Console.

Un ispettore che stampa ``<AudioChunk object at 0x7f…>`` non serve a nulla. Qui
i payload — dataclass, modelli Pydantic, dizionari, byte — diventano testo
leggibile, con due accorgimenti che contano nell'uso reale:

* i **byte non vengono stampati**: uno stream audio ha blocchi da 2880 byte e
  riempirebbero la finestra. Se ne mostra dimensione e anteprima esadecimale;
* le stringhe lunghe vengono **troncate** con indicazione della lunghezza
  originale, così un base64 da 4 KB non nasconde i campi che gli stanno intorno.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Final

__all__ = ["format_payload", "summarize"]

#: Oltre questa lunghezza una stringa viene troncata nella vista.
_MAX_STRING: Final[int] = 120

#: Byte mostrati in anteprima esadecimale.
_HEX_PREVIEW: Final[int] = 16

#: Profondità massima di annidamento, per non incorrere in strutture cicliche.
_MAX_DEPTH: Final[int] = 6


def _render(value: Any, depth: int = 0) -> str:
    """Converte un valore in testo, ricorsivamente."""
    if depth > _MAX_DEPTH:
        return "…"

    if value is None:
        return "—"
    if isinstance(value, bool):
        return "sì" if value else "no"
    if isinstance(value, (int, float)):
        return f"{value:.3f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)

    if isinstance(value, (bytes, bytearray)):
        preview = bytes(value[:_HEX_PREVIEW]).hex(" ")
        suffix = "…" if len(value) > _HEX_PREVIEW else ""
        return f"<{len(value)} byte> {preview}{suffix}"

    if isinstance(value, str):
        if len(value) <= _MAX_STRING:
            return value
        return f"{value[:_MAX_STRING]}… ({len(value)} caratteri)"

    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
        if not items:
            return "(vuoto)"
        if len(items) > 12:
            head = ", ".join(_render(i, depth + 1) for i in items[:12])
            return f"[{head}, … {len(items)} elementi]"
        return "[" + ", ".join(_render(i, depth + 1) for i in items) + "]"

    if isinstance(value, dict):
        if not value:
            return "(vuoto)"
        return "\n".join(f"  {k}: {_render(v, depth + 1)}" for k, v in value.items())

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        fields = {f.name: getattr(value, f.name, None) for f in dataclasses.fields(value)}
        return _render(fields, depth)

    # Modelli Pydantic e simili.
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return _render(dump(), depth)
        except Exception:
            pass

    return str(value)


def format_payload(payload: Any) -> str:
    """Rendering multilinea di un payload, per il pannello di dettaglio."""
    if payload is None:
        return "(nessun payload)"
    try:
        rendered = _render(payload)
    except Exception as exc:
        return f"(payload non rappresentabile: {exc})"

    type_name = type(payload).__name__
    return f"{type_name}\n{rendered}" if rendered != "—" else type_name


def summarize(payload: Any, limit: int = 70) -> str:
    """Riga singola per la timeline.

    Mostra i primi campi significativi invece del nome del tipo: scorrendo la
    timeline si vuole vedere *cosa* è successo, non di che classe è l'oggetto.
    """
    if payload is None:
        return ""

    try:
        if dataclasses.is_dataclass(payload) and not isinstance(payload, type):
            parts = []
            for field in dataclasses.fields(payload)[:4]:
                value = getattr(payload, field.name, None)
                if value in (None, "", (), 0.0):
                    continue
                parts.append(f"{field.name}={_render(value, _MAX_DEPTH - 1)}")
            text = " ".join(parts)
        elif isinstance(payload, dict):
            campi = list(payload.items())[:4]
            text = " ".join(f"{k}={_render(v, _MAX_DEPTH - 1)}" for k, v in campi)
        else:
            text = _render(payload, _MAX_DEPTH - 1)
    except Exception:
        return "(non rappresentabile)"

    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
