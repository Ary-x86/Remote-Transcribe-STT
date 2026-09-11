# Remote Transcribe

A self-hosted web app for turning speech into text with Whisper, running on
[Groq](https://groq.com). Click record, talk, and the transcript is in your
clipboard a second later. Or drop in a file — a voice memo, an interview, a
three-hour recording — and get it back as text, subtitles, or speaker-separated
turns.

Built for the case where you dictate faster than you type but are away from the
GPU that normally runs Whisper locally. Groq serves the same
`whisper-large-v3` at roughly 200× realtime for about four cents an hour.

## What it does

- **Record or upload.** Microphone capture in the browser, or drag in any audio
  or video file — the soundtrack is extracted for you.
- **Long recordings just work.** Audio is normalised to 16 kHz mono FLAC, and
  anything past the upload limit is split at natural pauses, transcribed in
  parallel, and stitched back together.
- **Multilingual.** All 99 Whisper languages, auto-detected or named
  explicitly. There is also a translate-to-English mode.
- **Speaker labels.** Estimated from the transcript by an LLM, or separated
  acoustically if you add an ElevenLabs key. See [Speakers](#speakers).
- **Optional cleanup pass.** Strip filler words, reformat rambling dictation
  into a structured prompt, or condense to notes. The raw transcript is always
  kept.
- **History.** Every transcript is saved with its audio, so you can replay it,
  re-run cleanup with a different preset, or export it later.
- **Exports.** Plain text, SRT, WebVTT, or the raw JSON with word timings.

## Quick start

You need [ffmpeg](https://ffmpeg.org), Python 3.11+, and a free API key from
[console.groq.com/keys](https://console.groq.com/keys).

```bash
git clone <this repo> && cd Remote-Transcribe
cp .env.example .env          # then put your key on the GROQ_API_KEY line

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --port 8080
```

Open <http://localhost:8080>.

### On Windows

Everything above works in PowerShell, but if you would rather double-click a
Desktop shortcut than open a terminal, see [`windows/README.md`](windows/README.md).
It covers a one-shot script that installs Desktop / Start Menu shortcuts
against your local checkout, and an Inno Setup script for building a
releasable `.exe` installer.

### With Docker

```bash
cp .env.example .env          # add your key
docker compose up -d
```

Compose binds the app to `127.0.0.1:8080` so it is only reachable through a
reverse proxy. Change the `ports` line to `"8080:8080"` to expose it directly.
Transcripts and audio live in `./data`, which survives rebuilds.

## Deploying to a server

1. Copy the project across, create `.env`, and set **`APP_PASSWORD`** — without
   it there is no login gate and anyone who finds the port can spend your Groq
   credits.
2. `docker compose up -d`.
3. Put it behind HTTPS. `Caddyfile.example` has a working config; point it at
   your domain and run `caddy run --config Caddyfile`.

> **TLS is not optional if you want the record button.** Browsers only grant
> microphone access on `localhost` or over HTTPS. Over plain HTTP to a remote
> IP the recorder is disabled and you can only upload files. The app detects
> this and tells you so rather than failing silently.

## Configuration

Everything lives in `.env`. Only `GROQ_API_KEY` is required.

| Variable | Default | What it does |
|---|---|---|
| `GROQ_API_KEY` | — | Required. From [console.groq.com/keys](https://console.groq.com/keys). |
| `ELEVENLABS_API_KEY` | — | Optional. Enables acoustic speaker separation. |
| `APP_PASSWORD` | — | Shared login password. Blank disables the login gate. |
| `SESSION_SECRET` | generated | Signs session cookies. Generated and persisted on first run. |
| `DEFAULT_MODEL` | `whisper-large-v3-turbo` | Model preselected in the UI. |
| `LLM_MODEL` | `openai/gpt-oss-120b` | Used for cleanup and speaker estimation. |
| `MAX_UPLOAD_BYTES` | `24000000` | Chunk threshold. Raise to ~`99000000` on Groq's dev tier. |
| `CHUNK_TARGET_SECONDS` | `600` | Preferred chunk length for long audio. |
| `CHUNK_OVERLAP_SECONDS` | `2` | Overlap between chunks, so no word is lost at a seam. |
| `MAX_CONCURRENT_CHUNKS` | `3` | Parallel requests. The free tier allows 20/min. |
| `KEEP_AUDIO` | `true` | Set `false` to keep transcripts but never store recordings. |
| `HISTORY_RETENTION_DAYS` | `30` | Age at which old transcripts are pruned. `0` keeps everything. |
| `DATA_DIR` | `./data` | Where the database and audio live. |

The API key is only ever used server-side. It is never sent to the browser and
never written to the database.

## Costs

Groq bills per hour of audio, with a 10-second minimum per request.

| | Turbo ($0.04/hr) | Large v3 ($0.111/hr) |
|---|---|---|
| 2-minute dictated prompt | $0.0013 | $0.0037 |
| 30-minute meeting | $0.02 | $0.06 |
| 3-hour recording | $0.12 | $0.33 |

Cleanup and speaker estimation add a fraction of a cent each. Free-tier limits
are 25 MB per file, 20 requests/minute, and 7200 seconds of audio per hour
(two audio-hours per hour, eight per day).

## Speakers

**Groq's Whisper API has no diarization.** It returns text with no notion of
who spoke. So there are two options, and they are not equivalent:

- **Estimate with an LLM** (default) sends the timestamped transcript to a Groq
  language model, which assigns speakers from conversational cues. It needs no
  extra setup and costs about a cent. But it reads the *text*, not the voices —
  dependable on clean back-and-forth, unreliable when people talk over each
  other. The UI labels it as an estimate for exactly this reason.
- **Acoustic** uses ElevenLabs Scribe v2 for real voice-based separation. Add
  `ELEVENLABS_API_KEY` to `.env` to enable it. Costs about $0.22/hour — roughly
  five times Turbo — and is worth it when attribution has to be right.

Either way, click a speaker label in the Speakers tab to rename them.

## Cleanup

After a transcript comes back, you can pick one of four presets. The raw
transcript is always kept, so you can re-run cleanup with a different preset
later without re-transcribing.

- **Raw** — Exactly what Whisper heard. No second LLM pass, no extra cost.
  Every filler word, false start, and mis-punctuation is left in.
- **Clean up** — Drops filler words (um, uh, like), stutters, and false starts,
  and fixes punctuation, capitalisation, and paragraph breaks. Your wording
  and meaning are preserved; nothing is summarised, reordered, or rephrased.
  Use this when you want a readable version of what you actually said.
- **Format as prompt** — Turns rambling dictation into a structured written
  prompt for an AI assistant. Organises the request logically, adds headings
  or bullets where they help, and makes implied structure explicit. Every
  requirement, constraint, question, and aside is preserved — nothing is
  invented and the prompt is never answered. Use this when you dictated a
  request to hand to another LLM.
- **Summary notes** — Condenses the transcript into a short context paragraph
  followed by bulleted key points, with separate headings for any decisions,
  action items, or open questions. Use this for meetings or interviews where
  you want the takeaways rather than the full text.

Clean up and Format as prompt preserve everything that was said; Summary
notes deliberately does not. Each cleanup pass costs a fraction of a cent on
top of the transcription itself.

## Known limits

- **Mixed languages in one recording.** Whisper transcribes one language at a
  time. On a genuinely bilingual conversation it may quietly translate
  everything into the dominant one. Leave the language on Auto, and consider
  ElevenLabs if it keeps getting it wrong.
- **Silence and music** can make Whisper hallucinate a stray phrase — often a
  "Thank you" or a subtitle credit. Trim dead air if you see it.
- **A failed chunk does not sink the whole transcript.** The rest still comes
  back, with a warning naming the minutes that are missing.

## Development

```bash
.venv/bin/python tests/test_pipeline.py
```

Runs offline — no API key needed and no credits spent. It builds real audio
with ffmpeg to exercise silence detection and chunk planning, then checks the
stitcher against the boundary cases that matter (an utterance re-timed across
a seam, a truncated chunk edge, a chunk that failed outright) and the export
formats.

### Layout

```
app/
  main.py         FastAPI routes
  config.py       settings from .env
  auth.py         password login, signed cookie
  audio.py        ffmpeg: probe, normalise, split, stitch
  jobs.py         pipeline orchestration and progress
  engines/        groq.py, elevenlabs.py, shared types in base.py
  postprocess.py  LLM speaker labelling and cleanup presets
  store.py        SQLite history
  formats.py      txt / srt / vtt / json
static/           the frontend: no framework, no build step
```
