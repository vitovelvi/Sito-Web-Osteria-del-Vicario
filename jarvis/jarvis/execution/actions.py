"""Azioni standard registrate nell'Executor.

Ogni azione dichiara il proprio livello di sicurezza e i parametri richiesti.
Gli handler ricevono un :class:`ActionContext` con i servizi iniettati dal
Kernel (``memory``, ``llm_router``, ``sandbox``, ``identity``) — mai i
sottosistemi interi né accesso al terminale.
"""

from __future__ import annotations

import json
from typing import Any

from jarvis.execution.executor import ActionContext, ActionSpec, Executor
from jarvis.llm import LLMRequest, Quality
from jarvis.security import SecurityLevel


async def _system_stats(ctx: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
    """Snapshot delle metriche di sistema (Livello 0)."""
    from jarvis.observation.system import collect_system_metrics

    return collect_system_metrics(top_processes=int(params.get("top", 5)))


async def _memory_recall(ctx: ActionContext, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Recupero dalla memoria (Livello 0)."""
    memory = ctx.service("memory")
    return memory.context_for(str(params.get("text", "")),
                              limit=int(params.get("limit", 5)))


async def _memory_store(ctx: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
    """Scrittura in memoria (Livello 1: reversibile, si può dimenticare)."""
    memory = ctx.service("memory")
    store_name = str(params.get("store", "semantic"))
    store = {
        "semantic": memory.semantic,
        "episodic": memory.episodic,
        "preference": memory.preference,
        "working": memory.working,
    }.get(store_name, memory.semantic)
    record = store.remember(dict(params.get("content", {})),
                            tags=list(params.get("tags", [])),
                            importance=float(params.get("importance", 0.5)))
    return {"record_id": record.record_id, "store": store_name}


async def _fs_list(ctx: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
    """Elenco directory dentro la sandbox (Livello 0)."""
    sandbox = ctx.service("sandbox")
    path = sandbox.check_read_path(str(params.get("path", ".")))
    entries = sorted(p.name + ("/" if p.is_dir() else "") for p in path.iterdir())
    return {"path": str(path), "entries": entries[:200]}


async def _fs_read(ctx: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
    """Lettura file dentro la sandbox (Livello 0)."""
    sandbox = ctx.service("sandbox")
    path = sandbox.check_read_path(str(params["path"]))
    text = path.read_text(encoding="utf-8", errors="replace")
    limit = int(params.get("max_chars", 20000))
    return {"path": str(path), "content": text[:limit], "truncated": len(text) > limit}


async def _fs_write(ctx: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
    """Scrittura file SOLO nelle radici di scrittura della sandbox (Livello 1)."""
    sandbox = ctx.service("sandbox")
    path = sandbox.check_write_path(str(params["path"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(params.get("content", "")), encoding="utf-8")
    return {"path": str(path), "bytes": len(str(params.get("content", "")))}


async def _web_search(ctx: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
    """Ricerca web (Livello 0). Placeholder documentato.

    Integrazione reale: SearxNG locale, Brave Search API o simili; la chiave
    va letta dall'ambiente. Il contratto (query → risultati) resta questo.
    """
    return {
        "query": str(params.get("query", "")),
        "results": [],
        "note": "Ricerca web non configurata: collegare un motore in web.search",
    }


async def _llm_generate(ctx: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
    """Generazione tramite LLM Router (Livello 0: produce solo testo)."""
    router = ctx.service("llm_router")
    identity = ctx.service("identity")
    context = params.get("context") or []
    prompt = str(params.get("prompt", ""))
    if context:
        prompt = (
            "Contesto dalla memoria:\n"
            + json.dumps(context, ensure_ascii=False, indent=2)[:2000]
            + f"\n\nRichiesta: {prompt}"
        )
    quality = Quality(str(params.get("quality", "standard")))
    response = await router.generate(LLMRequest(
        prompt=prompt,
        system=identity.system_prompt(),
        quality=quality,
        max_tokens=int(params.get("max_tokens", 1024)),
    ))
    return {"text": response.text, "provider": response.provider,
            "model": response.model}


async def _respond(ctx: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
    """Step terminale: marca il piano come dotato di risposta (Livello 0).

    La composizione finale della risposta è fatta dall'ExecutiveAgent, che
    ha visibilità sui risultati degli step precedenti.
    """
    return {"template": str(params.get("template", "llm")),
            "request": str(params.get("request", ""))}


def register_standard_actions(executor: Executor) -> None:
    """Registra il set standard di azioni sul registro dell'Executor."""
    specs = [
        ActionSpec("system.stats", _system_stats, SecurityLevel.READ_ONLY,
                   "Metriche di sistema: CPU, RAM, processi"),
        ActionSpec("memory.recall", _memory_recall, SecurityLevel.READ_ONLY,
                   "Recupero dalla memoria"),
        ActionSpec("memory.store", _memory_store, SecurityLevel.REVERSIBLE,
                   "Scrittura in memoria", required_params=("content",)),
        ActionSpec("fs.list", _fs_list, SecurityLevel.READ_ONLY,
                   "Elenco directory (sandbox)"),
        ActionSpec("fs.read", _fs_read, SecurityLevel.READ_ONLY,
                   "Lettura file (sandbox)", required_params=("path",)),
        ActionSpec("fs.write", _fs_write, SecurityLevel.REVERSIBLE,
                   "Scrittura file (solo radici sandbox)", required_params=("path",)),
        ActionSpec("web.search", _web_search, SecurityLevel.READ_ONLY,
                   "Ricerca web (placeholder configurabile)"),
        ActionSpec("llm.generate", _llm_generate, SecurityLevel.READ_ONLY,
                   "Generazione testo via LLM Router", required_params=("prompt",)),
        ActionSpec("respond", _respond, SecurityLevel.READ_ONLY,
                   "Consegna della risposta all'utente"),
    ]
    for spec in specs:
        executor.register(spec)
