#!/bin/sh
# Container entrypoint for the panel service.
#
# 1. Read /etc/panel/whitelist.json (bind-mounted by compose).
# 2. Rewrite argv so each command runs via `docker exec` in the
#    privileged sidecar.
# 3. Validate the rewritten whitelist using the same loader the
#    server uses at runtime — fail loudly if the rewrite produced
#    something the server will later reject.
# 4. Drop privileges (root -> uid 999) and exec the CMD passed by
#    the Dockerfile (uvicorn ...).
#
# SIGHUP from `docker kill -s hup panel` triggers whitelist reload
# (handled in server.app:lifespan). tini forwards the signal to
# uvicorn because we're already exec'd into it via gosu.

set -eu

SRC="${PANEL_WHITELIST_SRC:-/etc/panel/whitelist.src.json}"
DST="${PANEL_WHITELIST_PATH:-/etc/panel/whitelist.json}"
HOST_CONTAINER="${PANEL_HOST_CONTAINER:-panel-host}"
DOCKER_BIN="${PANEL_DOCKER_BIN:-/usr/bin/docker}"

# /etc/panel is a freshly-mounted named volume on first boot — root-
# owned by default. We run as root here so the chown actually takes
# effect (cap_drop: ALL in compose strips CAP_CHOWN from the long-
# running uvicorn process, but the entrypoint runs unconstrained).
DST_DIR="$(dirname "$DST")"
if [ -d "$DST_DIR" ]; then
    chown panel:panel "$DST_DIR"
fi

if [ ! -f "$SRC" ]; then
    echo "[entrypoint] whitelist source not found at $SRC" >&2
    exit 1
fi

echo "[entrypoint] rewriting $SRC -> $DST (host=$HOST_CONTAINER docker=$DOCKER_BIN)"
python -m server.docker_rewrite \
    --input "$SRC" \
    --output "$DST" \
    --host-container "$HOST_CONTAINER" \
    --docker-bin "$DOCKER_BIN"

# Validate using the same loader the server uses. Catches rewrite bugs
# (e.g. an absolute path that becomes relative) before they hit prod.
PANEL_SECRET="${PANEL_SECRET:-validate-only}"
export PANEL_SECRET
python - <<'PY'
import os, sys
from pathlib import Path
from server.config import Settings
from server.whitelist import load_whitelist
try:
    settings = Settings(secret=os.environ["PANEL_SECRET"])  # type: ignore[call-arg]
except Exception as e:
    print(f"[entrypoint] settings init failed: {e}", file=sys.stderr)
    sys.exit(1)
try:
    wl = load_whitelist(settings.whitelist_path)
except Exception as e:
    print(f"[entrypoint] rewritten whitelist is invalid: {e}", file=sys.stderr)
    sys.exit(1)
print(f"[entrypoint] whitelist OK: {len(list(wl.ids()))} commands")
PY

# Drop to the panel user before exec'ing uvicorn. gosu is the standard
# Debian privilege-drop tool: it does setuid only and forks, so PID 1
# (tini) keeps signal-forwarding semantics intact.
echo "[entrypoint] starting $*"
exec gosu panel "$@"