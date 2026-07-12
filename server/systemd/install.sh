#!/bin/bash
# install.sh
#
# Install Remote Panel as a systemd service on a Debian 12+ bare-metal host.
#
# This is the install path described in `deploy/README.md` — prerequisites
# plus the systemd unit drop-in. It is idempotent: re-runs skip work already
# done and re-apply the unit + (re)enable it.
#
# What this script does NOT do:
#   * Install Caddy — that's `deploy/Caddyfile.example`, separate step.
#   * Re-pair the Android app — the existing PANEL_SECRET in
#     /etc/panel/env is preserved across re-runs.
#   * Touch the docker-compose stack — see `migrate-to-bare-metal.sh` if
#     you want to migrate off docker.
#
# Pre-flight (the script does not check these for you):
#   * You have root or passwordless sudo.
#   * This repo is checked out somewhere accessible. By default we look for
#     /opt/panel/repo (set REPO_DIR to override).
#   * No service named `remote-panel` is already running under a different
#     user or WorkingDirectory than the one this script installs.

set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/panel/repo}"
APP_DIR="${APP_DIR:-/opt/panel}"
SERVICE_NAME="remote-panel"
SERVICE_SRC="$REPO_DIR/server/systemd/$SERVICE_NAME.service"
SERVICE_DST="/etc/systemd/system/$SERVICE_NAME.service"
SECRET_DIR="/etc/panel"
SECRET_FILE="$SECRET_DIR/env"
WHITELIST_SRC="$REPO_DIR/server/whitelist.json"
WHITELIST_DST="$APP_DIR/whitelist.json"
AUDIT_FILE="$APP_DIR/audit.jsonl"
SUDOERS_SRC="$REPO_DIR/server/sudoers.d/panel.example"
SUDOERS_DST="/etc/sudoers.d/panel"
VENV="$APP_DIR/.venv"

say() { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

[ -f "$SERVICE_SRC" ] || die "missing $SERVICE_SRC — set REPO_DIR or check out the repo first."

# ---------------------------------------------------------------------------
# Pre-flight: tools
# ---------------------------------------------------------------------------

say "Pre-flight"
if ! command -v systemctl >/dev/null 2>&1; then
    die "systemctl not found — this script targets systemd hosts (Debian 12+)."
fi
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-venv python3-dev build-essential sudo
which python3 systemctl sudo || die "missing tools after install"

# ---------------------------------------------------------------------------
# Step 1 — low-privilege user + dirs
# ---------------------------------------------------------------------------

say "Step 1 — panel user + dirs"
if ! id -u panel >/dev/null 2>&1; then
    sudo useradd --system --shell /usr/sbin/nologin --home "$APP_DIR" \
                 --create-home panel
fi
sudo mkdir -p "$APP_DIR" "$SECRET_DIR"
sudo chown panel:panel "$APP_DIR"
sudo chown root:panel "$SECRET_DIR"
sudo chmod 0750 "$SECRET_DIR"

# ---------------------------------------------------------------------------
# Step 2 — code checkout
# ---------------------------------------------------------------------------

say "Step 2 — code at $REPO_DIR"
if [ ! -d "$REPO_DIR/.git" ]; then
    if [ -n "${PANEL_REPO_URL:-}" ]; then
        sudo -u panel git clone "$PANEL_REPO_URL" "$REPO_DIR"
    else
        die "$REPO_DIR is not a git checkout. Clone the repo there first (or set PANEL_REPO_URL before re-running)."
    fi
fi
[ -f "$REPO_DIR/server/whitelist.json" ] || die "$REPO_DIR does not look like a remote-panel checkout"
sudo chown -R panel:panel "$REPO_DIR"

# ---------------------------------------------------------------------------
# Step 3 — venv + deps
# ---------------------------------------------------------------------------

say "Step 3 — venv at $VENV"
if [ ! -x "$VENV/bin/uvicorn" ]; then
    sudo -u panel python3 -m venv "$VENV"
    sudo -u panel "$VENV/bin/pip" install --quiet -r "$REPO_DIR/server/requirements.txt"
fi
"$VENV/bin/uvicorn" --version

# ---------------------------------------------------------------------------
# Step 4 — whitelist (init only; preserve any edits already on disk)
# ---------------------------------------------------------------------------

say "Step 4 — whitelist at $WHITELIST_DST"
if [ ! -f "$WHITELIST_DST" ]; then
    sudo install -m 0640 -o panel -g panel "$WHITELIST_SRC" "$WHITELIST_DST"
else
    echo "  $WHITELIST_DST already exists — leaving it alone (edit + SIGHUP to reload)."
fi

# ---------------------------------------------------------------------------
# Step 5 — secret in /etc/panel/env
#
# Preserve an existing secret across re-runs so the Android app keeps
# pairing. Only generate one if the file is missing or empty.
# ---------------------------------------------------------------------------

say "Step 5 — secret at $SECRET_FILE"
EXISTING_SECRET="$(sudo awk -F= '/^PANEL_SECRET=/{print $2}' "$SECRET_FILE" 2>/dev/null || true)"
if [ -z "$EXISTING_SECRET" ]; then
    SECRET="$(openssl rand -hex 32)"
    sudo tee "$SECRET_FILE" >/dev/null <<EOF
PANEL_SECRET=$SECRET
EOF
    sudo chown root:panel "$SECRET_FILE"
    sudo chmod 0640 "$SECRET_FILE"
    echo "  Generated new PANEL_SECRET (32 bytes / 64 hex chars)."
    echo "  Copy it into the Android app now: Settings → Update Secret."
    echo "  Secret: $SECRET"
else
    echo "  $SECRET_FILE already has PANEL_SECRET — preserved (Android app stays paired)."
fi

# ---------------------------------------------------------------------------
# Step 6 — sudoers snippet (optional but expected for any privileged cmd)
# ---------------------------------------------------------------------------

say "Step 6 — /etc/sudoers.d/panel"
if [ -f "$SUDOERS_SRC" ]; then
    sudo install -m 0440 "$SUDOERS_SRC" "$SUDOERS_DST"
    sudo visudo -c -f "$SUDOERS_DST" \
        || die "sudoers parse error — fix $SUDOERS_DST before continuing"
else
    echo "  no $SUDOERS_SRC — skipping (you'll need to author your own sudoers file)."
fi

# ---------------------------------------------------------------------------
# Step 7 — systemd unit
#
# The shipped unit hard-codes WorkingDirectory=/opt/panel/repo,
# Environment=PYTHONPATH / PANEL_WHITELIST_PATH / PANEL_AUDIT_PATH, and
# binds uvicorn to 127.0.0.1:8088. If APP_DIR differs from /opt/panel
# or REPO_DIR differs from /opt/panel/repo, we tell the user instead of
# silently rewriting the unit.
# ---------------------------------------------------------------------------

say "Step 7 — systemd unit"
if [ "$APP_DIR" != "/opt/panel" ] || [ "$REPO_DIR" != "/opt/panel/repo" ]; then
    die "unit hard-codes /opt/panel and /opt/panel/repo — install at the default paths or edit the unit before re-running."
fi
sudo install -m 0644 "$SERVICE_SRC" "$SERVICE_DST"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"
sleep 1
sudo systemctl is-active "$SERVICE_NAME" \
    || die "$SERVICE_NAME not active — check: journalctl -u $SERVICE_NAME -n 30"

# ---------------------------------------------------------------------------
# Step 8 — smoke test on the loopback (Caddy sits in front of this later)
# ---------------------------------------------------------------------------

say "Step 8 — curl 127.0.0.1:8088/healthz"
curl -sf http://127.0.0.1:8088/healthz | tee /dev/stderr | grep -q '"ok": true' \
    || die "healthz did not return ok:true"
curl -sf http://127.0.0.1:8088/buttons | python3 -m json.tool

# ---------------------------------------------------------------------------
# Step 9 — Caddy reverse proxy (optional but expected in prod)
# ---------------------------------------------------------------------------

say "Step 9 — Caddy reverse proxy"
if [ -f "$REPO_DIR/deploy/Caddyfile.example" ]; then
    sudo mkdir -p /etc/caddy/Caddyfile.d
    sudo install -m 0644 "$REPO_DIR/deploy/Caddyfile.example" \
                       /etc/caddy/Caddyfile.d/remote-panel.caddy
    HOST_FQDN="$(hostname -f 2>/dev/null || hostname)"
    sudo sed -i "s/panel\.example\.com/$HOST_FQDN/g" \
               /etc/caddy/Caddyfile.d/remote-panel.caddy
    if ! grep -q 'Caddyfile\.d' /etc/caddy/Caddyfile 2>/dev/null; then
        sudo tee /etc/caddy/Caddyfile >/dev/null <<'CADDY'
import /etc/caddy/Caddyfile.d/*.caddy
CADDY
    fi
    sudo systemctl reload caddy
    echo "  Caddyfile at /etc/caddy/Caddyfile.d/remote-panel.caddy (hostname: $HOST_FQDN)"
    echo "  Verify once ACME finishes: curl -sf https://$HOST_FQDN/healthz"
else
    echo "  no $REPO_DIR/deploy/Caddyfile.example — install Caddy manually."
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

say "Install complete"
cat <<'EOF'

Next steps:
  * Confirm /etc/panel/env is mode 0640, owner root:panel.
  * Edit /opt/panel/whitelist.json to list the commands you want, and add
    matching lines to /etc/sudoers.d/panel for any that need privilege.
    Then: sudo systemctl kill -s SIGHUP remote-panel   (or 'restart' / 'reload').
  * On the phone: Settings → Update Secret, paste the secret printed above.
  * Verify: curl -sf https://<your-hostname>/healthz

Service management:
  systemctl status  remote-panel
  journalctl  -u    remote-panel -f
  systemctl reload  remote-panel        # whitelist reload (also: kill -s HUP)

EOF
