#!/bin/sh
# A bind-mounted ./data arrives owned by the host user, which hides whatever
# ownership the image set on /data. So fix it here, at runtime, when we still
# have root — then drop to the unprivileged account to actually run the app.
set -e

APP_UID=10001
APP_GID=10001
DATA_DIR="${DATA_DIR:-/data}"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_DIR/audio"
    # Only touch ownership when it is actually wrong: on a large existing
    # history a blanket recursive chown would be slow for no reason.
    if [ "$(stat -c %u "$DATA_DIR")" != "$APP_UID" ]; then
        chown -R "$APP_UID:$APP_GID" "$DATA_DIR"
    fi
    exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --init-groups "$@"
fi

# Already unprivileged, e.g. the operator set `user:` in compose. Run as-is;
# if the volume is not writable the app will say so at startup.
mkdir -p "$DATA_DIR/audio" 2>/dev/null || true
exec "$@"
