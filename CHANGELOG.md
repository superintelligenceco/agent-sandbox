# Changelog

All notable changes to this project are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Multi-arch server image (`linux/amd64`, `linux/arm64`) on
  `ghcr.io/superintelligenceco/agent-sandbox`, tagged `vX.Y.Z` and `latest` on
  releases and `edge` on manual builds of `main`.
- Release assets: the wheel and sdist for the SDK and `agent-sandbox-mcp`, a
  Docker Compose file pinned to the release's image, and `SHA256SUMS`.
- `docker-compose.build.yml` override that builds the image from a checkout.

### Changed

- `docker-compose.yml` pulls the GHCR image instead of building from source, so
  downloading it and running `docker compose up -d` installs the server.
- Releases come from pushing a `v*` tag instead of release-please.

### Fixed

- CodeQL runs on a private repository without GitHub Advanced Security and keeps
  its SARIF results as a run artifact.

## [0.1.0] - 2026-09-30

The first release: a self-hostable sandbox server for AI agents, with a Docker
backend, a Python SDK, and an MCP server.

### Added

- REST API to create, list, inspect, and destroy sandboxes, with per-request
  image, CPU, memory, process-count, network, and TTL settings.
- Command execution that returns stdout, stderr, and the exit code, plus a
  streaming variant that sends NDJSON events as output arrives. Timeouts kill the
  command's whole process group.
- File upload, download, and directory listing, with writes confined to
  `/workspace`.
- Snapshots of `/workspace`, rollback to a snapshot, and fork of a snapshot into
  a new sandbox. Snapshots outlive their source sandbox.
- TTL reaping, a server-wide sandbox quota, an image allowlist, and cleanup of
  orphaned containers and volumes on restart.
- API key authentication through `Authorization: Bearer` or `X-API-Key`, with
  constant-time comparison.
- Docker backend with hardened defaults: non-root user, all capabilities
  dropped, `no-new-privileges`, read-only root filesystem, no network unless
  requested, pids, memory, and CPU limits, and swap disabled.
- `Backend` interface for other isolation technologies.
- Python SDK (`agent_sandbox.client`) that depends only on `httpx`.
- MCP server (`agent-sandbox-mcp`) with ten sandbox tools.
- OpenAPI 3.1 spec in `docs/openapi.json`.
- Dockerfile and Docker Compose file for a one-command local deployment.
- Unit tests against an in-memory backend and integration tests against real
  Docker.

### Known limits

- Containers share the host kernel. See the security model in the README.
- Snapshots capture `/workspace` only, not memory, processes, or `/tmp`.
- Every API key can see and control every sandbox.

[Unreleased]: https://github.com/superintelligenceco/agent-sandbox/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/superintelligenceco/agent-sandbox/releases/tag/v0.1.0
