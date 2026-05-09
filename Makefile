.PHONY: help bootstrap up down logs ps seed demo test lint typecheck fmt clean

PYTHON ?= python3.12
COMPOSE ?= docker compose

help:
	@echo "AegisFlow - make targets"
	@echo "  bootstrap   install workspace deps via uv"
	@echo "  up          docker compose up the full stack"
	@echo "  down        tear down the stack (preserves volumes)"
	@echo "  nuke        tear down + drop volumes"
	@echo "  logs        tail logs from all services"
	@echo "  ps          show running services"
	@echo "  seed        load sample agents, memory, chaos scenarios"
	@echo "  demo        run an end-to-end workflow against the gateway"
	@echo "  test        run unit + integration suites"
	@echo "  lint        ruff + check formatting"
	@echo "  typecheck   mypy across services"
	@echo "  fmt         ruff format + isort"
	@echo "  clean       clean caches and build artifacts"

bootstrap:
	uv sync --all-packages

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

nuke:
	$(COMPOSE) down -v

logs:
	$(COMPOSE) logs -f --tail=200

ps:
	$(COMPOSE) ps

seed:
	$(PYTHON) scripts/seed.py

demo:
	$(PYTHON) scripts/demo.py

test:
	uv run pytest tests/ -v

lint:
	uv run ruff check .

typecheck:
	uv run mypy libs/ services/

fmt:
	uv run ruff format .
	uv run ruff check --fix .

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
