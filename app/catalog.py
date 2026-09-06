"""Curated metadata for the models we can actually make claims about.

Anything else returned by /v1/models is surfaced without invented pricing.
Figures come from https://console.groq.com/docs/speech-to-text and the Groq
models page, verified 2026-09-06.
"""

from __future__ import annotations

from typing import Any

CURATED: dict[str, dict[str, Any]] = {
    "whisper-large-v3": {
        "label": "Whisper Large v3",
        "provider": "groq",
        "price_per_hour": 0.111,
        "wer": "10.3%",
        "speed": "189x realtime",
        "languages": "99 (multilingual)",
        "diarization": False,
        "best_for": "Highest accuracy. Reach for it with accents, background "
                    "noise, poor microphones, or non-English audio.",
    },
    "whisper-large-v3-turbo": {
        "label": "Whisper Large v3 Turbo",
        "provider": "groq",
        "price_per_hour": 0.040,
        "wer": "12%",
        "speed": "216x realtime",
        "languages": "99 (multilingual)",
        "diarization": False,
        "recommended": True,
        "best_for": "The default. Nearly as accurate as v3 at under half the "
                    "price, and fast enough that dictation feels instant.",
    },
    "distil-whisper-large-v3-en": {
        "label": "Distil-Whisper Large v3 (English)",
        "provider": "groq",
        "price_per_hour": None,
        "wer": None,
        "speed": "fastest",
        "languages": "English only",
        "diarization": False,
        "best_for": "English-only bulk work where speed matters more than the "
                    "last point of accuracy.",
    },
    "scribe_v2": {
        "label": "ElevenLabs Scribe v2",
        "provider": "elevenlabs",
        "price_per_hour": 0.220,
        "wer": None,
        "speed": "batch",
        "languages": "99",
        "diarization": True,
        "best_for": "The only option here with true voice-based speaker "
                    "separation. Also skips chunking — it accepts files up to 5 GB.",
    },
}

# Models the transcription UI should offer even when /v1/models is unreachable.
GROQ_FALLBACK_IDS = ["whisper-large-v3-turbo", "whisper-large-v3"]


def is_audio_model(model_id: str) -> bool:
    lowered = model_id.lower()
    return "whisper" in lowered


def describe(model_id: str, provider: str = "groq") -> dict[str, Any]:
    """Curated entry when we have one, otherwise a claim-free stub."""
    entry = CURATED.get(model_id)
    if entry:
        return {"id": model_id, **entry}
    return {
        "id": model_id,
        "label": model_id,
        "provider": provider,
        "price_per_hour": None,
        "wer": None,
        "speed": None,
        "languages": None,
        "diarization": False,
        "best_for": None,
    }
