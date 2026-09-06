"""Groq client: audio transcription/translation plus a small chat helper.

Talks to the HTTP API directly rather than through the SDK — one httpx client
covers Groq and ElevenLabs, and there is no SDK version to drift out from
under us.
"""

from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path
from typing import Any

import httpx

from .base import EngineError, Segment, Transcript, TranscribeOptions, Word

BASE_URL = "https://api.groq.com/openai/v1"
MAX_ATTEMPTS = 4
# Groq truncates the transcription prompt at 224 tokens; ~4 chars/token.
PROMPT_CHAR_LIMIT = 224 * 4


def _mime_for(path: Path) -> str:
    return {
        ".flac": "audio/flac", ".mp3": "audio/mpeg", ".mp4": "audio/mp4",
        ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".wav": "audio/wav",
        ".webm": "audio/webm", ".mpeg": "audio/mpeg", ".mpga": "audio/mpeg",
    }.get(path.suffix.lower(), "application/octet-stream")


def _parse_verbose(payload: dict[str, Any]) -> tuple[list[Segment], str | None, float]:
    """verbose_json -> our Segment list, with word timings attached."""
    words_by_time = [
        Word(float(w.get("start", 0.0)), float(w.get("end", 0.0)), str(w.get("word", "")))
        for w in payload.get("words") or []
    ]

    segments: list[Segment] = []
    for raw in payload.get("segments") or []:
        start = float(raw.get("start", 0.0))
        end = float(raw.get("end", 0.0))
        segments.append(
            Segment(
                start=start,
                end=end,
                text=str(raw.get("text", "")).strip(),
                words=[w for w in words_by_time if start <= w.start < end],
            )
        )

    # Some responses carry text without segments; keep the text usable.
    if not segments and payload.get("text"):
        segments = [Segment(0.0, float(payload.get("duration", 0.0)),
                            str(payload["text"]).strip(), words=words_by_time)]

    return segments, payload.get("language"), float(payload.get("duration", 0.0) or 0.0)


class GroqEngine:
    name = "groq"
    supports_diarization = False

    def __init__(self, api_key: str, max_upload_bytes: int) -> None:
        if not api_key:
            raise EngineError(
                "No Groq API key configured. Add GROQ_API_KEY to your .env "
                "file — you can create one at https://console.groq.com/keys"
            )
        self.api_key = api_key
        self.max_upload_bytes = max_upload_bytes

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def _request(self, client: httpx.AsyncClient, **kwargs: Any) -> httpx.Response:
        """POST/GET with backoff on rate limits and transient server errors."""
        last_error = ""
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = await client.request(**kwargs, headers=self._headers)
            except httpx.RequestError as exc:
                last_error = f"could not reach Groq ({exc.__class__.__name__})"
                if attempt == MAX_ATTEMPTS - 1:
                    break
                await asyncio.sleep(2**attempt + random.random())
                continue

            if response.status_code < 400:
                return response

            if response.status_code in (408, 429) or response.status_code >= 500:
                last_error = self._error_message(response)
                if attempt == MAX_ATTEMPTS - 1:
                    break
                retry_after = response.headers.get("retry-after")
                try:
                    delay = float(retry_after) if retry_after else 2**attempt
                except ValueError:
                    delay = 2**attempt
                await asyncio.sleep(min(delay, 30) + random.random())
                continue

            raise EngineError(self._error_message(response), response.status_code)

        raise EngineError(f"Groq request failed after {MAX_ATTEMPTS} attempts: {last_error}")

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            body = response.json()
            message = body.get("error", {}).get("message") or body.get("error") or ""
        except (ValueError, AttributeError):
            message = response.text[:300]
        if response.status_code == 401:
            return "Groq rejected the API key. Check GROQ_API_KEY in your .env file."
        if response.status_code == 413:
            return ("Groq rejected the upload as too large. Lower "
                    "MAX_UPLOAD_BYTES so the app splits the audio into "
                    "smaller pieces.")
        if response.status_code == 429:
            return f"Groq rate limit reached. {message}".strip()
        return f"Groq error {response.status_code}: {message}".strip()

    async def transcribe(self, audio_path: str | Path, options: TranscribeOptions) -> Transcript:
        path = Path(audio_path)
        size = path.stat().st_size
        if size > self.max_upload_bytes:
            raise EngineError(
                f"{path.name} is {size / 1e6:.1f} MB, over the "
                f"{self.max_upload_bytes / 1e6:.0f} MB limit. It should have "
                "been split before reaching this point."
            )

        translating = options.task == "translate"
        endpoint = "/audio/translations" if translating else "/audio/transcriptions"

        data: dict[str, str] = {
            "model": options.model,
            "response_format": "verbose_json",
            "temperature": str(options.temperature),
        }
        if not translating and options.language:
            data["language"] = options.language
        if options.prompt:
            data["prompt"] = options.prompt[:PROMPT_CHAR_LIMIT]

        files = [
            ("file", (path.name, path.read_bytes(), _mime_for(path))),
            # Word timings power the SRT/VTT exports and speaker grouping.
            ("timestamp_granularities[]", (None, "segment")),
            ("timestamp_granularities[]", (None, "word")),
        ]

        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=15.0)) as client:
            response = await self._request(
                client, method="POST", url=f"{BASE_URL}{endpoint}", data=data, files=files
            )

        payload = response.json()
        segments, language, duration = _parse_verbose(payload)
        return Transcript(
            text=str(payload.get("text", "")).strip(),
            segments=segments,
            language="en" if translating else language,
            duration=duration,
            engine=self.name,
            model=options.model,
        )

    async def list_models(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await self._request(client, method="GET", url=f"{BASE_URL}/models")
        return response.json().get("data", [])

    async def chat_json(
        self, system: str, user: str, model: str, max_tokens: int = 8192
    ) -> dict[str, Any]:
        """Chat completion constrained to a JSON object. Used for speaker labelling."""
        text = await self.chat(system, user, model, max_tokens, json_mode=True)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise EngineError(f"The model returned malformed JSON: {exc}") from exc

    async def chat(
        self,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 8192,
        json_mode: bool = False,
    ) -> str:
        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_completion_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=15.0)) as client:
            response = await self._request(
                client, method="POST", url=f"{BASE_URL}/chat/completions", json=body
            )
        choices = response.json().get("choices") or []
        if not choices:
            raise EngineError("The model returned an empty response.")
        return str(choices[0].get("message", {}).get("content", "")).strip()
