.PHONY: help install dev-install install-uv format lint test test-unit test-integration test-all test-frontend test-e2e test-real-llm test-devcontainer test-dev test-validate test-validate-no-mocks install-hooks clean clean-testdb reset-usertest check-usertest-key
.PHONY: docker-up docker-up-all docker-down docker-test docker-test-isolated docker-test-one docker-shell docker-logs docker-logs-api docker-db-view docker-db-backup docker-db-backup-verify docker-db-restore docker-test-reset docker-clean docker-usertest
.PHONY: ui-standalone ui-standalone-test ui-console ui-console-test ui-web ui-web-test ui-all ui-all-test
.PHONY: probe probe-console-deterministic probe-console-local-llm probe-logs probe-db check-usertest-env
.PHONY: devcontainer-rebuild devcontainer-test devcontainer-open
.PHONY: frontend-sync-deps validate-frontend generate-schemas validate-schemas validate-generated-contracts validate-docs validate-architecture finalization-check

export PYTHONPATH := src
CONSOLE_UI_LOG ?= logs/console-ui.log
CONSOLE_UI_LOG_TEST ?= logs/console-ui-usertest.log

# Default target
help:
	@echo "Available targets:"
	@echo ""
	@echo "Default (Docker) Development:"
	@echo "  install-uv        - Deprecated local installer target (no-op)"
	@echo "  install           - Build API container (installs backend deps inside Docker)"
	@echo "  dev-install       - Build dev containers (api + console-ui + frontend)"
	@echo "  format            - Format code with black (Docker)"
	@echo "  lint              - Lint code with ruff (Docker)"
	@echo "  test              - Run backend tests (Docker)"
	@echo "  test-all          - Run backend + frontend + E2E (Docker)"
	@echo "  test-dev          - Quick backend tests (Docker)"
	@echo "  test-validate     - Full isolated Docker tests (pre-commit validation)"
	@echo "  test-unit         - Run unit tests only"
	@echo "  test-integration  - Run integration tests only"
	@echo "  test-frontend     - Run frontend Vitest unit tests"
	@echo "  test-e2e          - Run deterministic Playwright E2E"
	@echo "  frontend-sync-deps - Refresh frontend dev node_modules Docker volume"
	@echo "  validate-frontend - Run frontend type-check + Vite build (Docker)"
	@echo "  test-real-llm     - Run real-LLM tests only (Docker)"
	@echo "  test-devcontainer - Run devcontainer setup tests (Docker)"
	@echo "  install-hooks     - Install git pre-commit hook for automated testing"
	@echo "  clean             - Clean up generated files and caches"
	@echo "  clean-testdb      - Clean test databases only"
	@echo "  requirements      - Generate locked requirements from .in files"
	@echo "  sync              - Rebuild containers from locked requirements"
	@echo "  run               - Run terminal UI via Docker"
	@echo "  run-server        - Run HTTP/WebSocket server via Docker"
	@echo "  run-e2e           - Run deterministic e2e server via Docker"
	@echo "  generate-schemas  - Generate JSON schemas from Pydantic models (Docker)"
	@echo "  validate-schemas  - Validate generated JSON schemas (Docker)"
	@echo "  validate-generated-contracts - Validate committed generated protocol/types (Docker)"
	@echo "  validate-docs     - Validate docs metadata + canonical active-doc index (Docker)"
	@echo "  validate-architecture - Validate architecture budgets and layer boundaries (Docker)"
	@echo "  finalization-check - Run full release-candidate validation path (Docker)"
	@echo ""
	@echo "UI Mode Selection:"
	@echo "  ui-standalone     - Run standalone terminal UI (Docker)"
	@echo "  ui-standalone-test - Run standalone terminal in usertest mode"
	@echo "  ui-console        - Run console UI service (Docker, WebSocket client)"
	@echo "  ui-console-test   - Run console UI service in usertest mode"
	@echo "  probe             - Run local-LLM full-stack console workflow probe"
	@echo "  probe-console-deterministic - Run deterministic full-stack console workflow probe"
	@echo "  probe-console-local-llm - Run local-LLM full-stack console workflow probe"
	@echo "  probe-logs        - Print latest workflow probe summary"
	@echo "  probe-db          - Print rows created by latest workflow probe"
	@echo "  ui-web            - Run web UI (Docker, browser interface)"
	@echo "  ui-web-test       - Run web UI in usertest mode"
	@echo "  ui-all            - Run all UI modes simultaneously"
	@echo "  ui-all-test       - Run all UI modes in usertest mode"
	@echo ""
	@echo "Docker Development:"
	@echo "  docker-up         - Start all development services (api, frontend, console-ui)"
	@echo "  docker-down       - Stop all Docker containers"
	@echo "  docker-shell      - Shell into API container"
	@echo "  docker-logs       - View logs (usage: make docker-logs SERVICE=api)"
	@echo "  docker-logs-api   - View API logs only (useful when running console-ui)"
	@echo "  docker-usertest   - Run app in user-test mode (shorter sessions, test DB)"
	@echo "  reset-usertest    - Stop usertest containers and clear usertest database"
	@echo "  docker-test       - Run tests in Docker (usually not needed, use 'make test')"
	@echo "  docker-test-one   - Run specific test (usage: make docker-test-one TEST=tests/unit/test_foo.py)"
	@echo "  docker-db-view    - View database at http://localhost:8080 (DB=prod|usertest, default: prod)"
	@echo "  docker-db-backup  - Back up the local SQLite database"
	@echo "  docker-db-backup-verify - Verify a backup (usage: make docker-db-backup-verify BACKUP=data/backups/file.db)"
	@echo "  docker-db-restore - Restore a backup (usage: make docker-db-restore BACKUP=data/backups/file.db)"
	@echo "  docker-test-reset - Reset test database"
	@echo "  docker-clean      - Clean up all Docker resources"
	@echo ""
	@echo "Docker Production:"
	@echo "  docker-prod       - Start production app"
	@echo ""
	@echo "DevContainer:"
	@echo "  devcontainer-rebuild - Rebuild devcontainer without cache"
	@echo "  devcontainer-test    - Test devcontainer configuration"
	@echo "  devcontainer-open    - Open project in VSCode devcontainer"

