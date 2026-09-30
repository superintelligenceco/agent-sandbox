# Common development tasks. Run `make` or `make help` to list them.

PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

.DEFAULT_GOAL := help

.PHONY: help
help: ## List the available targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

$(BIN)/python:
	$(PYTHON) -m venv $(VENV)

.PHONY: setup
setup: $(BIN)/python ## Create .venv and install the package with dev and docs extras
	$(BIN)/python -m pip install -U pip
	$(BIN)/python -m pip install -e ".[dev,docs]"

.PHONY: lint
lint: ## Run ruff and check that docs/openapi.json is current
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .
	$(BIN)/agent-sandbox openapi | diff -u docs/openapi.json -

.PHONY: fmt
fmt: ## Format the code and apply safe lint fixes
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

.PHONY: typecheck
typecheck: ## Run mypy in strict mode
	$(BIN)/mypy

.PHONY: test
test: ## Run the unit tests with coverage (no Docker needed)
	$(BIN)/pytest tests/unit --cov=agent_sandbox --cov-report=term-missing

.PHONY: test-integration
test-integration: ## Run the tests that need a Docker daemon
	$(BIN)/pytest tests/integration -m docker

.PHONY: bench
bench: ## Run the benchmarks and compare them with the committed baseline
	$(BIN)/pytest tests/bench --benchmark-only --benchmark-json=bench.json
	$(BIN)/python scripts/bench_compare.py benchmarks/baseline.json bench.json

.PHONY: openapi
openapi: ## Regenerate docs/openapi.json
	$(BIN)/agent-sandbox openapi -o docs/openapi.json

.PHONY: build
build: ## Build the wheel, sdist, and the local server image
	$(BIN)/python -m build
	docker build -t agent-sandbox:local .

.PHONY: docs
docs: ## Build the documentation site into site/
	$(BIN)/mkdocs build --strict

.PHONY: docs-serve
docs-serve: ## Serve the documentation site on http://127.0.0.1:8000
	$(BIN)/mkdocs serve

.PHONY: up
up: ## Build and start the server with Docker Compose (needs AGENT_SANDBOX_API_KEY)
	docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build --wait

.PHONY: down
down: ## Stop the Compose stack and delete its data
	docker compose down -v

.PHONY: clean
clean: ## Remove build output and tool caches
	rm -rf build dist site .coverage coverage.xml htmlcov .pytest_cache .mypy_cache .ruff_cache .benchmarks bench.json mutants
