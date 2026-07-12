# Remote Panel — Docker deployment

Containerized deployment of the server. Three services:

```
┌──────────────────────────────────────────────────────────────────────┐
│ Host                                                                 │
│                                                                      │
│  ┌──────────────┐   docker exec   ┌────────────────┐                 │
│  │   panel      │ ──────────────▶ │  panel-host    │                 │
│  │   (unpriv)   │                 │  (root, caps↓) │                 │
│  │   :8088      │                 │  sudo,systemctl│                 │
│  └──────┬───────┘                 └────────┬───────┘                 │
│         │ HTTP                             │ systemctl → host systemd│
│         ▼                                  ▼                         │
│  ┌──────────────┐                 /run/systemd (host bind)           │
│  │   caddy      │                                                   │
│  │   :80/:443   │                                                   │
│  └──────────────┘                                                   │
└──────────────────────────────────────────────────────────────────────┘
```

The privilege boundary is the docker socket: only the `panel`
container is mounted to it, and the only thing `panel` does with it
is `docker exec panel-host <argv>`. `panel` itself runs as uid 999
with `cap_drop: [ALL]`.

## Threat model — what's different from the bare-metal install

The bare-metal systemd unit pins the panel user to a hardened
sandbox (`ProtectSystem=strict`, `NoNewPrivileges`, etc.). That
sandbox relies on Linux namespaces and cgroups, which Docker provides
natively — but Docker by default is more permissive (the container
runs as root unless told otherwise, and the docker socket is a
root-equivalent primitive). This setup counters that with:

| Risk | Mitigation |
|---|---|
| Container runs as root | `user: "999:999"` + `cap_drop: [ALL]` |
| Privilege escalation via setuid binaries | `no-new-privileges:true` + no setuid binaries installed in panel image |
| Filesystem tampering | `read_only: true` + tmpfs for ephemeral state + named volumes for audit |
| docker.sock = root | Mounted only on `panel`; the only thing `panel` does with it is `docker exec panel-host` (no `docker run`, no `docker build`) |
| panel-host has too many caps | `cap_drop: [ALL]` then explicit list (CAP_AUDIT_WRITE for sudo logging, CAP_DAC_OVERRIDE for /etc/shadow reads, CAP_SETUID/SETGID for sudo itself) |
| Host systemd reachable from panel-host | Bind mount is `:ro` and only `/run/systemd`; the panel-host image has no other host filesystem mounted |
| Tampered sudoers | `visudo -c -f /etc/sudoers.d/panel` runs at build time of `panel-host`; bad sudoers breaks the build, not production |
| Network sniffing between caddy ↔ panel | Both on `panel-net`; caddy only exposes 80/443 on the host's external interface |
| Whitelist tampering | Source whitelist is bind-mounted `:ro`; the rewritten copy lives on a tmpfs volume that disappears with the container |

What's NOT mitigated (and that's by design):

- Anyone with write access to the docker socket on the host is root.
  That's a property of Docker, not this setup. Protect the host.
- The `panel` container needs `seccomp=unconfined` because `docker exec`
  uses `clone(CLONE_NEWNS)`, which the default seccomp profile blocks.
  Replace with a custom profile in production that allows only the
  syscalls uvicorn + the docker CLI need. The README notes this.

## Prerequisites

