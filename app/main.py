"""Remote Transcribe — a self-hosted speech-to-text front end for Groq Whisper."""

from __future__ import annotations

import json
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import (
    Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, status,
)
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import catalog, formats
from .auth import COOKIE_NAME, SESSION_TTL_SECONDS, is_authenticated, issue_token, password_matches
from .auth import require_auth
from .config import PROJECT_ROOT, Settings, StartupError, check_ffmpeg, get_settings
from .engines.base import EngineError, TranscribeOptions
from .engines.groq import GroqEngine
from .jobs import JobRegistry, PipelineRequest, run_pipeline
from .postprocess import preset_options, run_cleanup
from .store import Store, segments_from_json

STATIC_DIR = PROJECT_ROOT / "static"
DIARIZATION_MODES = {"off", "llm", "acoustic"}
TASKS = {"transcribe", "translate"}

registry = JobRegistry()
_store: Store | None = None


def get_store() -> Store:
    if _store is None:  # pragma: no cover - set during lifespan startup
        raise RuntimeError("Store not initialised")
    return _store


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _store
    check_ffmpeg()
    settings = get_settings()
    _store = Store(settings.db_path, settings.audio_dir)
    _store.prune(settings.history_retention_days)

    if not settings.groq_api_key:
        print(
            "\n  No GROQ_API_KEY set. Copy .env.example to .env and add a key "
            "from https://console.groq.com/keys\n"
        )
    if not settings.auth_enabled:
        print(
            "  APP_PASSWORD is blank, so there is no login gate. Only do this "
            "on localhost or a private network.\n"
        )
    yield


app = FastAPI(title="Remote Transcribe", lifespan=lifespan, docs_url=None, redoc_url=None)


# --------------------------------------------------------------------------- auth

@app.get("/api/session")
async def read_session(request: Request, settings: Settings = Depends(get_settings)):
    return {
        "auth_required": settings.auth_enabled,
        "authenticated": is_authenticated(request, settings),
    }


@app.post("/api/login")
async def login(
    response: Response,
    password: str = Form(""),
    settings: Settings = Depends(get_settings),
):
    if not settings.auth_enabled:
        return {"authenticated": True}
    if not password_matches(password, settings.app_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect password.")

    response.set_cookie(
        COOKIE_NAME,
        issue_token(settings.session_secret),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        # Set only over HTTPS; leaving it off would break plain-HTTP localhost.
        secure=False,
    )
    return {"authenticated": True}


@app.post("/api/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)
    return {"authenticated": False}


# --------------------------------------------------------------------------- metadata

@app.get("/api/settings", dependencies=[Depends(require_auth)])
async def read_settings(settings: Settings = Depends(get_settings)):
    """Booleans only — the API keys themselves never leave the server."""
    return {
        "groq_configured": bool(settings.groq_api_key),
        "elevenlabs_configured": bool(settings.elevenlabs_api_key),
        "default_model": settings.default_model,
        "llm_model": settings.llm_model,
        "max_upload_mb": round(settings.max_upload_bytes / 1e6, 1),
        "keep_audio": settings.keep_audio,
        "cleanup_presets": preset_options(),
    }


@app.get("/api/models", dependencies=[Depends(require_auth)])
async def list_models(settings: Settings = Depends(get_settings)):
    """Live model list from Groq, annotated with what we can verify."""
    warning: str | None = None
    ids: list[str] = []

    if settings.groq_api_key:
        try:
            available = await GroqEngine(
                settings.groq_api_key, settings.max_upload_bytes
            ).list_models()
            ids = [
                str(model["id"])
                for model in available
                if model.get("id") and catalog.is_audio_model(str(model["id"]))
                and model.get("active", True)
            ]
        except EngineError as exc:
            warning = f"Could not reach Groq for the live model list ({exc}). Showing defaults."

    if not ids:
        ids = list(catalog.GROQ_FALLBACK_IDS)

    # Recommended model first, then curated, then anything else.
    def sort_key(model_id: str) -> tuple[int, str]:
        entry = catalog.CURATED.get(model_id, {})
        if entry.get("recommended"):
            return (0, model_id)
        return (1 if entry else 2, model_id)

    models = [catalog.describe(model_id, "groq") for model_id in sorted(ids, key=sort_key)]
    if settings.elevenlabs_api_key:
        models.append(catalog.describe("scribe_v2", "elevenlabs"))

    return {"models": models, "warning": warning}


# --------------------------------------------------------------------------- transcription

def _parse_int(value: str, minimum: int, maximum: int) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if minimum <= parsed <= maximum else None


@app.post("/api/transcribe", dependencies=[Depends(require_auth)])
async def transcribe(
    file: UploadFile = File(...),
    model: str = Form(""),
    engine: str = Form("groq"),
    task: str = Form("transcribe"),
    language: str = Form(""),
    prompt: str = Form(""),
    temperature: str = Form("0"),
    diarization: str = Form("off"),
    num_speakers: str = Form(""),
    cleanup: str = Form("raw"),
    settings: Settings = Depends(get_settings),
):
    engine = engine if engine in {"groq", "elevenlabs"} else "groq"
    if engine == "elevenlabs" and not settings.elevenlabs_api_key:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "ElevenLabs is not configured. Add ELEVENLABS_API_KEY to your .env file.",
        )
    if engine == "groq" and not settings.groq_api_key:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No Groq API key configured. Add GROQ_API_KEY to your .env file — "
            "create one at https://console.groq.com/keys",
        )

    diarization = diarization if diarization in DIARIZATION_MODES else "off"
    if diarization == "acoustic" and engine != "elevenlabs":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Acoustic diarization needs the ElevenLabs engine. Groq's Whisper "
            "API cannot separate speakers.",
        )

    task = task if task in TASKS else "transcribe"
    try:
        temp = min(1.0, max(0.0, float(temperature)))
    except ValueError:
        temp = 0.0

    # Stream the upload to disk so a large file never sits in memory.
    suffix = Path(file.filename or "audio").suffix or ".bin"
    handle = tempfile.NamedTemporaryFile(prefix="rt-upload-", suffix=suffix, delete=False)
    source_path = Path(handle.name)
    try:
        with handle:
            shutil.copyfileobj(file.file, handle)
    finally:
        await file.close()

    if source_path.stat().st_size == 0:
        source_path.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That file is empty.")

    options = TranscribeOptions(
        model=model or settings.default_model,
        task=task,
        language=language.strip() or None,
        prompt=prompt.strip() or None,
        temperature=temp,
        diarize=diarization == "acoustic",
        num_speakers=_parse_int(num_speakers, 1, 32),
    )

    job = registry.create()
    registry.spawn(
        run_pipeline(
            job,
            PipelineRequest(
                source_path=source_path,
                original_name=file.filename or "recording",
                engine_name=engine,
                options=options,
                diarization_mode=diarization,
                cleanup_preset=cleanup if cleanup in {p["id"] for p in preset_options()} else "raw",
                expected_speakers=_parse_int(num_speakers, 1, 32),
            ),
            settings,
            get_store(),
        )
    )
    return {"job_id": job.id}