# Install UV package manager
install-uv:
	@echo "⚠️  install-uv is deprecated in Docker-only workflow."
	@echo "    Use 'make requirements' to compile lockfiles in Docker."

# Install production dependencies inside Docker
install:
	docker compose build api

# Build dev containers (installs Python deps inside Docker images)
dev-install:
	docker compose build api console-ui frontend

# Format code with black (Docker)
format:
	docker compose run --rm api black .

# Lint code with ruff (Docker)
lint:
	docker compose run --rm api ruff check .

# Run all tests (Docker)
test:
	docker compose --profile test run --rm test

# Run unit tests only (Docker)
test-unit:
	docker compose --profile test run --rm test pytest -m unit

# Run integration tests only (Docker)
test-integration:
	docker compose --profile test run --rm test pytest -m integration

# Run full suite (deterministic CI-grade, Docker)
test-all:
	$(MAKE) test
	$(MAKE) validate-frontend
	$(MAKE) test-frontend
	$(MAKE) test-e2e

# Refresh frontend dev dependencies in the named Docker volume from package-lock.json
frontend-sync-deps:
	docker compose run --rm --build frontend npm ci

# Frontend validation in an isolated test container.
# npm ci prevents stale image-layer node_modules from masking package-lock changes.
# Use Vite directly here so validation does not rewrite generated type files.
validate-frontend:
	docker compose --profile test run --rm --build frontend-test sh -c "npm ci && npm run type-check && npx vite build"

# Frontend unit tests (Vitest, Docker)
test-frontend:
	docker compose --profile test run --rm --build frontend-test npm test

# Deterministic full-stack E2E (Playwright, Docker)
test-e2e:
	docker compose --profile test run --rm --build frontend-e2e npx playwright install chromium
	docker compose --profile test run --rm --build frontend-e2e npm run test:e2e

