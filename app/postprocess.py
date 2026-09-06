"""LLM passes that run after transcription: speaker labelling and cleanup.

Both go through Groq's chat API with the same key as transcription, so
neither needs extra setup.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .engines.base import EngineError, Segment
from .engines.groq import GroqEngine

# Segments per labelling call. Large enough to give the model real context,
# small enough to stay well inside the output token budget.
BATCH_SIZE = 120
# Segments from the previous batch replayed as context so labels stay stable
# across a batch boundary.
CONTEXT_TAIL = 8

DIARIZE_SYSTEM = """\
You assign speaker labels to a transcript.

You receive numbered transcript segments as JSON. Decide which speaker said \
each one, using conversational cues: question-and-answer structure, changes \
in topic or point of view, greetings, interruptions, and self-reference.

Rules:
- Number speakers from 1. Reuse the same number for the same person throughout.
- Consecutive segments are usually the same speaker. Only switch when there is \
a real cue for it.
- Some segments in the CONTEXT list are already labelled. Keep those labels \
consistent; do not renumber anyone.
- Return every index you were asked about, and nothing else.

Reply with only this JSON object:
{"assignments": [{"i": <segment index>, "speaker": <speaker number>}]}"""

CLEANUP_PRESETS: dict[str, dict[str, str]] = {
    "raw": {
        "label": "Raw",
        "description": "Exactly what Whisper heard. No second pass, no cost.",
        "system": "",
    },
    "clean": {
        "label": "Clean up",
        "description": "Drops filler words and false starts, fixes punctuation "
                       "and paragraph breaks. Keeps your wording.",
        "system": """\
You tidy up dictated speech into readable text.

Remove filler words (um, uh, like, you know), stutters, and false starts. Fix \
punctuation, capitalisation, and paragraph breaks. Repair obvious \
transcription slips where the intended word is unambiguous.

Do not summarise, reorder, rephrase for style, or add anything that was not \
said. The speaker's own wording and meaning must survive intact.

Reply with the cleaned text and nothing else.""",
    },
    "prompt": {
        "label": "Format as prompt",
        "description": "Turns rambling dictation into a structured, well-organised "
                       "prompt. Keeps every requirement.",
        "system": """\
You turn spoken, rambling dictation into a clear written prompt for an AI \
assistant.

Remove filler and repetition. Organise the request logically, using headings \
or bullet points where they genuinely help. Make implied structure explicit.

Preserve every requirement, constraint, question, and detail the speaker \
mentioned — including asides, since dictation often buries important points \
mid-sentence. Never invent requirements and never answer the prompt yourself.

Reply with the reformatted prompt and nothing else.""",
    },
    "notes": {
        "label": "Summary notes",
        "description": "Condenses the transcript into bulleted key points and "
                       "any action items.",
        "system": """\
You condense a transcript into notes.

Produce a short paragraph of context, then bulleted key points. If the \
transcript contains decisions, action items, or open questions, list them \
under their own headings.

Stick to what was actually said. Reply with the notes and nothing else.""",
    },
}


@dataclass
class DiarizationResult:
    segments: list[Segment]
    speaker_count: int
    warnings: list[str]


def _batches(segments: list[Segment]) -> list[tuple[int, list[Segment]]]:
    return [
        (start, segments[start : start + BATCH_SIZE])
        for start in range(0, len(segments), BATCH_SIZE)
    ]


async def label_speakers(
    engine: GroqEngine,
    segments: list[Segment],
    model: str,
    expected_speakers: int | None = None,
) -> DiarizationResult:
    """Estimate who said what from the transcript text.

    This reads words, not voices — Groq exposes no acoustic diarization. It
    holds up on clean turn-taking and degrades on crosstalk, so the result is
    always presented to the user as an estimate.
    """
    labelled = [Segment(s.start, s.end, s.text, s.speaker, s.words) for s in segments]
    if not labelled:
        return DiarizationResult(labelled, 0, [])

    warnings: list[str] = []
    assignments: dict[int, int] = {}

    for offset, batch in _batches(labelled):
        context = [
            {"i": offset - CONTEXT_TAIL + n, "speaker": assignments.get(offset - CONTEXT_TAIL + n),
             "text": labelled[offset - CONTEXT_TAIL + n].text}
            for n in range(CONTEXT_TAIL)
            if 0 <= offset - CONTEXT_TAIL + n < offset
        ]
        payload: dict[str, Any] = {
            "segments": [
                {"i": offset + n, "start": round(s.start, 2), "text": s.text}
                for n, s in enumerate(batch)
            ]
        }
        if context:
            payload["context_already_labelled"] = context
        if expected_speakers:
            payload["expected_speaker_count"] = expected_speakers

        try:
            reply = await engine.chat_json(
                DIARIZE_SYSTEM, json.dumps(payload, ensure_ascii=False), model
            )
        except EngineError as exc:
            warnings.append(f"Speaker labelling failed for part of the transcript: {exc}")
            continue

        for item in reply.get("assignments") or []:
            try:
                index = int(item["i"])
                speaker = int(item["speaker"])
            except (KeyError, TypeError, ValueError):
                continue
            if offset <= index < offset + len(batch) and speaker >= 1:
                assignments[index] = speaker

    if not assignments:
        warnings.append(
            "Could not estimate speakers for this recording. The transcript itself is unaffected."
        )
        return DiarizationResult(labelled, 0, warnings)

    # Renumber so labels read 1..N in order of first appearance.
    order: dict[int, int] = {}
    for index in sorted(assignments):
        speaker = assignments[index]
        if speaker not in order:
            order[speaker] = len(order) + 1

    unresolved = 0
    last_speaker = "Speaker 1"
    for index, segment in enumerate(labelled):
        if index in assignments:
            last_speaker = f"Speaker {order[assignments[index]]}"
        else:
            unresolved += 1
        # An unlabelled segment inherits the previous speaker, which is the
        # right guess far more often than not.
        segment.speaker = last_speaker

    if unresolved:
        warnings.append(
            f"{unresolved} of {len(labelled)} segments had no speaker returned "
            "and were attributed to whoever was speaking before them."
        )

    return DiarizationResult(labelled, len(order), warnings)


async def run_cleanup(
    engine: GroqEngine, text: str, preset: str, model: str
) -> tuple[str, list[str]]:
    """Apply a cleanup preset. Returns the text unchanged for 'raw'."""
    config = CLEANUP_PRESETS.get(preset)
    if not config or not config["system"] or not text.strip():
        return text, []

    try:
        cleaned = await engine.chat(config["system"], text, model, max_tokens=32768)
    except EngineError as exc:
        return text, [f"Cleanup ({config['label']}) failed, showing the raw transcript: {exc}"]

    if not cleaned.strip():
        return text, [f"Cleanup ({config['label']}) came back empty, showing the raw transcript."]
    return cleaned, []


def preset_options() -> list[dict[str, str]]:
    return [
        {"id": key, "label": value["label"], "description": value["description"]}
        for key, value in CLEANUP_PRESETS.items()
    ]
