# Remote Transcribe for Windows

Everything in this folder is about producing **one** installer `.exe` that
sets up Remote Transcribe as a normal Windows app:

- Prompts for your Groq API key (and optional ElevenLabs key and password)
  during install — no editing config files.
- Downloads a private Python 3.11 runtime and a private ffmpeg build during
  install, into the app's own folder. Nothing on your system PATH, nothing
  polluted.
- Puts a **Remote Transcribe** shortcut on your Desktop and in the Start
  Menu. Double-click, browser opens, done.
- Re-running the installer detects the existing install, pre-fills your
  keys, and lets you change them without a reinstall. Uninstall lives in
  Windows' normal Apps & features.
- Bumping the version in the build command produces an upgrade installer.

If you just want to *use* the app, ignore the rest of this file and grab
the latest `RemoteTranscribe-Setup-x.y.z.exe` from the project's GitHub
Releases page.

Everything below is for **building** the installer.

---

## Building the installer

### One-off setup

Install **Inno Setup 6.1 or newer** — <https://jrsoftware.org/isinfo.php>.
The default location is `C:\Program Files (x86)\Inno Setup 6\`. Optionally
add that folder to PATH so `iscc` works from any shell.

Nothing else. Python and ffmpeg are *not* needed on the build machine —
they are fetched by the installer at install time on the end user's
machine.

### Build

From the repo root:

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DAppVersion=1.0.0 windows\installer.iss
```

Output: `windows\output\RemoteTranscribe-Setup-1.0.0.exe`. That single
file is the whole installer — attach it to a GitHub Release.

Bump `/DAppVersion=` on every release. The installer uses a fixed `AppId`,
so newer versions detect and upgrade older installs in place.

### Optional: icon

Drop an `icon.ico` next to `installer.iss` before building and it will
become the app's Start Menu / Desktop / Add-Remove Programs icon. Any
square PNG converted at <https://icoconvert.com> works. If missing, the
installer builds without a custom icon.

---

## What the installer actually does

When the user runs `RemoteTranscribe-Setup-x.y.z.exe`:

1. **Welcome / install location.** Standard Inno Setup pages.
2. **Configuration page** — three text boxes:
   - Groq API key (required; blank installs but the app will refuse to
     transcribe until fixed)
   - ElevenLabs key (optional)
   - App password (optional; blank disables the login gate)
   If a previous install exists, all three are pre-filled from the
   existing `.env`.
3. **Copy app files** into the install directory (`app\`, `static\`,
   `tests\`, `requirements.txt`, `.env.example`, `windows\launcher.*`).
4. **Write `.env`** from the values entered on the Configuration page.
5. **Download and extract Python 3.11 embeddable** into `{app}\python\`,
   uncomment `import site` in `python311._pth`, bootstrap `pip` with
   `get-pip.py`.
6. **`pip install -r requirements.txt`** into that private Python.
7. **Download and extract ffmpeg** into `{app}\ffmpeg\` (the launcher adds
   `{app}\ffmpeg\bin` to PATH for its own process only).
8. **Create shortcuts.** Start Menu always; Desktop if the user ticked the
   box on the Ready page.
9. **Finish page** with a "Launch now" checkbox.

Total on-disk footprint after install: ~250 MB. Install-time internet
usage: ~120 MB (Python zip, ffmpeg zip, pip wheels).

## Layout after install

```
{app}\                          e.g. C:\Program Files\RemoteTranscribe
  app\                          Python source
  static\                       frontend
  tests\
  python\                       private Python 3.11 (created by installer)
    python.exe
    Lib\site-packages\          app dependencies
  ffmpeg\                       private ffmpeg (created by installer)
    bin\ffmpeg.exe
    bin\ffprobe.exe
  data\                         transcripts + audio (preserved on upgrade + uninstall)
  windows\
    launcher.vbs                shortcut target — starts server hidden
    launcher.ps1                the real launcher logic
  .env                          written by installer, editable by re-running it
  requirements.txt
```

## What re-running the installer offers

- **Same version installed:** installer runs through again with the
  Configuration page pre-filled. Save = update `.env` and repair any
  missing files. Effectively "change keys" and "repair" in one flow.
- **Older version installed:** wizard title reads "An older version was
  detected…" on the Configuration page. Proceeding upgrades in place;
  `data\` and `.env` are preserved.
- **Newer version installed:** installer warns you are about to downgrade
  and asks for confirmation.
- **Uninstall:** use *Settings → Apps → Remote Transcribe → Uninstall*.
  Removes the app, the bundled Python, and ffmpeg; keeps `data\`.

## Troubleshooting

**Nothing happens when I double-click the shortcut.** Open
`{app}\windows\last-startup.log` and `{app}\windows\uvicorn.err.log` —
one of them will name the problem.

**Install fails at "Downloading Python runtime".** No internet reachable
from the install context. Retry when online.

**Install fails at "Installing Python dependencies".** Usually a pip
network hiccup. Re-run the installer; step 5 skips work already done, so
it resumes at pip.

**Microphone doesn't work.** Browsers only grant microphone access on
`localhost` or HTTPS. The launcher opens `http://localhost:8080`, which
qualifies. Accessing the app from another device by LAN IP disables the
recorder — that's a browser rule, not the app.
