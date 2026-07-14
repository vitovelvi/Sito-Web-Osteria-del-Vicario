"""Voice System di JARVIS: pipeline vocale modulare."""

from jarvis.voice.pipeline import (
    ConsoleSpeechToText,
    ConsoleTextToSpeech,
    IntentDetector,
    KeywordIntentDetector,
    NullVoiceActivityDetector,
    NullWakeWordDetector,
    SpeechToText,
    TextToSpeech,
    VoiceActivityDetector,
    VoicePipeline,
    WakeWordDetector,
    build_voice_pipeline,
)

__all__ = [
    "WakeWordDetector", "VoiceActivityDetector", "SpeechToText",
    "IntentDetector", "TextToSpeech", "VoicePipeline",
    "NullWakeWordDetector", "NullVoiceActivityDetector",
    "ConsoleSpeechToText", "KeywordIntentDetector", "ConsoleTextToSpeech",
    "build_voice_pipeline",
]
