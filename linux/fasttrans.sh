#!/usr/bin/env bash
# FastTrans launcher for Remote Transcribe.
#
# Meant to run inside a terminal window (the desktop entry sets
# Terminal=true). Goes to the repo root, sets up .venv on first run, starts
# uvicorn in the foreground so the logs stay visible, and opens the browser
# once the server answers. Close the window or press Ctrl+C to stop it.

set -uo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
PORT="${PORT:-8080}"
URL="http://localhost:$PORT"

cd "$ROOT" || exit 1
printf '\033]0;FastTrans — Remote Transcribe\007'

fail() {
    echo
    echo "error: $*" >&2
    echo
    read -rp "Press Enter to close..." _
    exit 1
}

healthy() {
    curl -fsS -o /dev/null --max-time 1 "$URL/healthz" 2>/dev/null
}

open_browser() {
    xdg-open "$URL" >/dev/null 2>&1 &
}

# Already running (another FastTrans window, or started by hand)? Just open it.
if healthy; then
    echo "Remote Transcribe is already running on $URL — opening the browser."
    open_browser
    sleep 2
    exit 0
fi

command -v ffmpeg >/dev/null || fail "ffmpeg is not installed (pacman -S ffmpeg / apt install ffmpeg)."
command -v curl >/dev/null || fail "curl is not installed."

if [[ ! -f .env ]]; then
    fail "$ROOT/.env is missing. Copy .env.example to .env and set GROQ_API_KEY."
fi
grep -Eq '^[[:space:]]*GROQ_API_KEY[[:space:]]*=[[:space:]]*[^[:space:]]' .env \
    || fail "GROQ_API_KEY is empty in $ROOT/.env."

if [[ ! -x .venv/bin/uvicorn ]]; then
    echo "First run: creating .venv and installing dependencies..."
    python3 -m venv .venv || fail "could not create .venv (is python3 installed?)."
    .venv/bin/pip install -r requirements.txt || fail "pip install failed."
fi

# shellcheck disable=SC1091
source .venv/bin/activate

# Wait for the server in the background, then open the browser once.
(
    for _ in $(seq 1 100); do
        if healthy; then open_browser; exit 0; fi
        sleep 0.3
    done
) &

echo "Starting Remote Transcribe on $URL  (Ctrl+C to stop)"
echo
uvicorn app.main:app --port "$PORT"
status=$?

# Ctrl+C exits cleanly; anything else is a crash worth reading before the
# window closes.
if [[ $status -ne 0 && $status -ne 130 ]]; then
    fail "uvicorn exited with status $status (see the output above)."
fi
