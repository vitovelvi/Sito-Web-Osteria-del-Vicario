"""Test del Self-Healing System."""

import unittest

from jarvis.events import Event, EventBus
from jarvis.healing import (
    ErrorClass,
    ErrorClassifier,
    RecoverySupervisor,
    RetryPolicy,
    RollbackManager,
)


class ClassifierTest(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = ErrorClassifier()

    def test_by_type(self) -> None:
        self.assertEqual(self.classifier.classify_exception(TimeoutError()),
                         ErrorClass.TRANSIENT)
        self.assertEqual(self.classifier.classify_exception(ValueError("x")),
                         ErrorClass.LOGIC)
        self.assertEqual(self.classifier.classify_exception(MemoryError()),
                         ErrorClass.RESOURCE)

    def test_by_message(self) -> None:
        self.assertEqual(self.classifier.classify("Boh", "rate limit exceeded"),
                         ErrorClass.EXTERNAL)
        self.assertEqual(self.classifier.classify("Boh", "connection refused"),
                         ErrorClass.TRANSIENT)


class RetryPolicyTest(unittest.IsolatedAsyncioTestCase):
    async def test_retries_transient_until_success(self) -> None:
        policy = RetryPolicy(max_retries=3, base_backoff_seconds=0.001)
        attempts = 0

        async def flaky() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ConnectionError("rete instabile")
            return "ok"

        result = await policy.run(flaky, ErrorClassifier())
        self.assertEqual(result, "ok")
        self.assertEqual(attempts, 3)

    async def test_logic_errors_not_retried(self) -> None:
        policy = RetryPolicy(max_retries=3, base_backoff_seconds=0.001)
        attempts = 0

        async def broken() -> None:
            nonlocal attempts
            attempts += 1
            raise ValueError("input sbagliato")

        with self.assertRaises(ValueError):
            await policy.run(broken, ErrorClassifier())
        self.assertEqual(attempts, 1)

    def test_backoff_grows(self) -> None:
        policy = RetryPolicy(base_backoff_seconds=0.5, backoff_multiplier=2.0)
        self.assertEqual(policy.backoff(1), 0.5)
        self.assertEqual(policy.backoff(2), 1.0)
        self.assertEqual(policy.backoff(3), 2.0)


class RollbackTest(unittest.IsolatedAsyncioTestCase):
    async def test_rollback_in_reverse_order(self) -> None:
        manager = RollbackManager()
        done: list[str] = []

        async def undo_a() -> None:
            done.append("a")

        async def undo_b() -> None:
            done.append("b")

        manager.register("ctx", undo_a)
        manager.register("ctx", undo_b)
        succeeded = await manager.rollback("ctx")
        self.assertEqual(succeeded, 2)
        self.assertEqual(done, ["b", "a"])  # LIFO

    async def test_discard(self) -> None:
        manager = RollbackManager()

        async def undo() -> None:
            raise AssertionError("non deve girare")

        manager.register("ctx", undo)
        manager.discard("ctx")
        self.assertEqual(await manager.rollback("ctx"), 0)


class SupervisorTest(unittest.IsolatedAsyncioTestCase):
    async def test_detects_and_classifies_from_bus(self) -> None:
        bus = EventBus()
        supervisor = RecoverySupervisor(bus)
        detected: list[Event] = []
        bus.subscribe("healing.detected", detected.append)
        await bus.start()
        await bus.publish(Event(
            topic="execution.step.failed",
            payload={"error": "connection timeout", "error_type": "TimeoutError"},
            source="test",
        ))
        await bus.drain()
        self.assertEqual(len(detected), 1)
        self.assertEqual(detected[0].payload["error_class"], "transient")
        self.assertEqual(detected[0].payload["strategy"], "retry")
        await bus.stop()


if __name__ == "__main__":
    unittest.main()
