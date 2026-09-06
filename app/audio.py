"""ffmpeg-backed audio handling: probe, normalise, split, stitch.

Groq's upload cap is 25 MB on the free tier. Their recommended 16 kHz mono
FLAC encoding still runs roughly 60 MB per hour of speech, so anything past
~25 minutes has to be split. We cut at natural silences so a boundary rarely
lands mid-word, and overlap each cut so Whisper never starts cold on a
half-spoken syllable.
"""

from __future__ import annotations

import asyncio
import math
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from .engines.base import Segment, Transcript, Word

# Anything quieter than this for at least this long counts as a gap we may
# cut on. -30 dB is forgiving enough to find gaps in a noisy room recording.
SILENCE_NOISE_DB = "-30dB"
SILENCE_MIN_DURATION = 0.5

_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(-?[\d.]+)")


class AudioError(RuntimeError):
    pass


async def _run(*args: str) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return (
        proc.returncode or 0,
        stdout.decode("utf-8", "replace"),
        stderr.decode("utf-8", "replace"),
    )


def _tail(stderr: str, lines: int = 3) -> str:
    return " / ".join(stderr.strip().splitlines()[-lines:]) or "no output"


async def probe(path: str | Path) -> dict[str, float | str | bool]:
    """Duration and whether there is an audio stream at all."""
    code, out, err = await _run(
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name:format=duration",
        "-of", "default=noprint_wrappers=1:nokey=0",
        str(path),
    )
    if code != 0:
        raise AudioError(f"Could not read that file as media: {_tail(err)}")

    info: dict[str, str] = {}
    for line in out.splitlines():
        key, _, value = line.partition("=")
        info[key.strip()] = value.strip()

    codec = info.get("codec_name", "")
    if not codec:
        raise AudioError(
            "That file has no audio stream. Upload an audio or video file "
            "that actually contains sound."
        )
    try:
        duration = float(info.get("duration", "0") or 0)
    except ValueError:
        duration = 0.0

    return {"codec": codec, "duration": duration, "has_audio": True}


async def to_flac(src: str | Path, dst: str | Path) -> Path:
    """Groq's recommended preprocessing: 16 kHz mono FLAC.

    Also the single biggest lever on upload size, which is what decides
    whether we have to chunk at all.
    """
    code, _, err = await _run(
        "ffmpeg", "-nostdin", "-y", "-i", str(src),
        "-ar", "16000", "-ac", "1", "-map", "0:a", "-c:a", "flac",
        str(dst),
    )
    if code != 0:
        raise AudioError(f"Audio conversion failed: {_tail(err)}")
    return Path(dst)


async def detect_silences(path: str | Path) -> list[tuple[float, float]]:
    """Silent [start, end] windows, via ffmpeg's silencedetect filter."""
    _, _, err = await _run(
        "ffmpeg", "-nostdin", "-i", str(path),
        "-af", f"silencedetect=noise={SILENCE_NOISE_DB}:d={SILENCE_MIN_DURATION}",
        "-f", "null", "-",
    )
    silences: list[tuple[float, float]] = []
    pending: float | None = None
    for line in err.splitlines():
        start_match = _SILENCE_START_RE.search(line)
        if start_match:
            pending = float(start_match.group(1))
            continue
        end_match = _SILENCE_END_RE.search(line)
        if end_match and pending is not None:
            end = float(end_match.group(1))
            if end > pending:
                silences.append((max(0.0, pending), end))
            pending = None
    return silences


@dataclass
class Chunk:
    index: int
    # Logical span this chunk owns. Segments are kept only if their midpoint
    # falls in here, which is what makes overlap de-duplication exact.
    start: float
    end: float
    # What we actually hand to the API, padded by the overlap on both sides.
    cut_start: float
    cut_end: float
    path: Path | None = None

    @property
    def cut_duration(self) -> float:
        return self.cut_end - self.cut_start


