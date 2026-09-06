"""Settings, loaded from the environment with a .env file as a fallback."""

from __future__ import annotations

import os
import secrets
import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path) -> None:
    """Populate os.environ from a .env file. Real env vars always win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _str(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _int(name: str, default: int) -> int:
    try:
        return int(_str(name) or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(_str(name) or default)
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    value = _str(name).lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    groq_api_key: str
    elevenlabs_api_key: str
    app_password: str
    session_secret: str
    default_model: str
    llm_model: str
    max_upload_bytes: int
    chunk_target_seconds: int
    chunk_overlap_seconds: float
    max_concurrent_chunks: int
    keep_audio: bool
    history_retention_days: int
    data_dir: Path

    @property
    def auth_enabled(self) -> bool:
        return bool(self.app_password)

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "audio"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "transcribe.db"


def _resolve_session_secret(data_dir: Path) -> str:
    """Use the configured secret, else a persisted random one so that
    sessions survive a restart."""
    configured = _str("SESSION_SECRET")
    if configured:
        return configured
    secret_file = data_dir / ".session_secret"
    if secret_file.is_file():
        stored = secret_file.read_text(encoding="utf-8").strip()
        if stored:
            return stored
    generated = secrets.token_urlsafe(48)
    secret_file.write_text(generated, encoding="utf-8")
    secret_file.chmod(0o600)
    return generated


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")

    data_dir = Path(_str("DATA_DIR", "./data"))
    if not data_dir.is_absolute():
        data_dir = (PROJECT_ROOT / data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "audio").mkdir(parents=True, exist_ok=True)

    return Settings(
        groq_api_key=_str("GROQ_API_KEY"),
        elevenlabs_api_key=_str("ELEVENLABS_API_KEY"),
        app_password=_str("APP_PASSWORD"),
        session_secret=_resolve_session_secret(data_dir),
        default_model=_str("DEFAULT_MODEL", "whisper-large-v3-turbo"),
        llm_model=_str("LLM_MODEL", "openai/gpt-oss-120b"),
        max_upload_bytes=_int("MAX_UPLOAD_BYTES", 24_000_000),
        chunk_target_seconds=_int("CHUNK_TARGET_SECONDS", 600),
        chunk_overlap_seconds=_float("CHUNK_OVERLAP_SECONDS", 2.0),
        max_concurrent_chunks=max(1, _int("MAX_CONCURRENT_CHUNKS", 3)),
        keep_audio=_bool("KEEP_AUDIO", True),
        history_retention_days=_int("HISTORY_RETENTION_DAYS", 30),
        data_dir=data_dir,
    )


class StartupError(RuntimeError):
    pass


def check_ffmpeg() -> None:
    """Fail loudly at startup rather than mysteriously on first upload."""
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        raise StartupError(
            f"Required tool(s) not found on PATH: {', '.join(missing)}. "
            "Install ffmpeg (Debian/Ubuntu: apt install ffmpeg, "
            "Arch: pacman -S ffmpeg, macOS: brew install ffmpeg), or run the "
            "app with Docker where it is preinstalled."
        )
