"""Shared transcript shape that every engine normalises into."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Protocol


@dataclass
class Word:
    start: float
    end: float
    text: str
    speaker: str | None = None


@dataclass
class Segment:
    start: float
    end: float
    text: str
    speaker: str | None = None
    words: list[Word] = field(default_factory=list)


@dataclass
class Transcript:
    text: str
    segments: list[Segment] = field(default_factory=list)
    language: str | None = None
    duration: float = 0.0
    engine: str = ""
    model: str = ""
    # Non-fatal problems worth showing the user (a chunk that failed, a
    # provider quirk, a truncated prompt...).
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def has_speakers(self) -> bool:
        return any(seg.speaker for seg in self.segments)


@dataclass
class TranscribeOptions:
    model: str
    task: str = "transcribe"          # "transcribe" | "translate"
    language: str | None = None       # ISO-639-1, None = auto-detect
    prompt: str | None = None         # vocabulary / style hint, 224 tokens max
    temperature: float = 0.0
    diarize: bool = False             # only meaningful for engines that support it
    num_speakers: int | None = None


class Engine(Protocol):
    name: str
    supports_diarization: bool
    max_upload_bytes: int

    async def transcribe(
        self, audio_path: str, options: TranscribeOptions
    ) -> Transcript: ...


class EngineError(RuntimeError):
    """A provider call failed in a way the user should see."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status
