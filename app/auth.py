"""Shared-password login with an HMAC-signed session cookie.

Deliberately stdlib-only: one password, one cookie, no user accounts. That is
the whole threat model — keep a public VPS deployment from handing strangers
your Groq credits.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

from fastapi import Depends, HTTPException, Request, status

from .config import Settings, get_settings

COOKIE_NAME = "rt_session"
SESSION_TTL_SECONDS = 30 * 24 * 3600  # 30 days; this is a personal tool


def _sign(payload: str, secret: str) -> str:
    digest = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def issue_token(secret: str) -> str:
    payload = str(int(time.time()))
    return f"{payload}.{_sign(payload, secret)}"


def verify_token(token: str | None, secret: str) -> bool:
    if not token or "." not in token:
        return False
    payload, _, signature = token.rpartition(".")
    if not hmac.compare_digest(signature, _sign(payload, secret)):
        return False
    try:
        issued_at = int(payload)
    except ValueError:
        return False
    return 0 <= time.time() - issued_at <= SESSION_TTL_SECONDS


def password_matches(candidate: str, expected: str) -> bool:
    """Constant-time, so the endpoint does not leak the password by timing."""
    return hmac.compare_digest(candidate.encode(), expected.encode())


def is_authenticated(request: Request, settings: Settings) -> bool:
    if not settings.auth_enabled:
        return True
    return verify_token(request.cookies.get(COOKIE_NAME), settings.session_secret)


def require_auth(
    request: Request, settings: Settings = Depends(get_settings)
) -> None:
    if not is_authenticated(request, settings):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to continue.",
        )


def new_secret() -> str:
    return secrets.token_urlsafe(48)
