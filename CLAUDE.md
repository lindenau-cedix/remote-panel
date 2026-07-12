# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Remote Panel — an Android app that sends signed HTTPS webhooks to a small FastAPI server, which substitutes a matching argv list from a JSON whitelist and runs it. The phone is untrusted; the server owns the argv. See `README.md` for the full threat model.

## Commands

The Makefile is the entry point for everything. Common targets:

```bash
make test                            # server tests (pytest, 61 tests)
make run-server                      # uvicorn on 127.0.0.1:8088 (PANEL_SECRET must be set)
make smoke                           # curl /healthz on the running server
make build-apk                       # assemble debug APK (needs JDK 17 + Android SDK)
make docker-up                       # build + start the 3-service compose stack
make docker-down                     # stop + remove containers (volumes persist)
make docker-logs                     # tail logs from all 3 services
make docker-reload-whitelist         # docker kill -s HUP remote-panel (SIGHUP reload)
make docker-secret-rotate            # generate new secret, update .env, restart panel
```

### Running a single test

The `server/` tests use `pytest.ini` with `asyncio_mode = auto` and `testpaths = tests`. They require `PANEL_SECRET` to be set before import (the test fixture does `os.environ.setdefault(...)`). From the repo root:

```bash
cd server && PYTHONPATH=.. ../.venv/bin/pytest -q tests/test_app.py::test_hook_success -v
```

### Setting the secret locally

`server/app.py:make_app` refuses to start if `PANEL_SECRET` is unset or shorter than 16 chars. For local runs: `export PANEL_SECRET=$(openssl rand -hex 32)`.

## Architecture

### Server request flow (`server/`)

The wire protocol is HMAC-SHA256 over `f"{timestamp}.{body}"` with a separate nonce header that must match `body.nonce`. One process, four pieces:

- `app.py` — FastAPI app + the `/healthz`, `/buttons`, `/hook` endpoints. `make_app(settings)` builds the app; the module-level `app = _build_default_app()` lets `uvicorn server.app:app` work. SIGHUP reloads the whitelist via the `lifespan` context manager.
- `signer.py` — `verify_signature(...)`. Constant-time compare via `hmac.compare_digest`. ±300s timestamp window.
- `whitelist.py` — `load_whitelist(path)` parses + validates `whitelist.json`. Validation rules: ids are kebab-case `^[a-z0-9][a-z0-9-]{0,63}$`, argv[0] is absolute or in `ALLOWED_BASENAMES = {"sudo", "systemctl"}`, cwd absolute, env values strings, `timeout_seconds` > 0. Bad whitelist → `WhitelistError`, old list stays active on SIGHUP failure.
- `executor.py` — `subprocess.run(spec.argv, shell=False, ...)`. Never `shell=True`, never string exec. The argv list comes from the whitelist, not from the request body — this is the core invariant.
- `ratelimit.py` — in-process token bucket per IP + nonce store with TTL eviction. Single-process only; replace with Redis if scaling horizontally.
- `audit.py` — append-only JSONL with a line-buffered file handle and a module-level singleton (`audit.record(...)` is a no-op if no default is set, so tests can swap it).
- `config.py` — `pydantic_settings.BaseSettings` with `env_prefix="PANEL_"`. PANEL_SECRET, PANEL_BIND_HOST/PORT, PANEL_WHITELIST_PATH, PANEL_AUDIT_PATH, PANEL_NONCE_TTL_SECONDS, PANEL_RATE_CAPACITY, PANEL_RATE_REFILL_PER_SEC, PANEL_LOG_LEVEL.
- `docker_rewrite.py` — pure-data argv rewriter used only by the Docker entrypoint (see below). Not imported by `server.app`.

### Tests

Five files in `server/tests/` (one per module), plus `test_docker_rewrite.py`. They use `httpx.AsyncClient` with `ASGITransport` — no network socket, no uvicorn needed. The `client` fixture in `test_app.py` builds the app with a temp whitelist + temp audit path.

### Docker deployment (`deploy/docker/`)

Three services, privilege boundary is the docker socket:

- `panel` — FastAPI app. `uid 999`, `cap_drop: ALL`, `no-new-privileges`, `read_only: true`. Has only `/usr/bin/docker` (no `sudo`, no `systemctl`, no shell binaries beyond what the slim base carries — defense in depth against a regression to `shell=True`). Mounts `/var/run/docker.sock`.
- `panel-host` — privileged sidecar. Runs as root with `cap_drop: ALL` then an explicit cap list (CAP_AUDIT_WRITE for sudo, CAP_SETUID/SETGID for sudo itself, CAP_DAC_OVERRIDE for /etc/shadow). Mounts `/run/systemd:ro`, `/usr/bin/sudo:ro`, `/usr/bin/systemctl:ro`, `/etc/sudoers.d:ro`. Holds the sudoers snippet COPY'd from `server/sudoers.d/panel.example` (validated by `visudo -c` at build time). Stays alive with `sleep infinity` so `docker exec` has a target.
- `caddy` — TLS edge. `caddy:2`, ports 80/443, volumes for cert + config storage.

