# FastTrans: a desktop shortcut for Linux

Instead of opening an editor, opening a terminal, activating the venv and
typing `uvicorn app.main:app --port 8080`, install a **FastTrans** launcher
once and start the app from your app menu or Desktop like any other program.

Clicking it:

1. Opens a terminal window titled *FastTrans — Remote Transcribe*.
2. Goes to the repo root and activates `.venv` (creating it and running
   `pip install -r requirements.txt` the first time, if it doesn't exist).
3. Checks that `ffmpeg` is installed and that `.env` has a `GROQ_API_KEY`.
4. Runs `uvicorn app.main:app --port 8080` in the foreground, so the server
   logs stay visible.
5. Opens <http://localhost:8080> in your default browser once the server
   answers.

Close the window or press **Ctrl+C** to stop the server. If it is already
running, clicking the shortcut again just opens the browser. If startup
fails, the window stays open with the error until you press Enter.

Tested on Arch with KDE Plasma 6. It only relies on the freedesktop.org
desktop-entry standard, so GNOME, XFCE and the rest should work too.

## Install

From the repo root, after setting up `.env` (see the main
[README](../README.md#quick-start)):

```bash
linux/install.sh
```

That installs:

| What | Where |
|---|---|
| App menu entry (searchable in KRunner / the launcher as "FastTrans") | `~/.local/share/applications/fasttrans.desktop` |
| Desktop shortcut | `~/Desktop/fasttrans.desktop` |
| Icon | `~/.local/share/icons/hicolor/scalable/apps/fasttrans.svg` |

Options:

```bash
linux/install.sh --no-desktop   # app menu entry only, no Desktop icon
linux/install.sh --uninstall    # remove all of the above
```

The `.desktop` file has this checkout's absolute path baked in, so it is
generated per machine. A copy is kept at `linux/fasttrans.desktop`, which is
git-ignored. **If you move or rename the repo folder, run `install.sh`
again.**

To pin it to the KDE taskbar, right-click the entry in the app menu and
choose *Pin to Task Manager*.

## Changing the port

The launcher reads `PORT` from the environment (default `8080`). To use a
different port permanently, edit the `Exec=` line in the installed
`.desktop` file to `Exec=env PORT=9000 "/path/to/linux/fasttrans.sh"`, or
just run the script by hand:

```bash
PORT=9000 linux/fasttrans.sh
```

## Doing it by hand

If you'd rather not run the installer, this is all it does. Create
`~/.local/share/applications/fasttrans.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=FastTrans
GenericName=Remote Transcribe STT
Exec="/absolute/path/to/Remote-Transcribe-STT/linux/fasttrans.sh"
Path=/absolute/path/to/Remote-Transcribe-STT
Icon=/absolute/path/to/Remote-Transcribe-STT/linux/icon.svg
Terminal=true
Categories=AudioVideo;Audio;
```

Then `chmod +x` it and `linux/fasttrans.sh`, and copy the file to
`~/Desktop` if you want it there too. Keep the double quotes around the
`Exec` path if it contains spaces.

## Troubleshooting

**The Desktop icon shows a warning / asks whether to trust it.** Plasma
asks once for launchers it hasn't seen. Choose *Continue* (or *Mark as
executable*). `install.sh` already sets the executable bit, which normally
skips this.

**The wrong terminal opens.** `Terminal=true` uses your desktop's default
terminal. On KDE set it under *System Settings → Default Applications →
Terminal Emulator*.

**It doesn't show up in the menu.** Run `kbuildsycoca6` (KDE) or log out and
back in.
