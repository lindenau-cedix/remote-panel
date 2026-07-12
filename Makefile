# remote-panel — top-level Makefile
#
# Usage:
#   make test        — run server tests (pytest)
#   make run-server  — run webhook server locally on 127.0.0.1:8088
#   make build-apk   — assemble the Android debug APK
#   make smoke       — smoke-test /healthz against a running server
#   make all         — test + smoke

PY        ?= python3
PIP       ?= $(PY) -m pip
VENV      ?= .venv
VENV_BIN  ?= $(VENV)/bin
SERVER    ?= server
ANDROID   ?= android
DOCKER    ?= deploy/docker
COMPOSE   ?= docker compose -f $(DOCKER)/docker-compose.yml

.PHONY: all test run-server build-apk smoke clean venv \
        docker-build docker-up docker-down docker-logs docker-restart docker-reload-whitelist docker-secret-rotate

all: test smoke

venv:
	@test -d $(VENV) || $(PY) -m venv $(VENV)
	$(VENV_BIN)/pip install --quiet -r $(SERVER)/requirements.txt

test: venv
	cd $(SERVER) && PYTHONPATH=.. ../$(VENV_BIN)/pytest -q

run-server:
	$(VENV_BIN)/uvicorn server.app:app --host 127.0.0.1 --port 8088

smoke:
	curl -sf http://127.0.0.1:8088/healthz && echo

build-apk:
	cd $(ANDROID) && ./gradlew assembleDebug

clean:
	rm -rf $(VENV) $(SERVER)/.pytest_cache $(ANDROID)/.gradle $(ANDROID)/build $(ANDROID)/app/build
	find . -type d -name __pycache__ -exec rm -rf {} +

# ---- docker -----------------------------------------------------------------
# Targets assume `docker compose` (v2). Override COMPOSE= to use a wrapper.
# .env must exist in deploy/docker/ before any of these will work.

docker-build:
	$(COMPOSE) build

docker-up:
	$(COMPOSE) up -d --build
	@echo "verify: curl -sf https://$${PANEL_HOSTNAME:-panel.example.com}/healthz"

docker-down:
	$(COMPOSE) down

docker-logs:
	$(COMPOSE) logs -f --tail=200

docker-restart:
	$(COMPOSE) restart panel

docker-reload-whitelist:
	docker kill -s HUP remote-panel
	$(COMPOSE) logs --tail=20 panel

docker-secret-rotate:
	@if [ ! -f $(DOCKER)/.env ]; then echo "missing $(DOCKER)/.env"; exit 1; fi
	@NEW=$$(openssl rand -hex 32); \
	sed -i "s|^PANEL_SECRET=.*|PANEL_SECRET=$$NEW|" $(DOCKER)/.env; \
	echo "new secret: $$NEW"; \
	echo "paste into the Android app Settings → Update Secret"; \
	$(COMPOSE) up -d panel