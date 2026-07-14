"""Test del Security Layer."""

import unittest

from jarvis.core.identity import AutonomyLevel, CoreIdentity
from jarvis.events import EventBus
from jarvis.security import ConfirmationGate, OperationClassifier, SecurityLevel


class ClassifierTest(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = OperationClassifier({
            "fs.read": SecurityLevel.READ_ONLY,
            "fs.write": SecurityLevel.REVERSIBLE,
        })

    def test_base_levels(self) -> None:
        self.assertEqual(self.classifier.classify("fs.read", {}).level,
                         SecurityLevel.READ_ONLY)
        self.assertEqual(self.classifier.classify("fs.write", {}).level,
                         SecurityLevel.REVERSIBLE)

    def test_unknown_action_is_irreversible(self) -> None:
        op = self.classifier.classify("azione.ignota", {})
        self.assertEqual(op.level, SecurityLevel.IRREVERSIBLE)

    def test_destructive_params_escalate(self) -> None:
        op = self.classifier.classify("fs.read", {"cmd": "rm -rf /"})
        self.assertEqual(op.level, SecurityLevel.IRREVERSIBLE)


class GateTest(unittest.IsolatedAsyncioTestCase):
    def _gate(self, confirmer=None) -> tuple[ConfirmationGate, EventBus]:
        identity = CoreIdentity(autonomy=AutonomyLevel.SUPERVISED)
        bus = EventBus()
        gate = ConfirmationGate(identity, bus, confirmation_from_level=2,
                                auto_deny_when_unattended=True,
                                confirmer=confirmer)
        return gate, bus

    async def test_low_levels_pass_automatically(self) -> None:
        gate, bus = self._gate()
        await bus.start()
        classifier = OperationClassifier({"fs.read": SecurityLevel.READ_ONLY})
        op = classifier.classify("fs.read", {})
        self.assertTrue(await gate.authorize(op))
        await bus.drain()
        await bus.stop()

    async def test_high_level_denied_when_unattended(self) -> None:
        gate, bus = self._gate()
        await bus.start()
        classifier = OperationClassifier({"deploy": SecurityLevel.IRREVERSIBLE})
        op = classifier.classify("deploy", {})
        self.assertFalse(await gate.authorize(op))
        await bus.drain()
        await bus.stop()

    async def test_high_level_granted_with_confirmation(self) -> None:
        async def yes(description: str, level: SecurityLevel) -> bool:
            return True

        gate, bus = self._gate(confirmer=yes)
        await bus.start()
        classifier = OperationClassifier({"deploy": SecurityLevel.SIGNIFICANT})
        op = classifier.classify("deploy", {})
        self.assertTrue(await gate.authorize(op))
        await bus.drain()
        await bus.stop()


if __name__ == "__main__":
    unittest.main()
