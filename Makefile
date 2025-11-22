.PHONY: help install dev-install install-uv format lint test test-unit test-integration test-devcontainer test-dev test-validate install-hooks clean clean-testdb
.PHONY: docker-up docker-up-all docker-down docker-test docker-test-isolated docker-test-one docker-shell docker-logs docker-logs-api docker-db-view docker-test-reset docker-clean docker-usertest
.PHONY: ui-standalone ui-standalone-test ui-console ui-console-test ui-web ui-web-test ui-all ui-all-test
.PHONY: devcontainer-rebuild devcontainer-test devcontainer-open

# Default target
help:
	@echo "Available targets:"
	@echo ""
	@echo "Local Development:"
	@echo "  install-uv        - Install UV package manager"
	@echo "  install           - Install production dependencies with UV"
	@echo "  dev-install       - Install development dependencies with UV"
	@echo "  format            - Format code with black"
	@echo "  lint              - Lint code with ruff"
	@echo "  test              - Run all tests locally with pytest"
	@echo "  test-dev          - Quick tests in devContainer (fast, for active development)"
	@echo "  test-validate     - Full isolated Docker tests (pre-commit validation)"
	@echo "  test-unit         - Run unit tests only"
	@echo "  test-integration  - Run integration tests only"
	@echo "  test-devcontainer - Run devcontainer setup tests"
	@echo "  install-hooks     - Install git pre-commit hook for automated testing"
	@echo "  clean             - Clean up generated files and caches"
	@echo "  clean-testdb      - Clean test databases only"
	@echo "  requirements      - Generate locked requirements from .in files"
	@echo "  sync              - Sync environment with locked requirements"
	@echo "  run               - Run application locally"
	@echo ""
	@echo "UI Mode Selection:"
	@echo "  ui-standalone     - Run standalone terminal UI (local, no Docker)"
	@echo "  ui-standalone-test - Run standalone terminal in usertest mode"
	@echo "  ui-console        - Run console UI service (Docker, WebSocket client)"
	@echo "  ui-console-test   - Run console UI service in usertest mode"
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
	@echo "  docker-test       - Run tests in Docker (usually not needed, use 'make test')"
	@echo "  docker-test-one   - Run specific test (usage: make docker-test-one TEST=tests/unit/test_foo.py)"
	@echo "  docker-db-view    - Start database viewer at http://localhost:8080"
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
	pip install uv

# Install production dependencies with UV
install:
	uv pip install --system -r requirements.txt

# Install development dependencies with UV
dev-install:
	uv pip install --system -r requirements-dev.txt

# Format code with black
format:
	black .

# Lint code with ruff
lint:
	ruff check .

# Run all tests
test:
	pytest

# Run unit tests only
test-unit:
	pytest -m unit

# Run integration tests only
test-integration:
	pytest -m integration

# Run devcontainer setup tests
test-devcontainer:
	pytest tests/test_devcontainer.py -v

# Quick tests in devContainer (fast, for TDD workflow)
test-dev:
	@echo "🚀 Running quick tests in devContainer..."
	@echo "Perfect for: Active development, TDD, debugging"
	@echo ""
	pytest -x --tb=short -q

# Full isolated Docker tests (pre-commit validation)
test-validate:
	@echo "🔍 Running full test suite in isolated Docker environment..."
	@echo "Perfect for: Pre-commit validation, ensuring clean state"
	@echo ""
	docker compose --profile test run --rm test

# Install git hooks for automated testing
install-hooks:
	@echo "🔧 Installing git hooks..."
	@./scripts/install-hooks.sh

