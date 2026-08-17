.DEFAULT_GOAL := help

UV ?= uv
NPM ?= npm
NPX ?= npx
HOST ?= 127.0.0.1
PORT ?= 8000
WEB_HOST ?= localhost
WEB_PORT ?= 5173
H1B_DIR ?= ../h1b-job-search-mcp
H1B_HOST ?= 127.0.0.1
H1B_PORT ?= 8001
H1B_MCP_ENABLED ?= false
H1B_MCP_TRANSPORT ?= streamable-http
H1B_MCP_COMMAND ?=
H1B_MCP_URL ?= http://$(H1B_HOST):$(H1B_PORT)/mcp
H1B_MCP_TIMEOUT_SECONDS ?= 30
H1B_MCP_MAX_RESULT_CHARS ?= 200000
PYTEST_ARGS ?= tests/api -v
RAILWAY_URL ?= https://resume-agent.up.railway.app
API_TOKEN ?= $(shell sed -n 's/^API_TOKEN=//p' .env 2>/dev/null)
BACKUP_DIR ?= backups
SEED_FILE ?= seed.tar.gz

# H1B_MCP_* must be exported to the API process, but only when a caller has
# explicitly enabled the integration (the full-stack target does this below).
# Keeping the defaults disabled means tests and the standalone API target keep
# their existing .env-driven behavior.
ifneq ($(filter true TRUE yes YES 1,$(H1B_MCP_ENABLED)),)
export H1B_MCP_ENABLED H1B_MCP_TRANSPORT H1B_MCP_COMMAND H1B_MCP_URL
export H1B_MCP_TIMEOUT_SECONDS H1B_MCP_MAX_RESULT_CHARS
endif

# These names are consumed by the local H1B server only. They intentionally do
# not reuse PORT, which belongs to the resume-agent API.
export H1B_HOST H1B_PORT

.PHONY: help setup setup-browser api web h1b dev full-stack h1b-health api-health mcp-health stack-health test test-api test-py test-web lint lint-py lint-web build build-web preview verify eval openapi client kill-port backup-remote seed

help:
	@echo "Common targets:"
	@echo "  make setup          Install Python and web dependencies"
	@echo "  make api            Run FastAPI backend at http://$(HOST):$(PORT)"
	@echo "  make web            Run Vite frontend at http://$(WEB_HOST):$(WEB_PORT)"
	@echo "  make dev            Run API, frontend, and the local H-1B MCP server together"
	@echo "  make full-stack     Alias for make dev"
	@echo "  make h1b            Run H-1B MCP at http://$(H1B_HOST):$(H1B_PORT)/mcp"
	@echo "  make stack-health   Check API health and the H-1B MCP connection"
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

h1b:
	$(UV) --directory "$(H1B_DIR)" run python src/server.py

dev: full-stack

full-stack:
	+$(MAKE) -j3 H1B_MCP_ENABLED=true H1B_MCP_TRANSPORT=streamable-http H1B_MCP_COMMAND= H1B_MCP_URL=http://$(H1B_HOST):$(H1B_PORT)/mcp api web h1b

h1b-health:
	powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-RestMethod -ErrorAction Stop -Uri 'http://$(H1B_HOST):$(H1B_PORT)/health' -TimeoutSec 15 | ConvertTo-Json -Compress"

api-health:
	powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-RestMethod -ErrorAction Stop -Uri 'http://$(HOST):$(PORT)/api/health' -TimeoutSec 15 | ConvertTo-Json -Compress"

mcp-health:
	$(UV) run python scripts/check_h1b_mcp.py --url "$(H1B_MCP_URL)" --timeout $(H1B_MCP_TIMEOUT_SECONDS)

stack-health: api-health h1b-health mcp-health

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
