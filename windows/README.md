# Running Remote Transcribe on Windows

The rest of this project assumes Linux. This folder makes running it on
Windows a one-click affair: a desktop shortcut that starts the server hidden
in the background, waits for it to be ready, and opens the app in your
default browser.

There are two paths — pick whichever fits.

- **[Path A — Personal use](#path-a--personal-use-existing-clone).** You
  already have the repo cloned. Run one `.bat` to get shortcuts on your
  Desktop and Start Menu. No installer, no admin rights, ten seconds.
- **[Path B — Releasable installer](#path-b--build-a-releasable-installer).**
  Build a single `.exe` installer with [Inno Setup](https://jrsoftware.org/isinfo.php)
  that you can attach to a GitHub Release. Installs to `%LOCALAPPDATA%`,
  detects and upgrades existing installs, preserves user data.

Both paths need the same prerequisites on the target machine:

- **Python 3.11+**, installed with *Add Python to PATH* ticked.
- **ffmpeg**, on PATH (`winget install Gyan.FFmpeg` is the easy option).
- A **Groq API key** from <https://console.groq.com/keys>.

---

## Path A — Personal use (existing clone)

1. Clone the repo somewhere sensible — e.g. `C:\Users\<you>\Code\Remote-Transcribe-STT`.
2. Open the `windows` folder in File Explorer.
3. Double-click **`install-shortcuts.bat`**.

That creates:

- `Remote Transcribe` on your Desktop.
- A `Remote Transcribe` folder in the Start Menu with **Start**,
  **Stop Remote Transcribe**, and **Update Remote Transcribe** shortcuts.

Double-click the Desktop shortcut. On the first launch it will:

1. Create the `.venv` and install dependencies (~1 minute, one time only).
2. Copy `.env.example` to `.env` and open it in Notepad — paste your Groq key
   on the `GROQ_API_KEY=` line, save, close.
3. Start the server hidden and open <http://localhost:8080> when it is ready.

Every subsequent launch is instant: the venv is already there, the browser
opens straight away. If `requirements.txt` has changed since your last
launch (e.g. after a `git pull`), the launcher notices and reinstalls
dependencies automatically before starting the server.

### Optional: custom icon

Drop an `icon.ico` in this folder and re-run `install-shortcuts.bat`. The
shortcuts will pick it up. Any square PNG converted to `.ico` (e.g. via
<https://icoconvert.com>) works.

### Stopping the app

The server keeps running in the background until you either restart Windows
or click **Stop Remote Transcribe** in the Start Menu (which kills whatever
is listening on port 8080).

### What each file in this folder does

| File | Purpose |
|---|---|
| `launcher.ps1` | The real launcher — bootstraps venv, syncs deps, starts uvicorn, opens the browser. |
| `launcher.vbs` | Silent wrapper for `launcher.ps1` so no console window appears. This is what the shortcuts point at. |
| `stop.ps1` / `stop.vbs` | Kills the process listening on port 8080. |
| `update.ps1` | `git pull` + `pip install -r requirements.txt`. Shows output; wait for a keypress. |
| `install-shortcuts.ps1` | Creates the Desktop and Start Menu shortcuts pointing at the files above. |
| `install-shortcuts.bat` | Double-clickable wrapper for `install-shortcuts.ps1` (bypasses execution policy for this one call). |
| `installer.iss` | Inno Setup script for [Path B](#path-b--build-a-releasable-installer). |

---

## Path B — Build a releasable installer

Use this when you want a single `.exe` you can upload to a GitHub Release
so the app installs on any Windows box without cloning the repo.

### One-off setup on your build machine

1. Install **Inno Setup** — <https://jrsoftware.org/isinfo.php>. The default
   install puts `ISCC.exe` on `C:\Program Files (x86)\Inno Setup 6\`.
2. Optionally add that folder to PATH so you can call `iscc` directly.

### Build

From the repo root, in any shell:

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DAppVersion=1.0.0 windows\installer.iss
```

Output lands in `windows\output\RemoteTranscribe-Setup-1.0.0.exe`. Attach
that file to a GitHub Release.

Bump `/DAppVersion=` for every release. The installer uses a fixed `AppId`,
so running a newer version detects the previous install and upgrades it in
place; the `data\` folder is preserved across upgrades and even across
uninstalls.

### What the installer does on the target machine

- Installs to `%LOCALAPPDATA%\Programs\RemoteTranscribe` (no admin needed).
- Creates Start Menu shortcuts and, if the user ticks the box, a Desktop
  shortcut.
- Warns (does not block) if Python is not on PATH.
- Offers to launch the app when install finishes.
- On uninstall, removes the app and the `.venv` but keeps `data\`.

### What the installer does *not* do

It doesn't bundle Python or ffmpeg — both are large and outside the scope of
this app. The install prompt tells the user to install them if missing. If
you want a truly zero-dependency installer, the two options are
[PyInstaller](https://pyinstaller.org/) (bundle Python + all deps into a
single exe, then wrap that with Inno Setup) or [embeddable Python](https://docs.python.org/3/using/windows.html#windows-embeddable)
(ship a portable Python inside the installer). Both are meaningful projects
in their own right — deliberately out of scope here.

### Release checklist

1. `git tag v1.0.0 && git push --tags`
2. Build: `iscc /DAppVersion=1.0.0 windows\installer.iss`
3. Create a GitHub Release for the tag, attach the `.exe` from
   `windows\output\`.

---

## Troubleshooting

**Nothing happens when I double-click the shortcut.** Open
`windows\last-startup.log` and `windows\uvicorn.err.log` — one of them will
tell you why.

**"Python is not recognized"** during first launch. Python isn't on PATH.
Reinstall Python from python.org and tick *Add Python to PATH*.

**"Port 8080 already in use"** in the log. Something else is bound to 8080.
Either stop it, or edit `launcher.ps1` and `stop.ps1` to use a different
port.

**Microphone doesn't work in the browser.** Chrome and Edge only grant
microphone access on `localhost` or over HTTPS. The launcher opens
`http://localhost:8080`, which qualifies — but if you access the app from
another device on your LAN by IP, the recorder is disabled. That is a
browser rule, not the app.
