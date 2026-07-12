#!/bin/sh
# Container entrypoint for the panel service.
#
# 1. Read /etc/panel/whitelist.json (bind-mounted by compose).
# 2. Rewrite argv so each command runs via `docker exec` in the
#    privileged sidecar.
# 3. Validate the rewritten whitelist using the same loader the
#    server uses at runtime — fail loudly if the rewrite produced
#    something the server will later reject.
# 4. exec the CMD passed by the Dockerfile (uvicorn ...).
#
# SIGHUP from `docker kill -s hup panel` triggers whitelist reload
# (handled in server.app:lifespan).

set -eu

SRC="${PANEL_WHITELIST_SRC:-/etc/panel/whitelist.src.json}"
DST="${PANEL_WHITELIST_PATH:-/etc/panel/whitelist.json}"
HOST_CONTAINER="${PANEL_HOST_CONTAINER:-panel-host}"
DOCKER_BIN="${PANEL_DOCKER_BIN:-/usr/bin/docker}"

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

echo "[entrypoint] starting $*"
exec "$@"