@app.get("/api/jobs/{job_id}", dependencies=[Depends(require_auth)])
async def read_job(job_id: str):
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That job has expired or never existed.")
    return job.to_dict()


# --------------------------------------------------------------------------- history

@app.get("/api/history", dependencies=[Depends(require_auth)])
async def list_history(store: Store = Depends(get_store)):
    return {"items": store.list()}


@app.get("/api/history/{record_id}", dependencies=[Depends(require_auth)])
async def read_history(record_id: str, store: Store = Depends(get_store)):
    record = store.get(record_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such transcript.")
    return record


@app.delete("/api/history/{record_id}", dependencies=[Depends(require_auth)])
async def delete_history(record_id: str, store: Store = Depends(get_store)):
    if not store.delete(record_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such transcript.")
    return {"deleted": True}


@app.get("/api/history/{record_id}/audio", dependencies=[Depends(require_auth)])
async def read_audio(record_id: str, store: Store = Depends(get_store)):
    path = store.audio_path(record_id)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No audio kept for this transcript.")
    return FileResponse(path, media_type="audio/flac")


@app.post("/api/history/{record_id}/cleanup", dependencies=[Depends(require_auth)])
async def recleanup(
    record_id: str,
    preset: str = Form("clean"),
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_settings),
):
    record = store.get(record_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such transcript.")
    if preset not in {p["id"] for p in preset_options()}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown cleanup preset.")

    if preset == "raw":
        store.update_cleanup(record_id, "", "raw")
        return {"clean_text": None, "preset": "raw", "warnings": []}

    engine = GroqEngine(settings.groq_api_key, settings.max_upload_bytes)
    text, warnings = await run_cleanup(engine, record["raw_text"], preset, settings.llm_model)
    store.update_cleanup(record_id, text, preset)
    return {"clean_text": text, "preset": preset, "warnings": warnings}


@app.post("/api/history/{record_id}/speakers", dependencies=[Depends(require_auth)])
async def rename_speakers(
    record_id: str, request: Request, store: Store = Depends(get_store)
):
    payload: dict[str, Any] = await request.json()
    mapping = {str(k): str(v).strip()[:60] for k, v in (payload.get("mapping") or {}).items()
               if str(v).strip()}
    if not mapping:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No speaker names supplied.")
    if not store.rename_speakers(record_id, mapping):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such transcript.")
    return store.get(record_id)


@app.get("/api/history/{record_id}/export", dependencies=[Depends(require_auth)])
async def export(record_id: str, fmt: str = "txt", store: Store = Depends(get_store)):
    if fmt not in formats.EXTENSIONS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported format.")

    record = store.get(record_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such transcript.")

    segments = segments_from_json(json.dumps(record["segments"]))
    body = formats.render(
        fmt, segments, record.get("clean_text") or record["raw_text"], record
    )
    stem = "".join(c for c in record["title"][:40] if c.isalnum() or c in " -_").strip()
    filename = f"{stem or 'transcript'}.{formats.EXTENSIONS[fmt]}"

    return Response(
        content=body,
        media_type=formats.MEDIA_TYPES[fmt],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --------------------------------------------------------------------------- static

@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"ok": True}


@app.exception_handler(StartupError)
async def startup_error_handler(_: Request, exc: StartupError):  # pragma: no cover
    return JSONResponse({"detail": str(exc)}, status_code=500)


if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
else:  # pragma: no cover
    @app.get("/")
    async def missing_static() -> PlainTextResponse:
        return PlainTextResponse("static/ directory is missing", status_code=500)
