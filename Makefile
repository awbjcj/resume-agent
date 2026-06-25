.DEFAULT_GOAL := help

UV ?= uv
NPM ?= npm
NPX ?= npx
HOST ?= 127.0.0.1
PORT ?= 8000
WEB_HOST ?= localhost
WEB_PORT ?= 5173
PYTEST_ARGS ?= tests/api -v

.PHONY: help setup setup-browser api web dev test test-api test-py test-web lint lint-py lint-web build build-web preview verify openapi client kill-port

help:
	@echo "Common targets:"
	@echo "  make setup          Install Python and web dependencies"
	@echo "  make api            Run FastAPI backend at http://$(HOST):$(PORT)"
	@echo "  make web            Run Vite frontend at http://$(WEB_HOST):$(WEB_PORT)"
	@echo "  make dev            Run backend and frontend together"
	@echo "  make test           Run API and frontend tests"
	@echo "  make test-py        Run the full Python test suite"
	@echo "  make lint           Run Python and frontend linters"
	@echo "  make build          Build the frontend"
	@echo "  make verify         Run lint, tests, and frontend build"
	@echo ""
	@echo "  make kill-port      Free PORT if an orphaned dev server is holding it"
	@echo ""
	@echo "Overrides:"
	@echo "  make api PORT=8080"
	@echo "  make web WEB_PORT=3000"
	@echo "  make test-api PYTEST_ARGS=\"tests/api/test_app_health.py -v\""

setup:
	$(UV) sync
	$(NPM) --prefix web install

setup-browser:
	$(UV) run playwright install chromium

api:
	$(UV) run resume-agent serve --host $(HOST) --port $(PORT)

kill-port:
	powershell -NoProfile -ExecutionPolicy Bypass -File scripts/kill_port.ps1 -Port $(PORT)

web:
	cd web && $(NPX) vite --host $(WEB_HOST) --port $(WEB_PORT)

dev:
	$(MAKE) -j2 api web

test: test-api test-web

test-api:
	$(UV) run pytest $(PYTEST_ARGS)

test-py:
	$(UV) run pytest tests -v

test-web:
	$(NPM) --prefix web run test:run

lint: lint-py lint-web

lint-py:
	$(UV) run ruff check src tests

lint-web:
	$(NPM) --prefix web run lint

build: build-web

build-web:
	$(NPM) --prefix web run build

preview:
	cd web && $(NPX) vite preview --host $(WEB_HOST) --port $(WEB_PORT)

verify: lint test build

openapi:
	$(UV) run python scripts/export_openapi.py

client:
	bash scripts/gen_ts_client.sh
