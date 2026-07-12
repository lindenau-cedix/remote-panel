#!/bin/bash
# migrate-to-bare-metal.sh
#
# Run this on the prod VPS (vps-9770ade5) to migrate Remote Panel from the
# docker-compose stack to the bare-metal systemd install.
#
# Pre-flight (the script does not check these for you):
#   1. You have root or passwordless sudo.
#   2. You have a checkout of this repo somewhere accessible.
#      Easiest: ssh-key access + a fresh `git clone` of the repo on the VPS.
#   3. `deploy/docker/.env` exists somewhere with PANEL_SECRET set (we read
#      from it so the phone doesn't need re-pairing).
#
# The script is idempotent for Phase 1 (it skips already-installed units).
# Phases 2-4 are intentionally NOT idempotent — re-running them after a
# success will fail. If something goes wrong in Phase 1.7 or later, fix the
# specific cause and continue from there; do NOT re-run from the top.

set -euo pipefail

REPO_URL="${PANEL_REPO_URL:-https://github.com/lindenau-cedix/remote-panel.git}"
SECRET_FALLBACK="c01f98f685f5f631cc156139bb21804faa816a1fe9d09c03606066e3d1ecc459"
APP_DIR="/opt/panel"

say() { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Pre-flight: tools, hostname, DNS
# ---------------------------------------------------------------------------

say "Pre-flight"
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-venv python3-dev build-essential caddy sudo git
which python3 caddy sudo git || die "missing tools after install"

HOST_FQDN="$(hostname -f 2>/dev/null || hostname)"
echo "Hostname: $HOST_FQDN"
dig +short "$HOST_FQDN" | head -1 || true

# ---------------------------------------------------------------------------
# Phase 1.1 — panel user + dirs
# ---------------------------------------------------------------------------

say "Phase 1.1 — create panel user"
if ! id -u panel >/dev/null 2>&1; then
    sudo useradd --system --shell /usr/sbin/nologin --home "$APP_DIR" \
                 --create-home panel
fi
sudo mkdir -p "$APP_DIR" /etc/panel
sudo chown panel:panel "$APP_DIR"

# ---------------------------------------------------------------------------
# Phase 1.2 — checkout
# ---------------------------------------------------------------------------

say "Phase 1.2 — checkout repo to /opt/panel/repo"
if [ ! -d "$APP_DIR/repo/.git" ]; then
    sudo -u panel git clone "$REPO_URL" "$APP_DIR/repo"
fi
cd "$APP_DIR/repo"
sudo chown -R panel:panel "$APP_DIR/repo"

# ---------------------------------------------------------------------------
# Phase 1.3 — venv + deps
# ---------------------------------------------------------------------------

say "Phase 1.3 — build venv"
if [ ! -x "$APP_DIR/.venv/bin/uvicorn" ]; then
    sudo -u panel python3 -m venv "$APP_DIR/.venv"
    sudo -u panel "$APP_DIR/.venv/bin/pip" install --quiet \
        -r "$APP_DIR/repo/server/requirements.txt"
fi
"$APP_DIR/.venv/bin/uvicorn" --version

# ---------------------------------------------------------------------------
# Phase 1.4 — whitelist (only sim24-bot, mirroring deploy/docker one)
# ---------------------------------------------------------------------------

say "Phase 1.4 — write /opt/panel/whitelist.json"
sudo tee "$APP_DIR/whitelist.json" >/dev/null <<'JSON'
{
  "commands": [
    {
      "id": "sim24-bot",
      "name": "Bock datavolume",
      "description": "Refreshes sim24 unlimited data usage.",
      "argv": ["/usr/local/bin/sim24", "book"],
      "cwd": null,
      "env": {},
      "timeout_seconds": 120
    }
  ]
}
JSON
sudo chown panel:panel "$APP_DIR/whitelist.json"
sudo chmod 0640 "$APP_DIR/whitelist.json"

# ---------------------------------------------------------------------------
# Phase 1.5 — secret in /etc/panel/env
# ---------------------------------------------------------------------------

say "Phase 1.5 — /etc/panel/env (secret + paths)"
DOCKER_SECRET="$(sudo grep '^PANEL_SECRET=' "$APP_DIR/repo/deploy/docker/.env" 2>/dev/null \
                 | cut -d= -f2 || true)"
if [ -z "${DOCKER_SECRET:-}" ]; then
    echo "WARN: deploy/docker/.env missing PANEL_SECRET — using fallback from chat history."
    DOCKER_SECRET="$SECRET_FALLBACK"
fi
sudo tee /etc/panel/env >/dev/null <<EOF
PANEL_SECRET=$DOCKER_SECRET
EOF
sudo chown root:panel /etc/panel/env
sudo chmod 0640 /etc/panel/env

# Note: PANEL_WHITELIST_PATH / PANEL_AUDIT_PATH / PYTHONPATH / WorkingDirectory
# are baked into the unit file itself (server/systemd/remote-panel.service,
# updated by Phase 5). Don't add them here.

# ---------------------------------------------------------------------------
# Phase 1.6 — sudoers
# ---------------------------------------------------------------------------

say "Phase 1.6 — install /etc/sudoers.d/panel"
sudo install -m 0440 "$APP_DIR/repo/server/sudoers.d/panel.example" \
                   /etc/sudoers.d/panel
sudo visudo -c -f /etc/sudoers.d/panel \
    || die "sudoers parse error — fix /etc/sudoers.d/panel before continuing"

# ---------------------------------------------------------------------------
# Phase 1.7 — systemd unit (no override needed; unit is self-contained)
# ---------------------------------------------------------------------------

say "Phase 1.7 — install systemd unit"
sudo cp "$APP_DIR/repo/server/systemd/remote-panel.service" \
        /etc/systemd/system/remote-panel.service
sudo systemctl daemon-reload
sudo systemctl enable --now remote-panel
sleep 1
sudo systemctl is-active remote-panel \
    || die "remote-panel not active; check: journalctl -u remote-panel -n 30"

# ---------------------------------------------------------------------------
# Phase 1.8 — local-loopback smoke test
# ---------------------------------------------------------------------------

say "Phase 1.8 — curl 127.0.0.1:8088/healthz"
curl -sf http://127.0.0.1:8088/healthz \
    | tee /dev/stderr \
    | grep -q '"ok": true' \
    || die "healthz did not return ok:true"
curl -sf http://127.0.0.1:8088/buttons | python3 -m json.tool

# ---------------------------------------------------------------------------
# Phase 1.9 — Caddy in front
# ---------------------------------------------------------------------------

say "Phase 1.9 — install Caddyfile"
sudo mkdir -p /etc/caddy/Caddyfile.d
sudo cp "$APP_DIR/repo/deploy/Caddyfile.example" \
        /etc/caddy/Caddyfile.d/remote-panel.caddy
sudo sed -i "s/panel\.example\.com/$HOST_FQDN/g" \
            /etc/caddy/Caddyfile.d/remote-panel.caddy

# If global Caddyfile already imports /etc/caddy/Caddyfile.d/, reload alone is
# enough. Otherwise, write the global to import. Try the safer import-path
# approach first and fall back to a direct write if it's not already set up.
if ! grep -q 'Caddyfile\.d' /etc/caddy/Caddyfile 2>/dev/null; then
    sudo tee /etc/caddy/Caddyfile >/dev/null <<'CADDY'
import /etc/caddy/Caddyfile.d/*.caddy
CADDY
fi
sudo systemctl reload caddy
sudo journalctl -u caddy -n 20 --no-pager | tail -10

# ---------------------------------------------------------------------------
# Phase 1.10 — smoke through Caddy
# ---------------------------------------------------------------------------

say "Phase 1.10 — curl https://$HOST_FQDN/healthz"
sleep 5   # let ACME finish if it just started
curl -sf "https://$HOST_FQDN/healthz" \
    | tee /dev/stderr \
    | grep -q '"ok": true' \
    || die "healthz via Caddy did not return ok:true (ACME may still be in progress; re-run later)"
curl -sf "https://$HOST_FQDN/buttons" | python3 -m json.tool

# ---------------------------------------------------------------------------
# Phase 2 — sim24 binary must exist on the host
# ---------------------------------------------------------------------------

say "Phase 2 — /usr/local/bin/sim24 must be present on host"
if [ ! -x /usr/local/bin/sim24 ]; then
    die "/usr/local/bin/sim24 missing — install or copy it before continuing.
The bind-mount we previously used inside the panel-host container is gone.
The whitelist expects this binary at exactly this path."
fi

# Quick test as the panel user (no sudo)
echo "Testing sim24 as panel user..."
sudo -u panel /usr/local/bin/sim24 book \
    || die "sim24 failed as user 'panel' — fix permissions or its dependencies before continuing"

# ---------------------------------------------------------------------------
# Phase 3 — tear down docker stack
# ---------------------------------------------------------------------------

say "Phase 3 — tear down docker stack"
cd "$APP_DIR/repo"

# Make sure bare-metal is healthy one more time before we tear docker down.
curl -sf "https://$HOST_FQDN/healthz" | grep -q '"ok": true' \
    || die "bare-metal healthz failed — DO NOT tear down docker; debug first"

docker compose -f deploy/docker/docker-compose.yml down \
    || true
docker volume rm panel-audit caddy-data caddy-config 2>/dev/null || true
docker image rm remote-panel:dev remote-panel-host:dev caddy:2 2>/dev/null || true

echo
echo "After Phase 3, Caddy is still proxying to 127.0.0.1:8088 — the bare-metal"
echo "uvicorn. Verify:"
curl -sf "https://$HOST_FQDN/healthz" | grep -q '"ok": true' \
    || die "healthz broke after docker tear-down"
echo "OK."

# ---------------------------------------------------------------------------
# Phase 4 — phone-side verification checklist (no commands; report only)
# ---------------------------------------------------------------------------

say "Phase 4 — phone-side verification"
cat <<'EOF'

Run these manually:

  # Audit log is the canonical source of truth:
  sudo tail -n 5 /opt/panel/audit.jsonl | jq .

  # Open the app on the phone, tap the "Bock datavolume" button.
  # Expect: result dialog with exit_code: 0 and stdout from sim24-book.

  # If the phone shows an HTTP 401 (bad signature), the secret in
  # /etc/panel/env doesn't match what the phone has. Re-paste the
  # phone's secret in Settings → Update Secret, OR re-paste the
  # VPS's secret into the phone.

  # If the phone shows 500 with FileNotFoundError on /usr/local/bin/sim24,
  # the binary isn't actually on the host filesystem even though -x said
  # yes. Could be a symlink pointing off-host that's broken; check:
  #   sudo -u panel readlink -f /usr/local/bin/sim24
  #   sudo -u panel /usr/local/bin/sim24 book   #  with full resolved path

EOF

say "Migration complete"
echo "Repo changes (not yet committed):"
git status --short
