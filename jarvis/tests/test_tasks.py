"""Test del Task Manager."""

import unittest

from jarvis.events import EventBus
from jarvis.tasks import TaskManager, TaskPriority, TaskState
from jarvis.tasks.manager import InvalidTransition


class TaskManagerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bus = EventBus()
        await self.bus.start()
        self.manager = TaskManager(self.bus)

    async def asyncTearDown(self) -> None:
        await self.bus.drain()
        await self.bus.stop()

    async def test_lifecycle(self) -> None:
        task = await self.manager.create("test", priority=TaskPriority.HIGH)
        self.assertEqual(task.state, TaskState.PENDING)
        await self.manager.transition(task.task_id, TaskState.RUNNING, "via")
        await self.manager.transition(task.task_id, TaskState.COMPLETED, "fine")
        stored = self.manager.get(task.task_id)
        assert stored is not None
        self.assertEqual(stored.state, TaskState.COMPLETED)
        self.assertEqual(len(stored.history), 3)  # pending, running, completed
        self.assertGreaterEqual(len(stored.logs), 3)

    async def test_invalid_transition_rejected(self) -> None:
        task = await self.manager.create("test")
        with self.assertRaises(InvalidTransition):
            await self.manager.transition(task.task_id, TaskState.COMPLETED)

    async def test_dependencies_block_and_unblock(self) -> None:
        first = await self.manager.create("prima")
        second = await self.manager.create("dopo", depends_on=[first.task_id])
        self.assertEqual(second.state, TaskState.BLOCKED)
        with self.assertRaises(InvalidTransition):
            await self.manager.transition(second.task_id, TaskState.RUNNING)
        await self.manager.transition(first.task_id, TaskState.RUNNING)
        await self.manager.transition(first.task_id, TaskState.COMPLETED)
        refreshed = self.manager.get(second.task_id)
        assert refreshed is not None
        self.assertEqual(refreshed.state, TaskState.PENDING)

    async def test_events_published(self) -> None:
        topics: list[str] = []
        self.bus.subscribe("task.*", lambda e: topics.append(e.topic))
        task = await self.manager.create("evento")
        await self.manager.transition(task.task_id, TaskState.RUNNING)
        await self.bus.drain()
        self.assertIn("task.created", topics)
        self.assertIn("task.updated", topics)


if __name__ == "__main__":
    unittest.main()
