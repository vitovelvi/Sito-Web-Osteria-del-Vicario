"""Task Manager: ogni richiesta importante diventa un task tracciato.

Un task ha ID, stato, priorità, dipendenze, log e cronologia delle
transizioni. Il manager valida le transizioni, rispetta le dipendenze e
pubblica ogni cambiamento sul bus (``task.created`` / ``task.updated``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, IntEnum
from typing import Any

from jarvis.events import Event, EventBus
from jarvis.logging import get_logger

_log = get_logger("tasks")


class TaskState(str, Enum):
    """Ciclo di vita di un task."""

    PENDING = "pending"
    BLOCKED = "blocked"      # dipendenze non completate
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Transizioni lecite: tutto il resto è un errore di programmazione.
_ALLOWED: dict[TaskState, set[TaskState]] = {
    TaskState.PENDING: {TaskState.RUNNING, TaskState.BLOCKED, TaskState.CANCELLED},
    TaskState.BLOCKED: {TaskState.PENDING, TaskState.CANCELLED},
    TaskState.RUNNING: {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.COMPLETED: set(),
    TaskState.FAILED: {TaskState.PENDING},  # retry esplicito
    TaskState.CANCELLED: set(),
}


class TaskPriority(IntEnum):
    """Priorità di un task (più alto = più urgente)."""

    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@dataclass(slots=True)
class Task:
    """Task tracciato dal manager."""

    title: str
    priority: TaskPriority = TaskPriority.NORMAL
    depends_on: list[str] = field(default_factory=list)
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    state: TaskState = TaskState.PENDING
    created_at: str = field(default_factory=_now)
    logs: list[dict[str, str]] = field(default_factory=list)
    history: list[dict[str, str]] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    result: Any = None

    def add_log(self, message: str) -> None:
        self.logs.append({"ts": _now(), "message": message})

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "state": self.state.value,
            "priority": int(self.priority),
            "depends_on": self.depends_on,
            "created_at": self.created_at,
            "logs": self.logs[-20:],
            "history": self.history,
        }


class InvalidTransition(Exception):
    """Transizione di stato non consentita."""


class TaskManager:
    """Registro dei task con transizioni validate e notifica a eventi."""

    def __init__(self, bus: EventBus, max_history: int = 200) -> None:
        self._bus = bus
        self._tasks: dict[str, Task] = {}
        self._max_history = max_history

    async def create(
        self,
        title: str,
        *,
        priority: TaskPriority = TaskPriority.NORMAL,
        depends_on: list[str] | None = None,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> Task:
        """Crea un task; nasce BLOCKED se ha dipendenze non completate."""
        task = Task(title=title, priority=priority,
                    depends_on=depends_on or [], payload=payload or {})
        if any(not self._is_done(dep) for dep in task.depends_on):
            task.state = TaskState.BLOCKED
        task.history.append({"ts": _now(), "state": task.state.value})
        task.add_log("task creato")
        self._tasks[task.task_id] = task
        self._trim()
        await self._bus.publish(Event(
            topic="task.created", payload=task.to_dict(),
            source="tasks.manager", correlation_id=correlation_id,
        ))
        return task

    async def transition(self, task_id: str, new_state: TaskState,
                         note: str = "") -> Task:
        """Applica una transizione di stato validata."""
        task = self._require(task_id)
        if new_state not in _ALLOWED[task.state]:
            raise InvalidTransition(
                f"{task.state.value} → {new_state.value} non consentita per {task_id}"
            )
        if new_state == TaskState.RUNNING and any(
            not self._is_done(dep) for dep in task.depends_on
        ):
            raise InvalidTransition(f"Task {task_id} ha dipendenze incomplete")
        task.state = new_state
        task.history.append({"ts": _now(), "state": new_state.value})
        if note:
            task.add_log(note)
        await self._bus.publish(Event(
            topic="task.updated", payload=task.to_dict(), source="tasks.manager",
        ))
        await self._unblock_dependents(task)
        return task

    async def _unblock_dependents(self, completed: Task) -> None:
        if completed.state != TaskState.COMPLETED:
            return
        for task in self._tasks.values():
            if (task.state == TaskState.BLOCKED
                    and all(self._is_done(dep) for dep in task.depends_on)):
                task.state = TaskState.PENDING
                task.history.append({"ts": _now(), "state": task.state.value})
                task.add_log(f"sbloccato dal completamento di {completed.task_id}")
                await self._bus.publish(Event(
                    topic="task.updated", payload=task.to_dict(),
                    source="tasks.manager",
                ))

    # ------------------------------------------------------------------ API

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def all_tasks(self) -> list[Task]:
        """Task ordinati per priorità decrescente e anzianità."""
        return sorted(self._tasks.values(),
                      key=lambda t: (-int(t.priority), t.created_at))

    def snapshot(self) -> dict[str, Any]:
        by_state: dict[str, int] = {}
        for task in self._tasks.values():
            by_state[task.state.value] = by_state.get(task.state.value, 0) + 1
        return {
            "total": len(self._tasks),
            "by_state": by_state,
            "recent": [t.to_dict() for t in self.all_tasks()[:20]],
        }

    # ------------------------------------------------------------ interni

    def _require(self, task_id: str) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"Task inesistente: {task_id}")
        return task

    def _is_done(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        return task is not None and task.state == TaskState.COMPLETED

    def _trim(self) -> None:
        """Contiene la cronologia: rimuove i task terminali più vecchi."""
        if len(self._tasks) <= self._max_history:
            return
        terminal = [t for t in self._tasks.values()
                    if t.state in (TaskState.COMPLETED, TaskState.CANCELLED,
                                   TaskState.FAILED)]
        terminal.sort(key=lambda t: t.created_at)
        for task in terminal[: len(self._tasks) - self._max_history]:
            del self._tasks[task.task_id]
