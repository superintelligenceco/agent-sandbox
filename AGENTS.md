# AGENTS.md

Guidance for automated coding agents and human contributors working in this
repository.

## Project layout

- `src/agent_sandbox/api.py`: FastAPI routes, auth wiring, error mapping, NDJSON
  streaming.
- `src/agent_sandbox/manager.py`: sandbox lifecycle, quotas, TTL reaping,
  snapshot storage, restart reconciliation.
- `src/agent_sandbox/backends/base.py`: the `Backend` interface.
- `src/agent_sandbox/backends/docker.py`: the Docker implementation and every
  hardening default.
- `src/agent_sandbox/client.py`: the Python SDK. It must depend only on `httpx`.
- `src/agent_sandbox/mcp_server.py`: MCP tools that wrap the SDK.
- `tests/unit`: fast tests against `tests/fakes.py`, an in-memory backend.
- `tests/integration`: tests against a real Docker daemon, marked `docker`.
- `docs/openapi.json`: generated. Never edit it by hand.

## Commands

```sh
pip install -e ".[dev]"
ruff check . && ruff format --check . && mypy
pytest tests/unit
pytest tests/integration        # needs Docker
agent-sandbox openapi -o docs/openapi.json
```

A change is done when all of these pass.

## Rules

- Keep the isolation defaults in `DockerBackend.create`: non-root user,
  `cap_drop=["ALL"]`, `no-new-privileges`, read-only rootfs, `network_mode="none"`
  unless requested, pids, memory, and CPU limits. The integration test
  `test_hardened_defaults` guards them. Don't weaken it to make a change pass.
- Validate every path with `normalize_path` or `require_in_workspace` in the
  manager, never only in a backend.
- Every new route needs a unit test in `tests/unit/test_api.py` and, if it
  reaches Docker, an integration test.
- Regenerate `docs/openapi.json` after any change to routes or models.
- Integration tests must clean up everything they create. Use the fixtures in
  `tests/integration/conftest.py`.
- Use Conventional Commits for commit messages.