def plan_chunks(
    duration: float,
    silences: list[tuple[float, float]],
    target_seconds: float,
    overlap: float,
) -> list[Chunk]:
    """Split [0, duration] into spans of about target_seconds, nudging each
    boundary onto the longest nearby silence."""
    if duration <= target_seconds:
        return [Chunk(0, 0.0, duration, 0.0, duration)]

    # Aim for evenly sized pieces rather than a long tail plus a stub.
    count = max(2, math.ceil(duration / target_seconds))
    stride = duration / count
    # How far from the ideal boundary we will wander to find a silence.
    window = min(stride / 3.0, 120.0)

    boundaries: list[float] = []
    previous = 0.0
    for i in range(1, count):
        ideal = stride * i
        candidates = [
            (silence_end - silence_start, (silence_start + silence_end) / 2.0)
            for silence_start, silence_end in silences
            if abs((silence_start + silence_end) / 2.0 - ideal) <= window
        ]
        # Longest silence in the window wins; ties break toward the ideal point.
        chosen = max(candidates, key=lambda c: c[0])[1] if candidates else ideal
        # Never emit a zero-length or backwards span.
        if chosen <= previous + 1.0:
            chosen = ideal
        if chosen <= previous + 1.0:
            continue
        boundaries.append(chosen)
        previous = chosen

    edges = [0.0, *boundaries, duration]
    chunks: list[Chunk] = []
    for i in range(len(edges) - 1):
        start, end = edges[i], edges[i + 1]
        chunks.append(
            Chunk(
                index=i,
                start=start,
                end=end,
                cut_start=max(0.0, start - overlap),
                cut_end=min(duration, end + overlap),
            )
        )
    return chunks


async def cut_chunk(src: str | Path, chunk: Chunk, dst: str | Path) -> Path:
    """Extract one chunk. -ss before -i seeks fast; -t after -i bounds the
    output, which is the combination that stays accurate."""
    code, _, err = await _run(
        "ffmpeg", "-nostdin", "-y",
        "-ss", f"{chunk.cut_start:.3f}",
        "-i", str(src),
        "-t", f"{chunk.cut_duration:.3f}",
        "-ar", "16000", "-ac", "1", "-c:a", "flac",
        str(dst),
    )
    if code != 0:
        raise AudioError(f"Could not split the audio: {_tail(err)}")
    return Path(dst)


def target_seconds_for_size(
    duration: float, size_bytes: int, max_bytes: int, ceiling_seconds: float
) -> float:
    """Longest chunk that still fits the upload cap, capped by the configured
    ceiling. Uses the file's own bitrate rather than a guess."""
    if duration <= 0 or size_bytes <= 0:
        return ceiling_seconds
    bytes_per_second = size_bytes / duration
    # 0.9 leaves headroom for FLAC's per-chunk overhead and bitrate variance.
    fits = (max_bytes * 0.9) / bytes_per_second
    return max(30.0, min(ceiling_seconds, fits))


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def _same_utterance(a: str, b: str) -> bool:
    """Whether two chunk-edge transcriptions are the same speech.

    They rarely match character for character — the two chunks give Whisper
    different context, so it re-punctuates and sometimes truncates at the cut.
    """
    left, right = _normalise(a), _normalise(b)
    if not left or not right:
        return False
    if left == right or left in right or right in left:
        return True
    return SequenceMatcher(None, left, right).ratio() >= 0.75


def stitch(results: list[tuple[Chunk, Transcript]]) -> tuple[str, list[Segment]]:
    """Merge per-chunk transcripts back into one timeline.

    Chunks overlap so Whisper never starts cold mid-word, which means the
    speech in an overlap gets transcribed twice, with different timestamps
    each time. Partitioning purely on time is therefore unsafe: an utterance
    straddling the boundary can be re-timed to land outside both chunks and
    vanish. So we merge sequentially and drop a segment only when the text we
    already have covers it — dropping nothing we have not already kept.
    """
    ordered = sorted(results, key=lambda r: r[0].index)
    merged: list[Segment] = []
    source_chunk: list[int] = []

    for chunk, transcript in ordered:
        offset = chunk.cut_start
        for segment in transcript.segments:
            if not segment.text.strip():
                continue

            shifted = Segment(
                start=segment.start + offset,
                end=segment.end + offset,
                text=segment.text.strip(),
                speaker=segment.speaker,
                words=[
                    Word(w.start + offset, w.end + offset, w.text, w.speaker)
                    for w in segment.words
                ],
            )

            # Only the boundary between two different chunks needs reconciling.
            if merged and source_chunk[-1] != chunk.index:
                previous = merged[-1]
                if shifted.start < previous.end and _same_utterance(shifted.text, previous.text):
                    # Same speech twice. The copy at a chunk edge is usually
                    # the truncated one, so keep whichever says more.
                    if len(shifted.text) > len(previous.text):
                        merged[-1] = shifted
                        source_chunk[-1] = chunk.index
                    continue
                if shifted.end <= previous.end + 0.01:
                    continue  # this span is already covered

            merged.append(shifted)
            source_chunk.append(chunk.index)

    merged.sort(key=lambda s: s.start)
    text = " ".join(s.text for s in merged if s.text)
    return re.sub(r"\s{2,}", " ", text).strip(), merged
