# Deploying Remote Panel

This file covers the production deployment on a Debian 12+ server.

## Prereqs (Debian)

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-dev build-essential \
                    caddy sudo
```

## Create the low-privilege user

```bash
sudo useradd --system --shell /usr/sbin/nologin --home /opt/panel --create-home panel
```

## Install the application

```bash
sudo mkdir -p /opt/panel
sudo chown panel:panel /opt/panel
sudo -u panel git clone <your-repo-url> /opt/panel/repo
cd /opt/panel/repo
sudo -u panel python3 -m venv /opt/panel/.venv
sudo -u panel /opt/panel/.venv/bin/pip install -r server/requirements.txt
sudo cp server/whitelist.json /opt/panel/whitelist.json
sudo chown panel:panel /opt/panel/whitelist.json
sudo chmod 0640 /opt/panel/whitelist.json
```

## Set the shared secret

```bash
sudo mkdir -p /etc/panel
sudo touch /etc/panel/env
sudo chmod 0640 /etc/panel/env
sudo chown root:panel /etc/panel/env

# Generate the secret — 32 bytes = 64 hex chars.
SECRET=$(openssl rand -hex 32)
echo "PANEL_SECRET=$SECRET" | sudo tee /etc/panel/env > /dev/null
echo "stored PANEL_SECRET=$SECRET in /etc/panel/env — copy it to your phone now"
```

## Drop in the sudoers snippet

```bash
sudo install -m 0440 server/sudoers.d/panel.example /etc/sudoers.d/panel
sudo visudo -c -f /etc/sudoers.d/panel   # must say "parsed OK"
```

Then edit `/etc/sudoers.d/panel` to add lines for every privileged command
in your `whitelist.json`. After editing: `sudo visudo -c -f /etc/sudoers.d/panel`
to confirm it still parses.

## Install the systemd unit

```bash
sudo cp server/systemd/remote-panel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now remote-panel
sudo systemctl status remote-panel   # should be active (running)
```

## Reverse proxy with Caddy

```bash
sudo cp deploy/Caddyfile.example /etc/caddy/Caddyfile.d/remote-panel.caddy
# Edit the hostname, then:
sudo systemctl reload caddy
```

Caddy will request a Let's Encrypt certificate on first boot. Verify:

```bash
curl -sf https://panel.example.com/healthz
# {"ok": true}
```

## Add a new command

1. Edit `/opt/panel/whitelist.json` (validated on every reload — bad entries
   keep the old list active).
2. If it needs `sudo`, add the matching line to `/etc/sudoers.d/panel` and run
   `sudo visudo -c -f /etc/sudoers.d/panel`.
3. `sudo systemctl kill -s SIGHUP remote-panel` (or `reload` if you prefer).
4. `journalctl -u remote-panel -n 20` to confirm the reload logged how many
   commands are now active.

## Rotate the secret

1. Generate a new one: `NEW=$(openssl rand -hex 32)`.
2. Update `/etc/panel/env` and restart: `sudo systemctl restart remote-panel`.
3. In the Android app: Settings → Update Secret.

## Read the audit log

```bash
sudo tail -n 50 /opt/panel/audit.jsonl | jq .
```

Each line is a JSON object with `ts` (unix seconds) and an `event`. Useful
`event` values: `auth_fail`, `replay`, `not_whitelisted`, `exec.start`,
`exec.done`, `rate_limited`, `whitelist.reload`.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `400 signature mismatch` | Clock skew or wrong secret | Check phone's time; verify secret in app vs. server env |
| `400 nonce replayed` | Network retry | The Android app retries once on timeout; ignore |
| `429 rate limited` | Burst from the app | Default 30 req/min — lower in `Settings` if needed |
| `408 timeout` | Command took too long | Bump `timeout_seconds` in whitelist.json |
| Service won't start | `PANEL_SECRET` not set / too short | Check `/etc/panel/env` permissions (mode 0640, owner `root:panel`) |
| `sudoers` parse error | Edited sudoers file broke | Run `visudo -c`; service will refuse to start otherwise |