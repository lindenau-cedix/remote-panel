# Remote Panel

> Tap a button on Android → server runs a pre-approved shell command over HTTPS.

`Remote Panel` is a one-way remote control system. An Android phone sends signed
webhooks to a small FastAPI server, which substitutes the matching argv list
from a JSON whitelist and runs it. **No SSH, no agent forwarding, no remote
shell.** The server is the only thing that can run anything; the phone only
says *which command id* (e.g. `restart-nginx`).

```
┌──────────────────┐  HTTPS POST + HMAC-SHA256   ┌──────────────────┐  argv[]   ┌────────────┐
│  Android App     │ ─────────────────────────▶ │  Webhook Server  │ ────────▶ │ Command    │
│  (Remote Panel)  │  X-Panel-Signature etc.     │  (FastAPI)       │  shell=F  │ whitelisted│
└──────────────────┘                             └──────────────────┘           └────────────┘
```

## What's in this repo

| Path | Purpose |
|---|---|
| `server/` | FastAPI webhook receiver + tests |
| `android/` | Kotlin + Jetpack Compose app |
| `deploy/` | Caddyfile + bare-metal deployment walkthrough |
| `deploy/docker/` | Dockerfile + docker-compose.yml + sidecar image + walkthrough |
| `Makefile` | `test`, `run-server`, `build-apk`, `smoke`, `docker-build`, `docker-up`, `docker-down`, `docker-reload-whitelist`, `docker-secret-rotate` |

## Threat model

The phone is treated as untrusted. The network is treated as hostile. Even if
both are fully compromised, an attacker can only trigger commands the admin
already pre-approved in `whitelist.json`. The shared secret never leaves the
keystore on the phone and `/etc/panel/env` on the server. There is no way for
the server to call back to the phone, no shell on the server that remote
parties can land in, and the argv list is fully owned by the server — the phone
literally cannot send an arbitrary command.

Out of scope: physical access to the server, OS-level compromise of the
server, denial of service (we rate-limit but don't try to stop motivated botnets).

## Generate the shared secret

```bash
openssl rand -hex 32          # copy this — it's the only secret both sides need
```

You'll paste this into the phone once at setup. The server reads it from
`/etc/panel/env` (`PANEL_SECRET=...`) on the bare-metal install, or from
`deploy/docker/.env` (`PANEL_SECRET=...`) on the Docker install.

## Pick a deployment style

| | Bare metal (`systemd` + `Caddy`) | Docker (`docker compose`) |
|---|---|---|
| Install path | `./deploy/README.md` | `./deploy/docker/README.md` |
| Privilege model | `systemd` sandboxing (`ProtectSystem=strict`, `NoNewPrivileges`, etc.) on a single service | `cap_drop: ALL` on three containers; privilege boundary is the `docker.sock` + a privileged `panel-host` sidecar |
| Requires | Debian 12+, `python3-venv`, `caddy`, `sudo` | Docker Engine 24+ with Compose v2, a host running systemd |
| Hot reload | `systemctl kill -s SIGHUP remote-panel` | `docker kill -s HUP remote-panel` |
| Secret rotation | edit `/etc/panel/env` + restart | edit `deploy/docker/.env` + `make docker-secret-rotate` |

Both paths run the same `server/` code; only the deploy artifacts differ.
The Docker path uses `server/docker_rewrite.py` to rewrite each
whitelist argv into `docker exec panel-host <argv>` at container start.
The rewriter has 9 unit tests in `server/tests/test_docker_rewrite.py`.

## Server setup (bare metal, Debian 12+)

```bash

## Server setup (Debian 12+)

```bash
sudo apt install -y python3 python3-venv python3-dev build-essential caddy sudo

sudo useradd --system --shell /usr/sbin/nologin --home /opt/panel --create-home panel
sudo mkdir -p /opt/panel /etc/panel
sudo chown panel:panel /opt/panel

sudo -u panel git clone <this repo> /opt/panel/repo
cd /opt/panel/repo
sudo -u panel python3 -m venv /opt/panel/.venv
sudo -u panel /opt/panel/.venv/bin/pip install -r server/requirements.txt
sudo cp server/whitelist.json /opt/panel/whitelist.json
sudo chown panel:panel /opt/panel/whitelist.json
sudo chmod 0640 /opt/panel/whitelist.json
```

Set the secret (the file is read by systemd):

```bash
sudo bash -c 'echo "PANEL_SECRET=$(openssl rand -hex 32)" > /etc/panel/env'
sudo chmod 0640 /etc/panel/env
sudo chown root:panel /etc/panel/env
```

Drop in the systemd unit, sudoers snippet, and Caddyfile:

```bash
sudo install -m 0644 server/systemd/remote-panel.service /etc/systemd/system/
sudo install -m 0440 server/sudoers.d/panel.example      /etc/sudoers.d/panel
sudo cp deploy/Caddyfile.example /etc/caddy/Caddyfile.d/remote-panel.caddy
# edit the hostname in /etc/caddy/Caddyfile.d/remote-panel.caddy

sudo systemctl daemon-reload
sudo systemctl enable --now remote-panel
sudo systemctl reload caddy

curl -sf https://panel.example.com/healthz   # → {"ok":true}
```

## Build the Android APK

The phone doesn't need an account or Play Store access — sideload is fine.

```bash
cd android
./gradlew assembleDebug
# adb install app/build/outputs/apk/debug/app-debug.apk
```

(You'll need JDK 17 + Android SDK with build-tools 34.5.0 on the build
machine. Tested with AGP 8.5.2, Kotlin 1.9.24, Compose BOM 2024.06.00,
minSdk 26, targetSdk 34.)

## First-run in-app setup

1. Open "Remote Panel" — the **Setup** screen appears.
2. Server URL: `https://panel.example.com` (or `http://10.0.2.2:8088` for
   emulator).
