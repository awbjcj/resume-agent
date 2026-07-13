.DEFAULT_GOAL := help

UV ?= uv
NPM ?= npm
NPX ?= npx
HOST ?= 127.0.0.1
PORT ?= 8000
WEB_HOST ?= localhost
WEB_PORT ?= 5173
PYTEST_ARGS ?= tests/api -v
RAILWAY_URL ?= https://resume-agent.up.railway.app
API_TOKEN ?= $(shell sed -n 's/^API_TOKEN=//p' .env 2>/dev/null)
BACKUP_DIR ?= backups
SEED_FILE ?= seed.tar.gz

.PHONY: help setup setup-browser api web dev test test-api test-py test-web lint lint-py lint-web build build-web preview verify eval openapi client kill-port backup-remote seed

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
	@echo "  make eval           Run the live resume-quality evals (needs an API key)"
	@echo ""
	@echo "  make kill-port      Free PORT if an orphaned dev server is holding it"
	@echo ""
	@echo "  make backup-remote  Export the deployed Railway data/config/.env archive into backups/"
	@echo "  make seed           Back up remote, then push local data/config/.env to Railway (full replace)"
	@echo ""
	@echo "Overrides:"
	@echo "  make api PORT=8080"
	@echo "  make web WEB_PORT=3000"
	@echo "  make test-api PYTEST_ARGS=\"tests/api/test_app_health.py -v\""
	@echo "  make seed RAILWAY_URL=https://your-app.up.railway.app API_TOKEN=..."

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
	$(UV) run ruff check src tests evals

lint-web:
	$(NPM) --prefix web run lint

build: build-web

build-web:
	$(NPM) --prefix web run build

preview:
	cd web && $(NPX) vite preview --host $(WEB_HOST) --port $(WEB_PORT)

verify: lint test build

eval:
	$(UV) run python -m evals.run_eval

openapi:
	$(UV) run python scripts/export_openapi.py

client:
	bash scripts/gen_ts_client.sh

backup-remote:
	@test -n "$(RAILWAY_URL)" || (echo "RAILWAY_URL is required, e.g. make backup-remote RAILWAY_URL=https://your-app.up.railway.app" && exit 1)
	@test -n "$(API_TOKEN)" || (echo "API_TOKEN is required (set it in .env or pass API_TOKEN=...)" && exit 1)
	mkdir -p $(BACKUP_DIR)
	curl -sf -H "Authorization: Bearer $(API_TOKEN)" \
		-o "$(BACKUP_DIR)/backup-$$(date +%Y-%m-%d-%H%M%S).tar.gz" \
		"$(RAILWAY_URL)/api/admin/export"
	@echo "Saved remote backup to $(BACKUP_DIR)/"

seed: backup-remote
	@test -n "$(RAILWAY_URL)" || (echo "RAILWAY_URL is required, e.g. make seed RAILWAY_URL=https://your-app.up.railway.app" && exit 1)
	@test -n "$(API_TOKEN)" || (echo "API_TOKEN is required (set it in .env or pass API_TOKEN=...)" && exit 1)
	$(UV) run python scripts/pack_data.py --out $(SEED_FILE)
	curl -sf -H "Authorization: Bearer $(API_TOKEN)" -F "file=@$(SEED_FILE)" \
		"$(RAILWAY_URL)/api/admin/import?confirm=REPLACE"
	@echo "Seeded $(RAILWAY_URL) from local data ($(SEED_FILE)); prior remote state backed up to $(BACKUP_DIR)/"
