"""Test dell'Event Bus."""

import unittest

from jarvis.events import Event, EventBus
from jarvis.events.bus import topic_matches


class TopicMatchingTest(unittest.TestCase):
    def test_exact_and_wildcard(self) -> None:
        self.assertTrue(topic_matches("system.metrics", "system.metrics"))
        self.assertTrue(topic_matches("system.*", "system.metrics"))
        self.assertTrue(topic_matches("system.*", "system.alert.cpu"))
        self.assertTrue(topic_matches("*", "qualunque.cosa"))
        self.assertFalse(topic_matches("system.*", "file.created"))
        self.assertFalse(topic_matches("system.metrics", "system.alert"))


class EventBusTest(unittest.IsolatedAsyncioTestCase):
    async def test_delivery_and_history(self) -> None:
        bus = EventBus(history_size=10)
        received: list[Event] = []
        bus.subscribe("test.*", received.append)
        await bus.start()
        await bus.publish(Event(topic="test.uno", payload={"n": 1}, source="t"))
        await bus.publish(Event(topic="altro.due", payload={"n": 2}, source="t"))
        await bus.drain()
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].payload["n"], 1)
        self.assertEqual(len(bus.history()), 2)
        await bus.stop()

    async def test_handler_error_is_isolated_and_republished(self) -> None:
        bus = EventBus()
        errors: list[Event] = []
        healthy: list[Event] = []

        def broken(event: Event) -> None:
            raise RuntimeError("boom")

        bus.subscribe("test.x", broken)
        bus.subscribe("test.x", healthy.append)
        bus.subscribe("bus.handler.error", errors.append)
        await bus.start()
        await bus.publish(Event(topic="test.x", source="t"))
        await bus.drain()
        self.assertEqual(len(healthy), 1)  # l'altro handler è stato servito
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].payload["error_type"], "RuntimeError")
        await bus.stop()

    async def test_correlation_chain(self) -> None:
        parent = Event(topic="request.received", source="t")
        child = parent.child("plan.created", {}, source="planner")
        self.assertEqual(child.correlation_id, parent.event_id)
        grandchild = child.child("step.done", {}, source="broker")
        self.assertEqual(grandchild.correlation_id, parent.event_id)


if __name__ == "__main__":
    unittest.main()
