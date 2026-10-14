#!/usr/bin/env bash
# Installs a "FastTrans" app-menu entry and Desktop shortcut that run
# linux/fasttrans.sh in a terminal. The generated .desktop file contains this
# checkout's absolute path, so it is written to linux/fasttrans.desktop
# (git-ignored) and copied into place. Re-run after moving the repo.
#
#   linux/install.sh              menu entry + Desktop shortcut
#   linux/install.sh --no-desktop menu entry only
#   linux/install.sh --uninstall  remove everything this script installed

set -euo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
ROOT="$(dirname "$HERE")"

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APPS_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/scalable/apps"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"

NAME="fasttrans"
GENERATED="$HERE/$NAME.desktop"

refresh_menus() {
    command -v update-desktop-database >/dev/null && update-desktop-database -q "$APPS_DIR" || true
    command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$DATA_HOME/icons/hicolor" || true
    for k in kbuildsycoca6 kbuildsycoca5; do
        command -v "$k" >/dev/null && { "$k" >/dev/null 2>&1 || true; break; }
    done
    return 0
}

if [[ "${1:-}" == "--uninstall" ]]; then
    rm -fv "$APPS_DIR/$NAME.desktop" "$DESKTOP_DIR/$NAME.desktop" "$ICON_DIR/$NAME.svg" "$GENERATED"
    refresh_menus
    exit 0
fi

# Quote a path for a desktop-entry Exec key: wrap in double quotes, escape
# the four reserved characters, then double every backslash for the
# key-file string layer.
exec_quote() {
    local s="$1"
    s="${s//\\/\\\\}"; s="${s//\"/\\\"}"; s="${s//\`/\\\`}"; s="${s//\$/\\\$}"
    s="\"$s\""
    printf '%s' "${s//\\/\\\\}"
}

chmod +x "$HERE/fasttrans.sh"
install -Dm644 "$HERE/icon.svg" "$ICON_DIR/$NAME.svg"

cat > "$GENERATED" <<EOF
[Desktop Entry]
Type=Application
Name=FastTrans
GenericName=Remote Transcribe STT
Comment=Start the Remote Transcribe server and open it in the browser
Exec=$(exec_quote "$ROOT/linux/fasttrans.sh")
Path=$ROOT
Icon=$NAME
Terminal=true
Categories=AudioVideo;Audio;
Keywords=transcribe;whisper;speech;stt;dictation;groq;
StartupNotify=true
EOF
chmod +x "$GENERATED"

install -Dm755 "$GENERATED" "$APPS_DIR/$NAME.desktop"
echo "Installed menu entry: $APPS_DIR/$NAME.desktop"

if [[ "${1:-}" != "--no-desktop" && -d "$DESKTOP_DIR" ]]; then
    install -Dm755 "$GENERATED" "$DESKTOP_DIR/$NAME.desktop"
    # GNOME/Nautilus also wants the launcher marked trusted; harmless elsewhere.
    command -v gio >/dev/null && gio set "$DESKTOP_DIR/$NAME.desktop" metadata::trusted true 2>/dev/null || true
    echo "Installed Desktop shortcut: $DESKTOP_DIR/$NAME.desktop"
fi

refresh_menus
echo "Done. Search for \"FastTrans\" in your app launcher."