3. Shared secret: paste the hex string from `openssl rand -hex 32`.
4. Tap **Save**. You'll land on the panel.

The secret is stored in `EncryptedSharedPreferences`. No analytics, no
crashlytics, no telemetry — verified in `AndroidManifest.xml` and the source.

## Add a new command

1. Edit `/opt/panel/whitelist.json` — append a new object to `commands[]`.
   `argv` is matched exactly; the phone only knows `id`.
2. If the command needs `sudo`, add a matching line to `/etc/sudoers.d/panel`
   and run `sudo visudo -c -f /etc/sudoers.d/panel` to verify it parses.
3. Reload the running server: `sudo systemctl kill -s SIGHUP remote-panel`.
   Bad entries are rejected; the previous list stays active on failure.
4. (Optional) Add the same `id/name/description` to
   `android/app/src/main/assets/buttons.json` and rebuild the APK — or wait
   until v0.2 lands `/buttons` refresh.

Example — restart a custom service:

```jsonc
{
  "id": "restart-myapp",
  "name": "Restart MyApp",
  "description": "Restart the userland service",
  "argv": ["sudo", "-n", "systemctl", "restart", "myapp.service"],
  "timeout_seconds": 15
}
```

And the matching sudoers line:

```
panel ALL=(root) NOPASSWD: /usr/bin/systemctl restart myapp.service
```

## Rotate the shared secret

```bash
NEW=$(openssl rand -hex 32)
sudo sed -i "s/^PANEL_SECRET=.*/PANEL_SECRET=$NEW/" /etc/panel/env
sudo systemctl restart remote-panel
# Open the app → ⚙ Settings → re-enter the new secret
```

Old requests signed with the previous secret will start returning
`{"ok": false, "error": "signature mismatch"}`. That's correct.

## Reading the audit log

```bash
sudo tail -n 50 /opt/panel/audit.jsonl | jq .
```

Each line is JSON with a `ts` (unix seconds) and an `event`. Events you'll see:

| event | meaning |
|---|---|
| `exec.start` | command starting (records `command_id`, `argv0`) |
| `exec.done` | command finished (`exit_code`, `duration_ms`, `timed_out`) |
| `auth_fail` | bad signature, missing header, bad timestamp, … |
| `replay` | nonce reused within TTL |
| `not_whitelisted` | `command_id` not in the config (403) |
| `rate_limited` | per-IP burst exceeded (429) |
| `bad_body` | JSON parse error or schema violation |
| `nonce_mismatch` | header `X-Panel-Nonce` ≠ `body.nonce` |
| `whitelist.reload` | SIGHUP reload — `ok: true/false` |

To keep audit size sane, no body content is logged — only the `command_id` and
exit code. Add a logrotate job if needed:

```
/etc/logrotate.d/remote-panel:
    /opt/panel/audit.jsonl {
        daily
        rotate 30
        compress
        missingok
        notifempty
        copytruncate
    }
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `{"error":"signature mismatch"}` | Phone clock drifted, or secret rotated | Check phone's "automatic time"; Settings → re-enter secret |
| `{"error":"timestamp outside ±300s window"}` | NTP drift on the server | `timedatectl status`; install `chrony` if needed |
| `{"error":"nonce replayed"}` | Network retry triggered twice | One-shot — ignore. The Android app's `runCommand` already retries on transient errors; if you see this on the second tap, the nonce collided by 1-in-2^128 chance |
| `429 rate limited` | > 30 req/min from one IP | Bump `PANEL_RATE_CAPACITY` and `PANEL_RATE_REFILL_PER_SEC` and SIGHUP-reload (note: not currently hot-reloadable — restart the service) |
| `408` with `timed_out: true` | Command ran longer than `timeout_seconds` | Increase `timeout_seconds` in `whitelist.json` |
| Service won't start with `PANEL_SECRET` message | Secret unset or < 16 chars | Check `/etc/panel/env` mode (`0640`, owner `root:panel`) |
| `sudo: a password is required` | Sudoers file missing or doesn't match the argv | `visudo -c -f /etc/sudoers.d/panel`; the exact command, not a wildcard |

## Security invariants the project enforces

If you ever find yourself reaching for `shell=True`, `os.system`, `eval`, or
`exec(<string>)` on the server — **stop and refactor**. There is no legitimate
use of these in `server/`. The repo contains a make-time grep you can re-run:

```bash
grep -RIn --exclude-dir=.git -E 'shell=True|os\.system|eval\(|exec\(' server/ android/
```

Only safe matches should appear (e.g. `eval` in a parser, with a justifying
comment). Currently there are zero matches.

### The four things that keep this from becoming an RCE

1. **HMAC-SHA256 over `timestamp.body`** — the phone proves it holds the
   secret. No secret → no request.
2. **5-minute timestamp window + nonce store** — replayed requests are rejected.
3. **Argv whitelist with exact match** — the server picks the command, not the
   wire. Phone has no influence over which binary runs or with which args.
4. **`shell=False` everywhere** — there's no string-to-shell surface area to
   exploit.

Combined, they make the phone a button-pressing remote that can only press
buttons that already exist.

## License

MIT — see `LICENSE`. Third-party dependencies retain their own licenses; the
locked versions are in `server/requirements.txt` and
`android/app/build.gradle.kts`.
