"""ElevenLabs Scribe v2 — the real-diarization path.

Groq cannot separate speakers at all, so when someone needs actual
voice-based attribution (rather than an LLM's guess from the text) this is
the engine that does it. It also accepts files up to 5 GB, which means no
chunking is needed on this path.
"""

from __future__ import annotations

import asyncio
import random
from pathlib import Path
from typing import Any

import httpx

from .base import EngineError, Segment, Transcript, TranscribeOptions, Word

BASE_URL = "https://api.elevenlabs.io/v1"
MODEL_ID = "scribe_v2"
MAX_ATTEMPTS = 3
# Start a new segment when the same speaker pauses this long.
TURN_GAP_SECONDS = 1.2


def _group_into_turns(words: list[Word]) -> list[Segment]:
    """Collapse the flat word stream into speaker turns."""
    segments: list[Segment] = []
    current: list[Word] = []

    def flush() -> None:
        if not current:
            return
        segments.append(
            Segment(
                start=current[0].start,
                end=current[-1].end,
                text="".join(w.text for w in current).strip(),
                speaker=current[0].speaker,
                words=[w for w in current if w.text.strip()],
            )
        )
        current.clear()

    for word in words:
        if current:
            changed_speaker = word.speaker != current[0].speaker
            long_pause = word.start - current[-1].end > TURN_GAP_SECONDS
            if changed_speaker or long_pause:
                flush()
        current.append(word)
    flush()
    return [s for s in segments if s.text]


def _normalise_speaker(raw: Any, mapping: dict[str, str]) -> str | None:
    """ElevenLabs ids look like "speaker_0"; show them as "Speaker 1"."""
    if raw is None:
        return None
    key = str(raw)
    if key not in mapping:
        mapping[key] = f"Speaker {len(mapping) + 1}"
    return mapping[key]


class ElevenLabsEngine:
    name = "elevenlabs"
    supports_diarization = True
    # 5 GB per the API docs; we never approach it, so no chunking here.
    max_upload_bytes = 5 * 1024 * 1024 * 1024

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise EngineError(
                "No ElevenLabs API key configured. Add ELEVENLABS_API_KEY to "
                "your .env file to enable acoustic diarization, or switch the "
                "Speakers setting back to the LLM estimate."
            )
        self.api_key = api_key

    async def transcribe(self, audio_path: str | Path, options: TranscribeOptions) -> Transcript:
        if options.task == "translate":
            raise EngineError(
                "Translate-to-English is a Groq Whisper feature. Switch the "
                "engine to Groq for that, or transcribe here and use the "
                "cleanup step to translate."
            )

        path = Path(audio_path)
        data: dict[str, str] = {
            "model_id": MODEL_ID,
            "timestamps_granularity": "word",
            "diarize": "true" if options.diarize else "false",
            "tag_audio_events": "false",
        }
        if options.language:
            data["language_code"] = options.language
        if options.diarize and options.num_speakers:
            data["num_speakers"] = str(options.num_speakers)

        files = {"file": (path.name, path.read_bytes(), "audio/flac")}
        headers = {"xi-api-key": self.api_key}

        last_error = ""
        for attempt in range(MAX_ATTEMPTS):
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=15.0)) as client:
                    response = await client.post(
                        f"{BASE_URL}/speech-to-text",
                        data=data, files=files, headers=headers,
                    )
            except httpx.RequestError as exc:
                last_error = f"could not reach ElevenLabs ({exc.__class__.__name__})"
                if attempt == MAX_ATTEMPTS - 1:
                    raise EngineError(last_error) from exc
                await asyncio.sleep(2**attempt + random.random())
                continue

            if response.status_code < 400:
                return self._to_transcript(response.json(), options)

            message = self._error_message(response)
            retryable = response.status_code == 429 or response.status_code >= 500
            if retryable and attempt < MAX_ATTEMPTS - 1:
                last_error = message
                await asyncio.sleep(2**attempt + random.random())
                continue
            raise EngineError(message, response.status_code)

        raise EngineError(f"ElevenLabs request failed: {last_error}")

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        if response.status_code == 401:
            return "ElevenLabs rejected the API key. Check ELEVENLABS_API_KEY in your .env file."
        try:
            detail = response.json().get("detail")
            message = detail.get("message") if isinstance(detail, dict) else detail
        except (ValueError, AttributeError):
            message = response.text[:300]
        return f"ElevenLabs error {response.status_code}: {message}".strip()

    def _to_transcript(self, payload: dict[str, Any], options: TranscribeOptions) -> Transcript:
        mapping: dict[str, str] = {}
        words = [
            Word(
                start=float(raw.get("start", 0.0)),
                end=float(raw.get("end", 0.0)),
                text=str(raw.get("text", "")),
                speaker=_normalise_speaker(raw.get("speaker_id"), mapping)
                if options.diarize else None,
            )
            for raw in payload.get("words") or []
            if raw.get("type") in (None, "word", "spacing")
        ]

        segments = _group_into_turns(words)
        text = str(payload.get("text", "")).strip()
        if not segments and text:
            segments = [Segment(0.0, 0.0, text)]

        return Transcript(
            text=text or " ".join(s.text for s in segments),
            segments=segments,
            language=payload.get("language_code"),
            duration=max((s.end for s in segments), default=0.0),
            engine=self.name,
            model=MODEL_ID,
        )
