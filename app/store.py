"""SQLite-backed transcript history, with the audio kept alongside for replay."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .engines.base import Segment, Word

SCHEMA = """
CREATE TABLE IF NOT EXISTS transcripts (
    id              TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    title           TEXT NOT NULL,
    engine          TEXT NOT NULL,
    model           TEXT NOT NULL,
    task            TEXT NOT NULL,
    language        TEXT,
    duration        REAL NOT NULL DEFAULT 0,
    raw_text        TEXT NOT NULL,
    clean_text      TEXT,
    cleanup_preset  TEXT,
    segments_json   TEXT NOT NULL,
    warnings_json   TEXT NOT NULL,
    options_json    TEXT NOT NULL,
    audio_filename  TEXT,
    audio_mime      TEXT
);
CREATE INDEX IF NOT EXISTS idx_transcripts_created ON transcripts(created_at DESC);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path, timeout=15.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def title_from(text: str) -> str:
    snippet = " ".join(text.split())[:70].strip()
    return snippet or "Untitled recording"


def segments_to_json(segments: list[Segment]) -> str:
    return json.dumps(
        [
            {
                "start": s.start, "end": s.end, "text": s.text, "speaker": s.speaker,
                "words": [{"start": w.start, "end": w.end, "text": w.text,
                           "speaker": w.speaker} for w in s.words],
            }
            for s in segments
        ],
        ensure_ascii=False,
    )


def segments_from_json(payload: str) -> list[Segment]:
    return [
        Segment(
            start=float(item.get("start", 0.0)),
            end=float(item.get("end", 0.0)),
            text=item.get("text", ""),
            speaker=item.get("speaker"),
            words=[
                Word(float(w.get("start", 0.0)), float(w.get("end", 0.0)),
                     w.get("text", ""), w.get("speaker"))
                for w in item.get("words") or []
            ],
        )
        for item in json.loads(payload or "[]")
    ]


class Store:
    def __init__(self, db_path: Path, audio_dir: Path) -> None:
        self.db_path = db_path
        self.audio_dir = audio_dir
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        with _connect(self.db_path) as connection:
            connection.executescript(SCHEMA)

    def save(
        self,
        *,
        raw_text: str,
        clean_text: str | None,
        cleanup_preset: str,
        segments: list[Segment],
        engine: str,
        model: str,
        task: str,
        language: str | None,
        duration: float,
        warnings: list[str],
        options: dict[str, Any],
        audio_bytes: bytes | None = None,
        audio_suffix: str = ".flac",
        audio_mime: str = "audio/flac",
    ) -> str:
        record_id = uuid.uuid4().hex
        audio_filename = None
        if audio_bytes:
            audio_filename = f"{record_id}{audio_suffix}"
            (self.audio_dir / audio_filename).write_bytes(audio_bytes)

        with _connect(self.db_path) as connection:
            connection.execute(
                """INSERT INTO transcripts (
                    id, created_at, title, engine, model, task, language, duration,
                    raw_text, clean_text, cleanup_preset, segments_json,
                    warnings_json, options_json, audio_filename, audio_mime
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record_id,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    title_from(clean_text or raw_text),
                    engine, model, task, language, duration,
                    raw_text, clean_text, cleanup_preset,
                    segments_to_json(segments),
                    json.dumps(warnings, ensure_ascii=False),
                    json.dumps(options, ensure_ascii=False),
                    audio_filename, audio_mime,
                ),
            )
        return record_id

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        with _connect(self.db_path) as connection:
            rows = connection.execute(
                """SELECT id, created_at, title, engine, model, task, language,
                          duration, audio_filename
                   FROM transcripts ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [{**dict(row), "has_audio": bool(row["audio_filename"])} for row in rows]

    def get(self, record_id: str) -> dict[str, Any] | None:
        with _connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM transcripts WHERE id = ?", (record_id,)
            ).fetchone()
        if row is None:
            return None

        record = dict(row)
        record["segments"] = json.loads(record.pop("segments_json") or "[]")
        record["warnings"] = json.loads(record.pop("warnings_json") or "[]")
        record["options"] = json.loads(record.pop("options_json") or "{}")
        record["has_audio"] = bool(record.get("audio_filename"))
        return record

    def update_cleanup(self, record_id: str, clean_text: str, preset: str) -> None:
        with _connect(self.db_path) as connection:
            connection.execute(
                "UPDATE transcripts SET clean_text = ?, cleanup_preset = ?, title = ? "
                "WHERE id = ?",
                (clean_text, preset, title_from(clean_text), record_id),
            )

    def rename_speakers(self, record_id: str, mapping: dict[str, str]) -> bool:
        record = self.get(record_id)
        if record is None:
            return False
        segments = segments_from_json(json.dumps(record["segments"]))
        for segment in segments:
            if segment.speaker and segment.speaker in mapping:
                segment.speaker = mapping[segment.speaker]
            for word in segment.words:
                if word.speaker and word.speaker in mapping:
                    word.speaker = mapping[word.speaker]
        with _connect(self.db_path) as connection:
            connection.execute(
                "UPDATE transcripts SET segments_json = ? WHERE id = ?",
                (segments_to_json(segments), record_id),
            )
        return True

    def delete(self, record_id: str) -> bool:
        record = self.get(record_id)
        if record is None:
            return False
        if record.get("audio_filename"):
            (self.audio_dir / record["audio_filename"]).unlink(missing_ok=True)
        with _connect(self.db_path) as connection:
            connection.execute("DELETE FROM transcripts WHERE id = ?", (record_id,))
        return True

    def audio_path(self, record_id: str) -> Path | None:
        record = self.get(record_id)
        if not record or not record.get("audio_filename"):
            return None
        path = self.audio_dir / record["audio_filename"]
        return path if path.is_file() else None

    def prune(self, retention_days: int) -> int:
        """Drop records past the retention window. 0 disables pruning."""
        if retention_days <= 0:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        with _connect(self.db_path) as connection:
            stale = connection.execute(
                "SELECT id, audio_filename FROM transcripts WHERE created_at < ?", (cutoff,)
            ).fetchall()
            for row in stale:
                if row["audio_filename"]:
                    (self.audio_dir / row["audio_filename"]).unlink(missing_ok=True)
            connection.execute("DELETE FROM transcripts WHERE created_at < ?", (cutoff,))
        return len(stale)