# Full release-candidate validation path. Keep this order aligned with
# docs/schema/architecture gates before runtime and browser validation.
finalization-check:
	$(MAKE) validate-docs
	$(MAKE) validate-schemas
	$(MAKE) validate-generated-contracts
	$(MAKE) validate-architecture
	$(MAKE) test-validate
	$(MAKE) validate-frontend
	$(MAKE) test-frontend
	$(MAKE) test-e2e

# Real LLM/RAG smoke tests (Docker, requires secrets / external services)
test-real-llm:
	$(MAKE) check-usertest-key
	docker compose --profile usertest-all up -d --wait --remove-orphans api-usertest
	docker compose --profile test run --rm test pytest -m real_llm --no-mocks

# Run devcontainer setup tests (Docker)
test-devcontainer:
	docker compose run --rm api python scripts/devcontainer_test.py

# Quick tests in devContainer (Docker)
test-dev:
	@echo "🚀 Running quick tests in Docker..."
	@echo "Perfect for: Active development, TDD, debugging"
	@echo ""
	docker compose --profile test run --rm test pytest -m "not real_llm" -x --tb=short -q

# Full isolated Docker tests (pre-commit validation)
test-validate:
	@echo "🔍 Running full test suite in isolated Docker environment..."
	@echo "Perfect for: Pre-commit validation, ensuring clean state"
	@echo ""
	docker compose --profile test run --rm test

# Full isolated Docker tests without mocks (uses real services)
test-validate-no-mocks:
	@echo "🔍 Running full test suite in isolated Docker environment (NO MOCKS)..."
	@echo "⚠️  Requires valid API keys in .env.test and .env.usertest"
	@echo ""
	$(MAKE) check-usertest-key
	docker compose --profile usertest-all up -d --wait --remove-orphans api-usertest
	PYTEST_ARGS="--no-mocks" docker compose --profile test run --rm test

# Install git hooks for automated testing
install-hooks:
	@echo "🔧 Installing git hooks..."
	@./scripts/install-hooks.sh

