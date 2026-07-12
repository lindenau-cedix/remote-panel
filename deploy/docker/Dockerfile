# syntax=docker/dockerfile:1.7
#
# Multi-stage build for the Remote Panel webhook server.
#
# Runtime image is minimal: it contains only the Python venv and the
# `docker` CLI. It deliberately does NOT ship `sudo`, `systemctl`,
# `bash`, or any shell that the executor could reach — defense in depth
# against a regression to `shell=True` in server/executor.py.
#
# Build:   docker build -f deploy/docker/Dockerfile -t remote-panel:dev .
# Run:     see deploy/docker/docker-compose.yml

# ---- builder ---------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

COPY server/requirements.txt ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt


# ---- runtime ---------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # The argv rewriter reads this to decide where to call docker exec.
    PANEL_HOST_CONTAINER=panel-host \
    # Where the running container reads its whitelist and writes its audit.
    PANEL_WHITELIST_PATH=/etc/panel/whitelist.json \
    PANEL_AUDIT_PATH=/var/lib/panel/audit/audit.jsonl \
    PANEL_BIND_HOST=0.0.0.0 \
    PANEL_BIND_PORT=8000

# Only install the docker CLI; no sudo, no systemctl, no shells beyond
# what the python:3.12-slim base already carries. The CLI lets the
# FastAPI executor reach the privileged `panel-host` sidecar via
# `docker exec panel-host <argv...>`.
RUN apt-get update \
    && apt-get install -y --no-install-recommends docker.io tini \
    && rm -rf /var/lib/apt/lists/*

# Non-root user; uid 999 is conventional for "system" service accounts.
RUN groupadd --system --gid 999 panel \
    && useradd  --system --uid 999 --gid panel --no-log-init --create-home panel

COPY --from=builder /opt/venv /opt/venv
COPY server/ /opt/panel/server/

# /etc/panel is a mounted named volume (see docker-compose.yml), so we
# do NOT create it here. /var/lib/panel/audit is also a mounted
# volume, but we still mkdir + chown so the mount point exists with
# the right ownership before the volume is layered on top.
RUN mkdir -p /var/lib/panel/audit \
    && chown -R panel:panel /var/lib/panel/audit
VOLUME ["/var/lib/panel/audit"]

USER panel
WORKDIR /opt/panel

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"]

# tini reaps zombies and forwards signals (notably SIGHUP for whitelist
# reload). The argv rewriter runs first so the whitelist is rewritten
# before uvicorn starts serving.
ENTRYPOINT ["tini", "--", "/opt/panel/server/docker_entrypoint.sh"]
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]