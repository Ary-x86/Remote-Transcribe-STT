"""Job registry and the transcription pipeline itself.

Jobs run as asyncio tasks in-process. The frontend polls GET /api/jobs/{id}
for stage and chunk progress, so a long recording shows "chunk 3 of 7"
instead of an indefinite spinner.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import audio as audio_utils
from .config import Settings
from .engines.base import EngineError, Transcript, TranscribeOptions
from .engines.elevenlabs import ElevenLabsEngine
from .engines.groq import GroqEngine
from .formats import to_text
from .postprocess import label_speakers, run_cleanup
from .store import Store

# Finished jobs linger this long so a slow poll still collects the result.
JOB_RETENTION_SECONDS = 3600

STAGE_LABELS = {
    "queued": "Queued",
    "preparing": "Reading the audio",
    "converting": "Converting to 16 kHz mono",
    "splitting": "Splitting on silence",
    "transcribing": "Transcribing",
    "diarizing": "Estimating speakers",
    "cleaning": "Cleaning up the text",
    "saving": "Saving",
    "done": "Done",
    "error": "Failed",
}


@dataclass
class Job:
    id: str
    stage: str = "queued"
    chunks_done: int = 0
    chunks_total: int = 0
    created_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "stage": self.stage,
            "stage_label": STAGE_LABELS.get(self.stage, self.stage),
            "chunks_done": self.chunks_done,
            "chunks_total": self.chunks_total,
            "done": self.stage in ("done", "error"),
            "result": self.result,
            "error": self.error,
        }


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def create(self) -> Job:
        self._prune()
        job = Job(id=uuid.uuid4().hex)
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def spawn(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _prune(self) -> None:
        now = time.monotonic()
        for job_id, job in list(self._jobs.items()):
            if job.finished_at and now - job.finished_at > JOB_RETENTION_SECONDS:
                del self._jobs[job_id]


@dataclass
class PipelineRequest:
    source_path: Path
    original_name: str
    engine_name: str
    options: TranscribeOptions
    diarization_mode: str      # "off" | "llm" | "acoustic"
    cleanup_preset: str
    expected_speakers: int | None


async def _transcribe_chunks(
    engine: GroqEngine,
    flac_path: Path,
    duration: float,
    settings: Settings,
    options: TranscribeOptions,
    job: Job,
    workdir: Path,
) -> tuple[str, list[Any], str | None, list[str]]:
    """Split when the file is over the upload cap, transcribe, and stitch."""
    size = flac_path.stat().st_size
    warnings: list[str] = []

    if size <= settings.max_upload_bytes:
        job.stage = "transcribing"
        job.chunks_total = 1
        transcript = await engine.transcribe(flac_path, options)
        job.chunks_done = 1
        return transcript.text, transcript.segments, transcript.language, warnings

    job.stage = "splitting"
    target = audio_utils.target_seconds_for_size(
        duration, size, settings.max_upload_bytes, float(settings.chunk_target_seconds)
    )
    silences = await audio_utils.detect_silences(flac_path)
    chunks = audio_utils.plan_chunks(
        duration, silences, target, settings.chunk_overlap_seconds
    )

    for chunk in chunks:
        chunk.path = workdir / f"chunk_{chunk.index:03d}.flac"
        await audio_utils.cut_chunk(flac_path, chunk, chunk.path)

    job.stage = "transcribing"
    job.chunks_total = len(chunks)
    semaphore = asyncio.Semaphore(settings.max_concurrent_chunks)
    lock = asyncio.Lock()

    async def run_one(chunk: audio_utils.Chunk) -> tuple[Any, Transcript | None, str | None]:
        async with semaphore:
            try:
                transcript = await engine.transcribe(chunk.path, options)
            except EngineError as exc:
                return chunk, None, str(exc)
            finally:
                async with lock:
                    job.chunks_done += 1
            return chunk, transcript, None

    outcomes = await asyncio.gather(*(run_one(chunk) for chunk in chunks))

    succeeded = [(chunk, t) for chunk, t, _ in outcomes if t is not None]
    for chunk, _, error in outcomes:
        if error:
            warnings.append(
                f"Minute {int(chunk.start // 60)}–{int(chunk.end // 60)} could not be "
                f"transcribed and is missing from the text: {error}"
            )

    if not succeeded:
        raise EngineError("Every chunk failed to transcribe. " + (warnings[0] if warnings else ""))

    text, segments = audio_utils.stitch(succeeded)
    # Chunks are the same recording, so the first detection speaks for all.
    detected = next((t.language for _, t in succeeded if t.language), None)
    return text, segments, detected, warnings


async def run_pipeline(
    job: Job,
    request: PipelineRequest,
    settings: Settings,
    store: Store,
) -> None:
    """Full path: probe, normalise, transcribe, label, clean, persist."""
    workdir = Path(tempfile.mkdtemp(prefix="remote-transcribe-"))
    warnings: list[str] = []

    try:
        job.stage = "preparing"
        info = await audio_utils.probe(request.source_path)
        duration = float(info["duration"])

        job.stage = "converting"
        flac_path = workdir / "audio.flac"
        await audio_utils.to_flac(request.source_path, flac_path)
        if duration <= 0:
            duration = float((await audio_utils.probe(flac_path))["duration"])

        if request.engine_name == "elevenlabs":
            engine = ElevenLabsEngine(settings.elevenlabs_api_key)
            job.stage = "transcribing"
            job.chunks_total = 1
            transcript = await engine.transcribe(flac_path, request.options)
            job.chunks_done = 1
            text, segments = transcript.text, transcript.segments
            language = transcript.language
            engine_name, model_name = engine.name, transcript.model
        else:
            engine = GroqEngine(settings.groq_api_key, settings.max_upload_bytes)
            text, segments, detected, chunk_warnings = await _transcribe_chunks(
                engine, flac_path, duration, settings, request.options, job, workdir
            )
            warnings.extend(chunk_warnings)
            language = detected or request.options.language
            engine_name, model_name = engine.name, request.options.model

        if not text.strip() and not segments:
            raise EngineError(
                "No speech was found in that audio. Check that the recording "
                "actually captured sound."
            )

        if request.diarization_mode == "llm":
            job.stage = "diarizing"
            groq = GroqEngine(settings.groq_api_key, settings.max_upload_bytes)
            diarized = await label_speakers(
                groq, segments, settings.llm_model, request.expected_speakers
            )
            segments = diarized.segments
            warnings.extend(diarized.warnings)

        raw_text = to_text(segments, fallback=text)

        clean_text: str | None = None
        if request.cleanup_preset and request.cleanup_preset != "raw":
            job.stage = "cleaning"
            groq = GroqEngine(settings.groq_api_key, settings.max_upload_bytes)
            clean_text, cleanup_warnings = await run_cleanup(
                groq, raw_text, request.cleanup_preset, settings.llm_model
            )
            warnings.extend(cleanup_warnings)
            if clean_text == raw_text:
                clean_text = None

        job.stage = "saving"
        audio_bytes = flac_path.read_bytes() if settings.keep_audio else None
        record_id = store.save(
            raw_text=raw_text,
            clean_text=clean_text,
            cleanup_preset=request.cleanup_preset,
            segments=segments,
            engine=engine_name,
            model=model_name,
            task=request.options.task,
            language=language,
            duration=duration,
            warnings=warnings,
            options={
                "source": request.original_name,
                "diarization": request.diarization_mode,
                "expected_speakers": request.expected_speakers,
                "prompt": request.options.prompt,
                "temperature": request.options.temperature,
            },
            audio_bytes=audio_bytes,
        )

        record = store.get(record_id)
        job.result = record
        job.stage = "done"

    except (EngineError, audio_utils.AudioError) as exc:
        job.error = str(exc)
        job.stage = "error"
    except Exception as exc:  # noqa: BLE001 - surface anything else as a job failure
        job.error = f"Unexpected failure: {exc.__class__.__name__}: {exc}"
        job.stage = "error"
    finally:
        job.finished_at = time.monotonic()
        _cleanup_dir(workdir)
        request.source_path.unlink(missing_ok=True)


def _cleanup_dir(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