The argv rewriter: `server/docker_entrypoint.sh` reads `whitelist.json` (bind-mounted `:ro` from `deploy/docker/whitelist.json`), runs `server.docker_rewrite` to prepend `["/usr/bin/docker","exec","-u","root","--","panel-host", ...argv]` to every command, writes the result to a tmpfs volume, validates it through `server.whitelist.load_whitelist` (loud failure on bad rewrites), then `exec`s uvicorn. The rewriter has 9 unit tests.

Hot reload under Docker: `make docker-reload-whitelist` sends SIGHUP to the panel container. Same in-process reload as the bare-metal path.

The Caddyfiles (`deploy/docker/Caddyfile` + `deploy/Caddyfile.example`) use Caddy v2 only. The earlier v1-style `@blocked not method ...` negation was rewritten as a `route` block with mutually-exclusive `handle` arms for the three allowed endpoints (`POST /hook`, `GET /healthz`, `GET /buttons`) plus a matcher-less catch-all `respond "404 not found" 404`. Both files are validated by `caddy adapt`; both upstreams are `panel:8088` (docker) / `127.0.0.1:8088` (bare metal). The default port for the panel is **8088** (not 8000) — set via `PANEL_BIND_PORT` in `Dockerfile`, `deploy/docker/docker-compose.yml` port mapping `8088:8088`, and the systemd unit's `--port 8088`.

### Bare-metal deployment (`deploy/` + `server/systemd/` + `server/sudoers.d/`)

Systemd unit `server/systemd/remote-panel.service` hardens the process with `ProtectSystem=strict`, `NoNewPrivileges`, `PrivateTmp`, `PrivateDevices`, `RestrictNamespaces`, `MemoryDenyWriteExecute`, etc. The sudoers snippet `server/sudoers.d/panel.example` lists the exact commands the panel user can run with `sudo -n` — wildcards are intentionally avoided. Caddy reverse proxy in `deploy/Caddyfile.example`. Secret lives in `/etc/panel/env` (mode 0640, owner `root:panel`).

### Android (`android/`)

Kotlin + Jetpack Compose. AGP 8.5.2, Kotlin 1.9.24, Compose BOM 2024.06.00, minSdk 26, targetSdk 34. No analytics/crashlytics/telemetry — see `AndroidManifest.xml` and the source.

Data layer under `data/`:

- `UserCommand.kt` — phone-visible metadata for user-authored commands (`id`, `name`, `description`). The id is what the phone sends at run time; argv never leaves the server.
- `UserCommandsStore.kt` — `EncryptedSharedPreferences` in file `user_commands_secure_prefs`, single JSON-encoded `List<UserCommand>` under key `user_commands_json`. Pure-Kotlin `UserCommandLogic` helper in the same file (id-regex matching the server's `ID_PATTERN`, `append`, `removeById`) for JVM unit tests. Exposes `commands: StateFlow<List<UserCommand>>` plus `add` / `delete` / `list`. The user can author any id locally; the server rejects unknown ids at `/hook` time.
- `SecretStore.kt` / `SettingsStore.kt` — `EncryptedSharedPreferences` in file `panel_secure_prefs` for server URL + shared secret. `SecretStore.clear()` wipes the whole file (intentional: resets the connection). The commands store is in a separate file so this `clear()` cannot destroy the user's authored list.

UI under `ui/`: `SetupScreen` (first-run), `PanelScreen` (cards → confirmation dialog → `PanelApi.runCommand`), `ManageCommandsScreen` (list with delete + FAB → add dialog), `AddCommandDialog` (modal form with id/name/description fields and id-regex validation), `EmptyCommandsState`, `ResultDialog`. `MainActivity` holds two navigation flags — `showManage: Boolean` swaps between `PanelScreen` and `ManageCommandsScreen`, and `showAddDialog: Boolean` renders `AddCommandDialog` as a hoisted overlay that works from both screens (the empty-state CTA on `PanelScreen` and the FAB on `ManageCommandsScreen` both flip it). No nav-compose dep. The TopAppBar has a `List` icon (manage commands) and the gear (existing clear-settings path). When commands is empty, `PanelScreen` renders `EmptyCommandsState` instead of a `LazyColumn`.

## Hard invariants

These are non-negotiable; breaking them turns this into an RCE. The repo has a make-time grep you can re-run to check:

```bash
grep -RIn --exclude-dir=.git -E 'shell=True|os\.system|eval\(|exec\(' server/ android/
```

Currently zero matches outside the `NEVER uses shell=True` docstring in `server/executor.py` and one test function name (`test_rewrite_command_prepends_docker_exec`).

1. `shell=False` everywhere in `server/executor.py`. No `os.system`, no `eval`, no `exec(<string>)`.
2. `argv` is always a list from the server-owned whitelist — never built from request data.
3. HMAC signature verification is constant-time (`hmac.compare_digest`).
4. The nonce store rejects replays within TTL.
5. PANEL_SECRET never leaves the phone's keystore and the server's env file/`.env`. Never logged, never echoed in error responses.

## Where to look

- Wire protocol details → `server/signer.py` + `server/app.py::hook`.
- Threat model → `README.md` § "Threat model" + § "The four things that keep this from becoming an RCE".
- Deployment → `deploy/README.md` (bare metal) or `deploy/docker/README.md` (Docker; includes a security checklist).
- Adding a command → `README.md` § "Add a new command" (whitelist + sudoers + SIGHUP reload).
- Audit events → `README.md` § "Reading the audit log" + `server/audit.py`.