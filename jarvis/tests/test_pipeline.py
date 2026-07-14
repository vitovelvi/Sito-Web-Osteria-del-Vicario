"""Test end-to-end: Kernel completo, richiesta → piano → esecuzione → risposta."""

import unittest

from jarvis.core.kernel import Kernel
from jarvis.execution.validation import ValidationError
from jarvis.planning.plan import PlanStep
from jarvis.voice import (
    ConsoleSpeechToText,
    KeywordIntentDetector,
    NullVoiceActivityDetector,
    NullWakeWordDetector,
    VoicePipeline,
)
from tests.helpers import test_config


class SilentTTS:
    """TTS di test: registra invece di stampare."""

    def __init__(self) -> None:
        self.spoken: list[str] = []

    async def speak(self, text: str) -> None:
        self.spoken.append(text)


class EndToEndTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.kernel = Kernel(test_config())
        await self.kernel.start()

    async def asyncTearDown(self) -> None:
        await self.kernel.stop()

    async def test_system_report_flow(self) -> None:
        response = await self.kernel.submit_and_wait(
            "Fammi un report sullo stato del sistema", timeout=30)
        self.assertTrue(response["success"])
        self.assertIn("Report di sistema", response["text"])
        self.assertIn("CPU", response["text"])
        # Il task è tracciato e completato.
        snapshot = self.kernel.tasks.snapshot()
        self.assertEqual(snapshot["by_state"].get("completed"), 1)

    async def test_memory_flow(self) -> None:
        response = await self.kernel.submit_and_wait(
            "Ricorda che il backup va fatto ogni venerdì", timeout=30)
        self.assertTrue(response["success"])
        hits = self.kernel.memory.semantic.recall(text="venerdì")
        self.assertGreaterEqual(len(hits), 1)

    async def test_llm_fallback_flow(self) -> None:
        # Nessun provider configurato nei test: risponde la modalità euristica.
        response = await self.kernel.submit_and_wait(
            "Raccontami qualcosa di interessante", timeout=30)
        self.assertTrue(response["success"])
        self.assertIn("euristica", response["text"])

    async def test_validator_blocks_shell(self) -> None:
        validator = self.kernel.broker._validator  # noqa: SLF001 - test interno
        with self.assertRaises(ValidationError):
            validator.validate(PlanStep(action="shell", params={"cmd": "ls"}))
        with self.assertRaises(ValidationError):
            validator.validate(PlanStep(action="azione.inventata"))

    async def test_voice_pipeline_to_response(self) -> None:
        tts = SilentTTS()
        pipeline = VoicePipeline(
            self.kernel.bus,
            wake_word=NullWakeWordDetector(),
            vad=NullVoiceActivityDetector(),
            stt=ConsoleSpeechToText(),
            intent=KeywordIntentDetector(),
            tts=tts,  # type: ignore[arg-type]
        )
        text = await pipeline.process_audio("stato del sistema".encode("utf-8"))
        self.assertEqual(text, "stato del sistema")
        await self.kernel.bus.drain()
        self.assertEqual(len(tts.spoken), 1)
        self.assertIn("Report di sistema", tts.spoken[0])


if __name__ == "__main__":
    unittest.main()
