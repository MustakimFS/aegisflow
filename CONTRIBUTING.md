# Contributing

## Dev environment

```bash
make bootstrap     # uv sync --all-packages
make up            # docker compose up the full stack
make seed          # populate sample memory + run a workflow
make demo          # walk through the platform end-to-end
make logs          # follow logs across services
```

## Local iteration on a single service

Most edits don't need the full compose stack. Run the service against the
running compose dependencies:

```bash
docker compose up -d postgres redis nats otel-collector prometheus grafana
uvicorn orchestrator.main:app --reload --port 8081
```

The other services are mocked or skipped via `httpx` fail-open paths.

## Code conventions

- **Type-checked**: `make typecheck`. We're strict; please don't add
  `type: ignore` without a comment explaining why.
- **Linted + formatted**: `make fmt && make lint`. Ruff is the source of
  truth.
- **Tests**: every PR must add or update tests. Unit tests for new logic;
  integration tests for new cross-service flows.
- **Commits**: Conventional Commits (`feat:`, `fix:`, `refactor:`, ...).
- **Branch protection**: PRs to `main` need a green CI run and one review.

## Adding a new service

1. Copy `services/_template/` as a starting point (Dockerfile + pyproject + main.py).
2. Add to `pyproject.toml` workspace members.
3. Add to `docker-compose.yml`.
4. Add a k8s base manifest under `infra/k8s/base/`.
5. Wire `/healthz`, `/readyz`, `/metrics`.
6. Open a PR with a brief ADR if the choice is non-obvious.

## Adding a new agent

1. Subclass `orchestrator.agents.base.Agent`.
2. Register in the engine's agent dictionary.
3. Add to a workflow definition or write a new one.
4. Add a unit test exercising its prompt shape and a contract test against
   its expected output schema.

## Adding a new chaos scenario

1. Add the `Scenario` to `chaos/scenarios.py:builtin_scenarios`.
2. Document the failure mode it exercises.
3. Add an integration test that enables the scenario and asserts the
   orchestrator gracefully degrades.
