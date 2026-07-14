"""Pipeline vocale modulare.

Flusso:  Wake Word → VAD → STT → Intent → (Planner/LLM via eventi) → TTS

Ogni stadio è un'interfaccia con implementazioni sostituibili; quelle incluse
permettono di esercitare la pipeline senza hardware audio:
    - ``Null*``: stadi passanti (wake word e VAD sempre positivi);
    - ``ConsoleSpeechToText``: legge il "parlato" da stringhe di test/CLI;
    - ``ConsoleTextToSpeech``: "pronuncia" scrivendo su console/log.

Integrazioni reali documentate nelle docstring degli stadi (openWakeWord,
webrtcvad/silero, Whisper, Piper/Coqui TTS).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from jarvis.config import Config
from jarvis.events import Event, EventBus
from jarvis.logging import get_logger

_log = get_logger("voice")


class WakeWordDetector(ABC):
    """Rileva la parola di attivazione in un flusso audio.

    Implementazione reale consigliata: openWakeWord o Porcupine.
    """

    @abstractmethod
    async def detect(self, audio_chunk: bytes) -> bool:
        """Vero se la wake word è presente nel chunk."""


class VoiceActivityDetector(ABC):
    """Distingue parlato da silenzio/rumore.

    Implementazione reale consigliata: webrtcvad o Silero VAD.
    """

    @abstractmethod
    async def is_speech(self, audio_chunk: bytes) -> bool:
        """Vero se il chunk contiene parlato."""


class SpeechToText(ABC):
    """Trascrive audio in testo.

    Implementazione reale consigliata: faster-whisper (locale).
    """

    @abstractmethod
    async def transcribe(self, audio: bytes) -> str:
        """Testo trascritto (stringa vuota se non riconosciuto)."""


class IntentDetector(ABC):
    """Classificazione leggera dell'intento della frase."""

    @abstractmethod
    async def detect(self, text: str) -> str:
        """Etichetta di intento (es. ``command``, ``question``)."""


class TextToSpeech(ABC):
    """Sintetizza testo in voce.

    Implementazione reale consigliata: Piper (locale) o Coqui TTS.
    """

    @abstractmethod
    async def speak(self, text: str) -> None:
        """Pronuncia il testo."""


# --------------------------------------------------------- implementazioni


class NullWakeWordDetector(WakeWordDetector):
    """Sempre attivo: utile per test e per input testuale."""

    async def detect(self, audio_chunk: bytes) -> bool:
        return True


class NullVoiceActivityDetector(VoiceActivityDetector):
    """Considera parlato qualunque chunk non vuoto."""

    async def is_speech(self, audio_chunk: bytes) -> bool:
        return bool(audio_chunk)


class ConsoleSpeechToText(SpeechToText):
    """STT simulato: l'audio è testo UTF-8 (test e modalità console)."""

    async def transcribe(self, audio: bytes) -> str:
        return audio.decode("utf-8", errors="replace").strip()


class KeywordIntentDetector(IntentDetector):
    """Intent detection deterministica a parole chiave."""

    async def detect(self, text: str) -> str:
        lowered = text.lower()
        if any(w in lowered for w in ("?", "cosa", "come", "perché", "quando")):
            return "question"
        if any(w in lowered for w in ("apri", "avvia", "crea", "esegui", "ferma")):
            return "command"
        return "statement"


class ConsoleTextToSpeech(TextToSpeech):
    """TTS su console: stampa ciò che verrebbe pronunciato."""

    async def speak(self, text: str) -> None:
        print(f"🔊 JARVIS: {text}")


# ----------------------------------------------------------------- pipeline


class VoicePipeline:
    """Compone gli stadi vocali e li collega all'Event Bus.

    L'ingresso audio produce ``voice.transcript`` (raccolto dal VoiceAgent);
    la pipeline sottoscrive ``voice.speak`` per la sintesi delle risposte.
    """

    def __init__(
        self,
        bus: EventBus,
        wake_word: WakeWordDetector,
        vad: VoiceActivityDetector,
        stt: SpeechToText,
        intent: IntentDetector,
        tts: TextToSpeech,
    ) -> None:
        self._bus = bus
        self._wake_word = wake_word
        self._vad = vad
        self._stt = stt
        self._intent = intent
        self._tts = tts
        bus.subscribe("voice.speak", self._on_speak)

    async def process_audio(self, audio_chunk: bytes) -> str | None:
        """Fa attraversare la pipeline a un chunk audio.

        Returns:
            La trascrizione se il chunk ha superato wake word e VAD,
            altrimenti ``None``.
        """
        if not await self._wake_word.detect(audio_chunk):
            return None
        if not await self._vad.is_speech(audio_chunk):
            return None
        text = await self._stt.transcribe(audio_chunk)
        if not text:
            return None
        intent = await self._intent.detect(text)
        await self._bus.publish(Event(
            topic="voice.transcript",
            payload={"text": text, "intent": intent},
            source="voice.pipeline",
        ))
        return text

    async def _on_speak(self, event: Event) -> None:
        await self._tts.speak(str(event.payload.get("text", "")))


def build_voice_pipeline(bus: EventBus, config: Config) -> VoicePipeline:
    """Costruisce la pipeline dagli stadi dichiarati in configurazione.

    Ogni stadio ha un registro di implementazioni; per integrarne una nuova
    basta aggiungerla al registro corrispondente.
    """
    stages = config.section("voice.stages")
    wake_words: dict[str, WakeWordDetector] = {"null": NullWakeWordDetector()}
    vads: dict[str, VoiceActivityDetector] = {"null": NullVoiceActivityDetector()}
    stts: dict[str, SpeechToText] = {"console": ConsoleSpeechToText()}
    intents: dict[str, IntentDetector] = {"keyword": KeywordIntentDetector()}
    ttss: dict[str, TextToSpeech] = {"console": ConsoleTextToSpeech()}

    def pick(registry: dict, key: str, default: str):  # type: ignore[type-arg]
        name = str(stages.get(key, default))
        if name not in registry:
            _log.warning("Stadio voce %s=%r non trovato: uso %r", key, name, default)
            name = default
        return registry[name]

    return VoicePipeline(
        bus,
        wake_word=pick(wake_words, "wake_word", "null"),
        vad=pick(vads, "vad", "null"),
        stt=pick(stts, "stt", "console"),
        intent=pick(intents, "intent", "keyword"),
        tts=pick(ttss, "tts", "console"),
    )
