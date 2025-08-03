.PHONY: help install dev-install format lint test clean

# Default target
help:
	@echo "Available targets:"
	@echo "  install      - Install production dependencies"
	@echo "  dev-install  - Install development dependencies"
	@echo "  format       - Format code with black"
	@echo "  lint         - Lint code with ruff"
	@echo "  test         - Run tests"
	@echo "  clean        - Clean up generated files"

# Install production dependencies
install:
	pip install -r requirements.txt

# Install development dependencies
dev-install:
	pip install -r requirements-dev.txt

# Format code with black
format:
	black .

# Lint code with ruff
lint:
	ruff check .

# Run tests
test:
	pytest

# Clean up generated files
clean:
	rm -rf __pycache__ */
__pycache__ */
*.pyc */
*.pyo */
*.pyd */
.pytest_cache/
.mypy_cache/
.pytype/
build/
dist/
*.egg-info/
src/data/vector_db/
src/data/psychoanalyst.db
src/data/psychoanalyst_test.db

# Generate locked requirements from .in files
requirements:
	pip-compile requirements.in
	pip-compile requirements-dev.in

# Sync environment with locked requirements
sync:
	pip-sync requirements.txt requirements-dev.txt

# Run the application
run:
	python src/main.py

# Run with Docker
docker-run:
	docker-compose up --build

# Run Docker in detached mode
docker-detach:
	docker-compose up -d

# Stop Docker containers
docker-stop:
	docker-compose down
