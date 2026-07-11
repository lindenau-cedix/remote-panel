# remote-panel — top-level Makefile
#
# Usage:
#   make test        — run server tests (pytest)
#   make run-server  — run webhook server locally on 127.0.0.1:8000
#   make build-apk   — assemble the Android debug APK
#   make smoke       — smoke-test /healthz against a running server
#   make all         — test + smoke

PY        ?= python3
PIP       ?= $(PY) -m pip
VENV      ?= .venv
VENV_BIN  ?= $(VENV)/bin
SERVER    ?= server
ANDROID   ?= android

.PHONY: all test run-server build-apk smoke clean venv

all: test smoke

venv:
	@test -d $(VENV) || $(PY) -m venv $(VENV)
	$(VENV_BIN)/pip install --quiet -r $(SERVER)/requirements.txt

test: venv
	cd $(SERVER) && PYTHONPATH=.. ../$(VENV_BIN)/pytest -q

run-server:
	$(VENV_BIN)/uvicorn server.app:app --host 127.0.0.1 --port 8000

smoke:
	curl -sf http://127.0.0.1:8000/healthz && echo

build-apk:
	cd $(ANDROID) && ./gradlew assembleDebug

clean:
	rm -rf $(VENV) $(SERVER)/.pytest_cache $(ANDROID)/.gradle $(ANDROID)/build $(ANDROID)/app/build
	find . -type d -name __pycache__ -exec rm -rf {} +