"""Export serialisers: plain text, SRT, WebVTT, and raw JSON."""

from __future__ import annotations

import json
from typing import Any

from .engines.base import Segment

_UNSET = object()

EXTENSIONS = {"txt": "txt", "srt": "srt", "vtt": "vtt", "json": "json"}
MEDIA_TYPES = {
    "txt": "text/plain; charset=utf-8",
    "srt": "application/x-subrip; charset=utf-8",
    "vtt": "text/vtt; charset=utf-8",
    "json": "application/json; charset=utf-8",
}


def _clock(seconds: float, millis_separator: str) -> str:
    seconds = max(0.0, seconds)
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis == 1000:  # rounding can tip a whole second
        millis, secs = 0, secs + 1
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{millis_separator}{millis:03d}"


def to_text(segments: list[Segment], fallback: str = "") -> str:
    """Speaker-prefixed when diarized, otherwise flowing paragraphs."""
    if not segments:
        return fallback

    if any(s.speaker for s in segments):
        lines: list[str] = []
        current: object = _UNSET  # sentinel: distinct from any real label
        for segment in segments:
            if segment.speaker != current:
                current = segment.speaker
                lines.append(f"\n{segment.speaker or 'Unknown'}: {segment.text}")
            else:
                lines[-1] += f" {segment.text}"
        return "\n".join(line.strip() for line in lines).strip()

    return " ".join(s.text.strip() for s in segments if s.text.strip()).strip() or fallback


def to_srt(segments: list[Segment]) -> str:
    blocks = []
    for index, segment in enumerate(segments, start=1):
        text = f"{segment.speaker}: {segment.text}" if segment.speaker else segment.text
        blocks.append(
            f"{index}\n"
            f"{_clock(segment.start, ',')} --> {_clock(segment.end, ',')}\n"
            f"{text.strip()}\n"
        )
    return "\n".join(blocks)


def to_vtt(segments: list[Segment]) -> str:
    blocks = ["WEBVTT\n"]
    for segment in segments:
        text = f"<v {segment.speaker}>{segment.text}" if segment.speaker else segment.text
        blocks.append(
            f"{_clock(segment.start, '.')} --> {_clock(segment.end, '.')}\n{text.strip()}\n"
        )
    return "\n".join(blocks)


def to_json(record: dict[str, Any]) -> str:
    return json.dumps(record, indent=2, ensure_ascii=False)


def render(fmt: str, segments: list[Segment], text: str, record: dict[str, Any]) -> str:
    if fmt == "srt":
        return to_srt(segments)
    if fmt == "vtt":
        return to_vtt(segments)
    if fmt == "json":
        return to_json(record)
    return text or to_text(segments)