- Docker Engine 24+ with Compose v2.
- A Linux host with systemd (the panel-host sidecar talks to the
  host's systemd over `/run/systemd/private`).
- Ports 80 and 443 free on the host (Caddy).
- A DNS A/AAAA record pointing your hostname at the host. Caddy
  will fail the ACME challenge otherwise.

## First-time setup

```bash
# 1. Generate the secret and write the .env.
cd deploy/docker
cp .env.example .env
chmod 0600 .env
SECRET=$(openssl rand -hex 32)
sed -i "s|^PANEL_SECRET=.*|PANEL_SECRET=$SECRET|" .env
sed -i "s|^PANEL_HOSTNAME=.*|PANEL_HOSTNAME=panel.example.com|" .env
echo "stored PANEL_SECRET=$SECRET"
echo "paste this into the Android app Setup screen on first run"

# 2. Edit the whitelist if the defaults don't match your environment.
#    Defaults assume nginx is at /usr/bin/systemctl and the deploy
#    script at /opt/panel/bin/deploy.sh — both on the HOST (not in a
#    container).
$EDITOR whitelist.json

# 3. Build + start.
docker compose -f docker-compose.yml up -d --build

# 4. Verify.
docker compose -f docker-compose.yml ps
curl -sf https://panel.example.com/healthz
# {"ok": true}
```

If `/healthz` is reachable but `/hook` returns 4xx, the phone almost
certainly has the wrong secret. Re-paste in the app's Settings screen.

## Reloading the whitelist

```bash
docker kill -s HUP remote-panel
```

The server logs the reload count at INFO. Bad entries are rejected
and the previous list stays active — same guarantee as the systemd
install.

## Rotating the secret

```bash
NEW=$(openssl rand -hex 32)
sed -i "s|^PANEL_SECRET=.*|PANEL_SECRET=$NEW|" .env
docker compose -f docker-compose.yml up -d panel    # restart only the panel service
echo "new secret: $NEW — paste into the Android app"
```

## Reading the audit log

```bash
docker compose -f docker-compose.yml exec panel \
    tail -n 50 /var/lib/panel/audit/audit.jsonl | jq .
```

The volume `panel-audit` (created on first run) is where the log
lives. To back it up:

```bash
docker run --rm -v panel-audit:/src -v $(pwd):/dst \
    alpine tar -czf /dst/audit-$(date +%F).tar.gz -C /src .
```

## Add a new command

1. Edit `whitelist.json` — append a new object to `commands[]`.
2. If it needs `sudo`, add a matching line to
   `server/sudoers.d/panel.example` and rebuild the sidecar:
   ```bash
   docker compose -f docker-compose.yml build panel-host
   docker compose -f docker-compose.yml up -d panel-host
   ```
3. Reload the running server:
   ```bash
   docker kill -s HUP remote-panel
   ```
4. (Optional) Add the same `id/name/description` to
   `android/app/src/main/assets/buttons.json` and rebuild the APK.

The rewriter in `server/docker_rewrite.py` rewrites the argv at
container start — you write the host-side command, the server turns
it into `docker exec panel-host <your argv>`. The whitelist
validator runs against the rewritten form, so any malformed rewrite
crashes the container loudly at boot rather than silently at runtime.

## Using SSH-wrap mode (alternative to the docker-exec sidecar)

The default deployment runs each whitelisted command inside the
`panel-host` sidecar via `docker exec`. That works for commands whose
dependencies are bind-mounted into the sidecar (e.g. systemctl,
sudoers), but it can't reach arbitrary host state — files outside
the bind-mount list, host-resident credentials, services only the
host can talk to. SSH-wrap mode replaces `docker exec panel-host`
with a direct `ssh user@host -- argv` call from the panel container
to the host's sshd, with the exact argv pinned on the host side by
an `authorized_keys` `command=` directive.

Use SSH-wrap mode when:
- A command needs to read files outside what `panel-host` mounts
  (e.g. `/etc/<service>` credentials on the host).
- You want the host's regular filesystem layout (no bind-mount
  bookkeeping in compose).
- You don't need the docker-exec privilege model (you're not using
  the sidecar's sudoers + caps).

Use the default docker-exec mode when:
- The command's only privilege is `systemctl` / sudoers-based —
  the sidecar is the simpler setup.
- You don't want SSH keypairs to manage.

### Per-command SSH key generation

Once per whitelist entry that opts into SSH-wrap, run on the host:

```bash
# 1. Generate an ed25519 keypair with no passphrase (the panel process
#    can't type one, and BatchMode=yes means ssh will fail rather than
#    prompt).
sudo install -d -m 0755 /etc/panel/ssh
sudo ssh-keygen -t ed25519 -N '' -C 'panel:<command_id>' \
    -f /etc/panel/ssh/<command_id>.ed25519
sudo chmod 0600 /etc/panel/ssh/<command_id>.ed25519
sudo chmod 0644 /etc/panel/ssh/<command_id>.ed25519.pub

# 2. Authorize the public key on the host with command= pinned to the
#    EXACT whitelist argv. The host's sshd ignores whatever argv the
#    client passes and runs only what's pinned here.
sudo -u root tee -a /root/.ssh/authorized_keys >/dev/null <<EOF
command="<argv[0]> <argv[1]> ... <argv[-1]>",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty,no-user-rc $(cat /etc/panel/ssh/<command_id>.ed25519.pub)
EOF
sudo chmod 0600 /root/.ssh/authorized_keys

# 3. Populate known_hosts for the loopback connection. Run this AFTER
#    the host's host key is stable (it usually is).
sudo ssh-keyscan -t ed25519 localhost 2>/dev/null \
    > /etc/panel/ssh/known_hosts
sudo chmod 0644 /etc/panel/ssh/known_hosts
```

The `command=` pin must match the whitelist argv **byte-for-byte**.
A wrong pin means sshd will return exit 1 with stderr like
`forced-command: bad command "...something else..."` — that's the
signal that the whitelist and authorized_keys are out of sync.

### Whitelist entry shape

Add an `ssh` block to the relevant whitelist entry:

```json
{
  "id": "sim24-bot",
  "name": "Bock datavolume",
  "description": "Refresh sim24 unlimited data usage.",
  "argv": ["/usr/local/bin/sim24", "book"],
  "cwd": null,
  "env": {},
  "timeout_seconds": 120,
  "ssh": {
    "host": "localhost",
    "user": "root",
    "key_path": "/etc/panel/ssh/sim24-bot.ed25519"
  }
}
```