# Clean up generated files
clean:
	rm -rf __pycache__ */__pycache__ \
		*.pyc */*.pyc \
		*.pyo */*.pyo \
		*.pyd */*.pyd \
		.pytest_cache/ \
		.mypy_cache/ \
		.pytype/ \
		build/ \
		dist/ \
		*.egg-info/ \
		data/vector_db/ \
		data/psychoanalyst.db \
		data/psychoanalyst_test.db \
		data/psychoanalyst_usertest.db \
		data/vector_db_usertest/

# Clean test databases only
clean-testdb:
	rm -rf data/psychoanalyst_test.db \
		data/psychoanalyst_usertest.db \
		data/vector_db_usertest/ \
		data/test_vector_db/
	@echo "Test databases cleaned"

# Generate locked requirements from .in files with UV
requirements:
	uv pip compile requirements.in -o requirements.txt
	uv pip compile requirements-dev.in -o requirements-dev.txt

# Sync environment with locked requirements using UV
sync:
	uv pip sync requirements.txt requirements-dev.txt

# Run the application locally
run:
	python src/main.py

# ============================================
# Docker Development Commands
# ============================================

# Start all development services (api, frontend, console-ui)
docker-up:
	docker compose up --build

# Start all services including optional ones
docker-up-all:
	docker compose up --build api frontend console-ui

# Stop all Docker containers
docker-down:
	docker compose down

# Run tests in isolated Docker environment
# NOTE: This is usually not needed - use 'make test' for local testing
# Docker tests are mainly for CI/CD or when you need complete isolation
docker-test:
	docker compose --profile test run --rm test

# Run specific test file
docker-test-one:
	docker compose --profile test run --rm test pytest $(TEST)

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
	@echo "Starting app in user-test mode..."
	@echo "- Using test database: data/psychoanalyst_usertest.db"
	@echo "- Session duration: 10 minutes"
	@echo "- Make sure to set your GEMINI_API_KEY in .env.usertest"
	@echo ""
	docker compose --profile usertest up --build usertest

# Start database viewer for debugging
docker-db-view:
	docker compose --profile debug up db-viewer

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
	docker compose --profile production up --build app

# Run production in detached mode
docker-prod-detach:
	docker compose --profile production up -d app

# ============================================
# UI Mode Selection Commands
# ============================================

# Standalone Terminal UI (local, no Docker)
ui-standalone:
	@echo "🖥️  Starting Standalone Terminal UI..."
	@echo "Running locally with direct Python execution"
	@echo ""
	python src/main.py

# Standalone Terminal UI (usertest mode)
ui-standalone-test:
	@echo "🖥️  Starting Standalone Terminal UI (Usertest Mode)..."
	@echo "- Using test database: data/psychoanalyst_usertest.db"
	@echo "- Session duration: 10 minutes"
	@echo "- Make sure to set your GEMINI_API_KEY in .env.usertest"
	@echo ""
	@set -a && . ./.env.usertest && set +a && python src/main.py

# Console UI Service (WebSocket client)
ui-console:
	@echo "💻 Starting Console UI Service..."
	@echo "- API Server: http://localhost:8000"
	@echo "- Console Client: WebSocket-based terminal"
	@echo ""
	@echo "💡 Tip: To view API logs, run 'make docker-logs-api' in another terminal"
	@echo ""
	docker compose up --build -d api && docker compose run --rm -it console-ui

# Console UI Service (usertest mode)
ui-console-test:
	@echo "💻 Starting Console UI Service (Usertest Mode)..."
	@echo "- Using test database: data/psychoanalyst_usertest.db"
	@echo "- Session duration: 10 minutes"
	@echo "- Make sure to set your GEMINI_API_KEY in .env.usertest"
	@echo ""
	@echo "💡 Tip: To view API logs, run 'docker compose logs -f api-usertest' in another terminal"
	@echo ""
	docker compose --profile usertest-console up --build -d api-usertest && docker compose --profile usertest-console run --rm -it console-ui-usertest

# Web UI (browser interface)
ui-web:
	@echo "🌐 Starting Web UI..."
	@echo "- API Server: http://localhost:8000"
	@echo "- Frontend: http://localhost:5173"
	@echo ""
	docker compose up --build api frontend

# Web UI (usertest mode)
ui-web-test:
	@echo "🌐 Starting Web UI (Usertest Mode)..."
	@echo "- Using test database: data/psychoanalyst_usertest.db"
	@echo "- Session duration: 10 minutes"
	@echo "- API Server: http://localhost:8001"
	@echo "- Frontend: http://localhost:5174"
	@echo "- Make sure to set your GEMINI_API_KEY in .env.usertest"
	@echo ""
	docker compose --profile usertest-web up --build api-usertest frontend-usertest

# All UI modes simultaneously
ui-all:
	@echo "🎯 Starting All UI Modes..."
	@echo "- API Server: http://localhost:8000"
	@echo "- Console Client: Terminal"
	@echo "- Frontend: http://localhost:5173"
	@echo ""
	@echo "⚠️  Note: Console UI requires interactive terminal. Web UI will run in background."
	@echo "💡 Tip: To view API logs, run 'make docker-logs-api' in another terminal"
	@echo ""
	docker compose up --build -d api frontend && docker compose run --rm -it console-ui

# All UI modes (usertest mode)
ui-all-test:
	@echo "🎯 Starting All UI Modes (Usertest Mode)..."
	@echo "- Using test database: data/psychoanalyst_usertest.db"
	@echo "- Session duration: 10 minutes"
	@echo "- API Server: http://localhost:8000"
	@echo "- Console Client: Terminal"
	@echo "- Frontend: http://localhost:5173"
	@echo "- Make sure to set your GEMINI_API_KEY in .env.usertest"
	@echo ""
	@echo "⚠️  Note: Console UI requires interactive terminal. Web UI will run in background."
	@echo "💡 Tip: To view API logs, run 'docker compose logs -f api-usertest' in another terminal"
	@echo ""
	docker compose --profile usertest-all up --build -d api-usertest frontend-usertest && docker compose --profile usertest-all run --rm -it console-ui-usertest

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