# Clean up generated files
clean:
	@echo "Cleaning generated files and caches..."
	@rm -rf __pycache__ */__pycache__ \
		*.pyc */*.pyc \
		*.pyo */*.pyo \
		*.pyd */*.pyd \
		.pytest_cache/ \
		.mypy_cache/ \
		.pytype/ \
		build/ \
		dist/ \
		*.egg-info/ \
		data/psychoanalyst.db \
		data/psychoanalyst_test.db \
		data/psychoanalyst_usertest.db 2>/dev/null || true
	@# Use Docker to remove vector DB files created by Docker containers
	@if [ -d "data/vector_db" ] || [ -d "data/vector_db_usertest" ]; then \
		echo "Removing Docker-created vector DB files..."; \
		docker run --rm -v "$(PWD)/data:/data" alpine sh -c "rm -rf /data/vector_db /data/vector_db_usertest" 2>/dev/null || true; \
	fi
	@echo "✓ Cleanup complete"

# Clean test databases only
clean-testdb:
	@echo "Cleaning test databases..."
	@rm -rf data/psychoanalyst_test.db \
		data/psychoanalyst_usertest.db 2>/dev/null || true
	@# Use Docker to remove files created by Docker containers (no sudo needed)
	@if [ -d "data/vector_db_usertest" ] || [ -d "data/test_vector_db" ]; then \
		echo "Removing Docker-created files..."; \
		docker run --rm -v "$(PWD)/data:/data" alpine sh -c "rm -rf /data/vector_db_usertest /data/test_vector_db" 2>/dev/null || true; \
	fi
	@echo "✓ Test databases cleaned"

# Reset usertest DB and containers
reset-foundation-db:
	@echo "Resetting incompatible foundation databases..."
	@docker compose down --remove-orphans
	docker compose run --rm -v "$(PWD)/data:/app/data" api python scripts/purge_databases.py
	@echo "Foundation databases reset."

# Reset usertest DB and containers
reset-usertest:
	@echo "Resetting usertest environment..."
	@docker compose --profile usertest --profile usertest-console --profile usertest-web --profile usertest-all down --remove-orphans
	@rm -rf data/psychoanalyst_usertest.db 2>/dev/null || true
	@# Use Docker to remove files created by Docker containers (no sudo needed)
	@if [ -d "data/vector_db_usertest" ]; then \
		echo "Removing Docker-created usertest vector DB files..."; \
		docker run --rm -v "$(PWD)/data:/data" alpine sh -c "rm -rf /data/vector_db_usertest" 2>/dev/null || true; \
	fi
	@echo "✓ Usertest environment reset"

# Generate locked requirements from .in files with UV
requirements:
	docker compose run --rm -v "$(PWD):/app" api uv pip compile requirements.in -o requirements.txt
	docker compose run --rm -v "$(PWD):/app" api uv pip compile requirements-dev.in -o requirements-dev.txt

# Sync environment with locked requirements using UV
sync: dev-install
	@echo "Docker images rebuilt using locked requirements."

# Run the application via Docker
run:
	docker compose run --rm api python -m psychoanalyst_app

run-server:
	docker compose run --rm api python -m psychoanalyst_app.server

run-e2e:
	docker compose run --rm api python -m psychoanalyst_app.e2e_server

# Generate JSON Schemas from Pydantic models (Docker)
generate-schemas:
	@echo "🔧 Generating JSON schemas from Pydantic models (Docker)..."
	docker compose run --rm -v "$(PWD)/schemas:/app/schemas" api \
		env PYTHONPATH=/app/src python -m psychoanalyst_app.schemas.generate_schemas \
		--output-dir /app/schemas

# Validate generated schemas (comprehensive validation, Docker)
validate-schemas:
	docker compose run --rm -v "$(PWD)/schemas:/app/schemas" -v "$(PWD)/scripts:/app/scripts" api \
		env PYTHONPATH=/app/src python scripts/validate_schemas.py

# Validate generated WebSocket constants and frontend API types without rewriting files.
validate-generated-contracts:
	docker compose run --rm -v "$(PWD)/scripts:/app/scripts" -v "$(PWD)/schemas:/app/schemas" -v "$(PWD)/src:/app/src" -v "$(PWD)/console-ui/src:/app/console-ui/src" -v "$(PWD)/frontend/src:/app/frontend/src" api \
		env PYTHONPATH=/app/src python scripts/generate_ws_protocol.py --check
	docker compose --profile test run --rm -v "$(PWD)/schemas:/app/schemas" --build frontend-test sh -c "npm ci && npm run check:generated-types"

# Validate docs metadata and canonical docs index (Docker)
validate-docs:
	docker compose run --rm -v "$(PWD)/docs:/app/docs" -v "$(PWD)/scripts:/app/scripts" api \
		env PYTHONPATH=/app/src python scripts/validate_docs_metadata.py

# Validate architecture budgets and layering boundaries (Docker)
validate-architecture:
	docker compose run --rm -v "$(PWD)/src:/app/src" -v "$(PWD)/scripts:/app/scripts" api \
		env PYTHONPATH=/app/src python scripts/check_architecture_budgets.py

# ============================================
# Docker Development Commands
# ============================================

# Start all development services (api, frontend, console-ui)
docker-up:
	docker compose up --build --remove-orphans

# Start all services including optional ones
docker-up-all:
	docker compose up --build --remove-orphans api frontend console-ui

# Stop all Docker containers
docker-down:
	docker compose down

# Run tests in isolated Docker environment
# NOTE: This is usually not needed - use 'make test' for local testing
# Docker tests are mainly for CI/CD or when you need complete isolation
docker-test: test

# Run specific test file
docker-test-one:
	docker compose --profile test run --rm test pytest $(TEST)

# Run frontend tests in Docker
docker-test-frontend: test-frontend

# Run all tests in Docker (Backend + Frontend)
# Note: E2E tests are skipped as they require a browser environment
docker-test-all: test-all

# Shell into API container
docker-shell:
	docker compose exec api bash

# View logs (default: all services, or specify SERVICE=api)
docker-logs:
	docker compose logs -f $(SERVICE)

# View API logs only (useful when console-ui is running interactively)
docker-logs-api:
	@echo "📋 Viewing API logs..."
	@echo "API logs are suppressed from console output to keep UI clean."
	@echo "Use this command to monitor API activity when debugging."
	@echo ""
	@if docker compose ps | grep -q "api-usertest"; then \
		docker compose logs -f api-usertest; \
	else \
		docker compose logs -f api; \
	fi

# Run app in user-test mode (manual testing with test settings)
docker-usertest:
	$(MAKE) check-usertest-key
	@echo "Starting app in user-test mode..."
	@echo "- Using test database: data/psychoanalyst_usertest.db"
	@echo "- Session duration: 10 minutes"
	@echo "- Make sure to set your GOOGLE_API_KEY in .env.usertest"
	@echo ""
	docker compose --profile usertest up --build --remove-orphans usertest

# Start database viewer for debugging
# Usage:
#   make docker-db-view             # View production DB (default)
#   make docker-db-view DB=usertest # View usertest DB
# Note: Test databases use in-memory SQLite and don't create viewable files
docker-db-view:
	@DB_NAME=$${DB:-prod}; \
	case $$DB_NAME in \
		prod) DB_FILE=psychoanalyst.db ;; \
		usertest) DB_FILE=psychoanalyst_usertest.db ;; \
		*) echo "❌ Invalid DB. Use: prod or usertest"; \
		   echo ""; \
		   echo "Note: Test databases use in-memory SQLite (:memory:) and"; \
		   echo "      don't create persistent files to view."; \
		   echo ""; \
		   echo "Example: make docker-db-view DB=usertest"; \
		   exit 1 ;; \
	esac; \
	if [ ! -f "data/$$DB_FILE" ]; then \
		echo "❌ Database file not found: data/$$DB_FILE"; \
		echo ""; \
		echo "Available databases:"; \
		ls -1 data/*.db 2>/dev/null || echo "  (none)"; \
		echo ""; \
		echo "💡 Tip: Run the app to create databases:"; \
		echo "   - Production: make ui-console"; \
		echo "   - Usertest: make ui-console-test"; \
		exit 1; \
	fi; \
	if [ ! -s "data/$$DB_FILE" ]; then \
		echo "⚠️  Warning: Database file is empty (0 bytes): data/$$DB_FILE"; \
		echo ""; \
		echo "💡 This database hasn't been initialized yet. Run the app to create tables:"; \
		echo "   - Production: make ui-console"; \
		echo "   - Usertest: make ui-console-test"; \
		echo ""; \
		read -p "Continue anyway? (y/N) " -n 1 -r; \
		echo ""; \
		if [[ ! $$REPLY =~ ^[Yy]$$ ]]; then \
			echo "Cancelled."; \
			exit 1; \
		fi; \
	fi; \
	echo "🔍 Starting database viewer for $$DB_NAME database..."; \
	echo "📁 Database file: data/$$DB_FILE"; \
	echo "🌐 Access at: http://localhost:8080"; \
	echo ""; \
	DB_FILE=$$DB_FILE docker compose --profile debug up db-viewer

# Back up the local production SQLite database.
docker-db-backup:
	docker compose run --rm -v "$(PWD)/data:/app/data" api python -m psychoanalyst_app.tools.db_backup backup

# Verify a local SQLite backup.
docker-db-backup-verify:
	@if [ -z "$(BACKUP)" ]; then \
		echo "Usage: make docker-db-backup-verify BACKUP=data/backups/<backup>.db"; \
		exit 1; \
	fi
	docker compose run --rm -v "$(PWD)/data:/app/data" api python -m psychoanalyst_app.tools.db_backup verify "$(BACKUP)"

# Restore a local SQLite backup. Stop running app containers before using this.
docker-db-restore:
	@if [ -z "$(BACKUP)" ]; then \
		echo "Usage: make docker-db-restore BACKUP=data/backups/<backup>.db"; \
		exit 1; \
	fi
	docker compose run --rm -v "$(PWD)/data:/app/data" api python -m psychoanalyst_app.tools.db_backup restore "$(BACKUP)" --replace

# Reset test database (removes test data volume)
docker-test-reset:
	docker compose down
	docker volume rm psychoanalyst_app_test-data 2>/dev/null || true

# Clean up all Docker resources
docker-clean:
	docker compose down --volumes --rmi local
	docker system prune -f

# ============================================
# Docker Production Commands
# ============================================

# Run production app
docker-prod:
	docker compose --profile production up --build --remove-orphans app

# Run production in detached mode
docker-prod-detach:
	docker compose --profile production up -d --remove-orphans app

# ============================================
# UI Mode Selection Commands
# ============================================

# Standalone Terminal UI (Docker)
ui-standalone:
	@echo "🖥️  Starting Standalone Terminal UI..."
	@echo "Running in Docker container"
	@echo ""
	docker compose run --rm api python -m psychoanalyst_app

# Standalone Terminal UI (usertest mode)
ui-standalone-test:
	$(MAKE) check-usertest-key
	@echo "🖥️  Starting Standalone Terminal UI (Usertest Mode)..."
	@echo "- Using test database: data/psychoanalyst_usertest.db"
	@echo "- Session duration: 10 minutes"
	@echo "- Make sure to set your GOOGLE_API_KEY in .env.usertest"
	@echo ""
	ENV_FILE=.env.usertest docker compose run --rm api python -m psychoanalyst_app

# Console UI Service (WebSocket client)
ui-console:
	@mkdir -p logs
	@printf "\n[%s] make ui-console\n" "$$(date -Iseconds)" >> $(CONSOLE_UI_LOG)
	@docker compose up --build --remove-orphans -d api >> $(CONSOLE_UI_LOG) 2>&1
	@docker compose run --rm -it console-ui 2>> $(CONSOLE_UI_LOG)

# Console UI Service (usertest mode)
ui-console-test:
	$(MAKE) check-usertest-key
	@mkdir -p logs
	@printf "\n[%s] make ui-console-test\n" "$$(date -Iseconds)" >> $(CONSOLE_UI_LOG_TEST)
	@docker compose --profile usertest-console up --build --remove-orphans -d api-usertest >> $(CONSOLE_UI_LOG_TEST) 2>&1
	@docker compose --profile usertest-console run --rm -it console-ui-usertest 2>> $(CONSOLE_UI_LOG_TEST)

# Local full-stack diagnostic probe. This is intentionally not a CI gate.
probe:
	@./scripts/probe_local_llm.sh

probe-console-deterministic:
	@./scripts/probe_deterministic.sh

probe-console-local-llm: probe

probe-logs:
	@if [ -f logs/workflow-probes/latest/summary.md ]; then \
		cat logs/workflow-probes/latest/summary.md; \
	else \
		echo "No workflow probe summary found at logs/workflow-probes/latest/summary.md"; \
		exit 1; \
	fi

probe-db:
	@if [ -f logs/workflow-probes/latest/created_rows.json ]; then \
		cat logs/workflow-probes/latest/created_rows.json; \
	else \
		echo "No workflow probe database artifact found at logs/workflow-probes/latest/created_rows.json"; \
		exit 1; \
	fi

# Web UI (browser interface)
ui-web:
	@echo "🌐 Starting Web UI..."
	@echo "- API Server: http://localhost:8000"
	@echo "- Frontend: http://localhost:5173"
	@echo ""
	docker compose up --build --remove-orphans api frontend

# Web UI (usertest mode)
ui-web-test:
	$(MAKE) check-usertest-key
	@echo "🌐 Starting Web UI (Usertest Mode)..."
	@echo "- Using test database: data/psychoanalyst_usertest.db"
	@echo "- Session duration: 10 minutes"
	@echo "- API Server: http://localhost:8001"
	@echo "- Frontend: http://localhost:5174"
	@echo "- Make sure to set your GOOGLE_API_KEY in .env.usertest"
	@echo ""
	docker compose --profile usertest-web up --build --remove-orphans api-usertest frontend-usertest

# All UI modes simultaneously
ui-all:
	@mkdir -p logs
	@printf "\n[%s] make ui-all\n" "$$(date -Iseconds)" >> $(CONSOLE_UI_LOG)
	@docker compose up --build --remove-orphans -d api frontend >> $(CONSOLE_UI_LOG) 2>&1
	@docker compose run --rm -it console-ui 2>> $(CONSOLE_UI_LOG)

# All UI modes (usertest mode)
ui-all-test:
	$(MAKE) check-usertest-key
	@mkdir -p logs
	@printf "\n[%s] make ui-all-test\n" "$$(date -Iseconds)" >> $(CONSOLE_UI_LOG_TEST)
	@docker compose --profile usertest-all up --build --remove-orphans -d api-usertest frontend-usertest >> $(CONSOLE_UI_LOG_TEST) 2>&1
	@docker compose --profile usertest-all run --rm -it console-ui-usertest 2>> $(CONSOLE_UI_LOG_TEST)

# ============================================
# DevContainer Commands
# ============================================

# Rebuild devcontainer without cache
devcontainer-rebuild:
	@echo "🔄 Rebuilding devcontainer..."
	@echo "This will rebuild the container from scratch without using cache."
	@echo ""
	@if command -v devcontainer > /dev/null 2>&1; then \
		devcontainer build --workspace-folder . --no-cache; \
	else \
		echo "❌ devcontainer CLI not found."; \
		echo "Install it with: npm install -g @devcontainers/cli"; \
		echo ""; \
		echo "Alternative: Rebuild from VSCode:"; \
		echo "1. Open Command Palette (Ctrl+Shift+P)"; \
		echo "2. Run 'Dev Containers: Rebuild Container'"; \
		exit 1; \
	fi

# Test devcontainer configuration
devcontainer-test:
	@echo "✅ Testing devcontainer setup..."
	@echo ""
	@echo "Checking configuration files exist..."
	@test -f .devcontainer/devcontainer.json && echo "✓ .devcontainer/devcontainer.json exists"
	@test -f .vscode/settings.json && echo "✓ .vscode/settings.json exists"
	@test -f .vscode/extensions.json && echo "✓ .vscode/extensions.json exists"
	@test -f .vscode/launch.json && echo "✓ .vscode/launch.json exists"
	@echo ""
	@echo "Validating JSON syntax (note: VSCode supports JSONC with comments)..."
	@python3 -c "import json; json.load(open('.devcontainer/devcontainer.json'))" && echo "✓ devcontainer.json is valid" || echo "⚠ devcontainer.json has comments (valid JSONC)"
	@echo ""
	@echo "Configuration files are ready! ✨"
	@echo ""
	@echo "Note: VSCode config files (.vscode/*) support comments (JSONC format)."
	@echo "They will work correctly in VSCode even if they fail strict JSON validation."

# Open project in VSCode devcontainer
devcontainer-open:
	@echo "🚀 Opening project in VSCode devcontainer..."
	@if command -v code > /dev/null 2>&1; then \
		code --folder-uri vscode-remote://dev-container+$(shell pwd | sed 's/\//\%2F/g')/app; \
	else \
		echo "❌ VSCode CLI not found."; \
		echo ""; \
		echo "Manual steps:"; \
		echo "1. Open this folder in VSCode"; \
		echo "2. Press Ctrl+Shift+P"; \
		echo "3. Run 'Dev Containers: Reopen in Container'"; \
	fi
check-usertest-key:
	@set -a && . ./.env.usertest && set +a && \
	if [ -z "$${GOOGLE_API_KEY:-}" ] || [ "$${GOOGLE_API_KEY}" = "test_mock_api_key_for_testing" ]; then \
		echo "❌ GOOGLE_API_KEY is not configured in .env.usertest."; \
		echo "   Please edit .env.usertest and provide your real API key before running user-test commands."; \
		echo "   (This profile uses real Gemini responses: MODEL_NAME=$${MODEL_NAME:-unset})"; \
		exit 1; \
	fi

check-usertest-env:
	@if [ ! -f .env.usertest ]; then \
		echo "❌ .env.usertest is missing."; \
		echo "   Copy .env.usertest.template to .env.usertest and configure the backend LLM."; \
		exit 1; \
	fi