The `ssh` block is optional — entries without it run via the legacy
`docker exec panel-host` path even when SSH-wrap env vars are set.
The `host`/`user`/`key_path` fields in the entry override the global
`PANEL_SSH_*` env vars per-command.

### Global configuration (default SSH target)

If most entries should share a single SSH target, set the global
env vars in `deploy/docker/.env`:

```bash
PANEL_SSH_TARGET_HOST=localhost
PANEL_SSH_TARGET_USER=root
PANEL_SSH_KEY_PATH=/etc/panel/ssh/sim24-bot.ed25519
```

Leave all three empty to run in legacy mode (no SSH wrap at all).

### Verify the SSH path works

After `make docker-up` with the env vars set:

```bash
# 1. Confirm the panel container has the SSH client and can reach the
#    loopback.
docker exec remote-panel ssh -V

# 2. Trigger a hook and check the audit log for transport: ssh.
docker exec remote-panel tail -n 5 /var/lib/panel/audit/audit.jsonl | jq .

# Expected (with command_id=sim24-bot):
# {"event":"exec.start","command_id":"sim24-bot",
#  "transport":"ssh","ssh_target":"root@localhost",...}
# {"event":"exec.done","command_id":"sim24-bot",
#  "transport":"ssh","ssh_target":"root@localhost","exit_code":0,...}
```

### Rollback

Remove the `ssh` block from the whitelist entry and reload:

```bash
make docker-reload-whitelist
```

The entry reverts to the docker-exec path. No image rebuild needed.
The SSH key files can stay on the host until you remove them
manually (they're inert without an `ssh` block pointing at them).

## Uninstall

```bash
docker compose -f docker-compose.yml down
docker volume rm panel-audit caddy-data caddy-config
docker image rm remote-panel:dev remote-panel-host:dev caddy:2
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `PANEL_SECRET must be set` in logs | `.env` missing or empty | `cp .env.example .env`, fill `PANEL_SECRET` |
| Caddy fails ACME challenge | DNS not pointing at host | Check `dig +short panel.example.com`; wait for TTL |
| `/hook` returns 502 | panel container unhealthy | `docker compose logs panel` — usually means rewriter failed |
| Rewriter says `whitelist is invalid` | Edit broke the source JSON | `docker run --rm -v $PWD/whitelist.json:/src python:3.12 python -c 'import json; json.load(open("/src"))'` |
| `docker: command not found` inside panel | Stale image | `docker compose build --pull panel` |
| `permission denied` on `docker.sock` | panel container not in docker group | Compose handles this via the socket's existing perms; ensure your user is in `docker` group on host |
| sudo says "a password is required" | sudoers file out of sync with whitelist | Edit `server/sudoers.d/panel.example`, rebuild sidecar |
| `/var/log/audit.log` missing on host | auditd not running | Install auditd; sudo logs will land in syslog instead |
| Hook with `ssh:` block fails with "Permission denied (publickey)" | Key mount missing, key mode wrong, or sshd config | Verify `/etc/panel/ssh` exists on the host with mode 0755; private key mode 0600; `PubkeyAuthentication yes` in `/etc/ssh/sshd_config`; reload sshd after config changes |
| Hook with `ssh:` block fails with "forced-command: bad command ..." | Whitelist argv and `command=` pin disagree | Update the `command=` pin in `authorized_keys` to exactly match the whitelist entry's argv |
| Hook with `ssh:` block fails with "Host key verification failed" | known_hosts missing or stale | Re-run `ssh-keyscan -t ed25519 localhost > /etc/panel/ssh/known_hosts`; ensure the panel container has the file mounted read-only |

## Security checklist

Before going to production, verify:

- [ ] `deploy/docker/.env` is `chmod 0600`, owned by the deploying user only.
- [ ] `PANEL_SECRET` is at least 64 hex chars (output of `openssl rand -hex 32`).
- [ ] `docker.sock` on the host is `0660 root:docker` (default), not world-writable.
- [ ] No other containers on the host mount `/var/run/docker.sock`.
- [ ] `panel-host` has `cap_drop: [ALL]` and only the caps listed in `docker-compose.yml` show up in `docker inspect panel-host | jq '.[0].HostConfig.CapAdd'`.
- [ ] The compose file's `seccomp=unconfined` is replaced with a custom profile that allows only the syscalls uvicorn and the docker CLI use.
- [ ] Caddy's data volume is on encrypted storage (or the host disk is).
- [ ] `deploy/docker/whitelist.json` is in version control; every change reviewed.
- [ ] No host filesystem paths other than `/var/run/docker.sock` and the Caddy ports are exposed.
- [ ] The host's firewall allows 80/443 inbound only.