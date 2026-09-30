# Changelog

All notable changes to this project are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project uses [Semantic Versioning](https://semver.org/).

## [0.2.0](https://github.com/superintelligenceco/agent-sandbox/compare/agent-sandbox-v0.1.0...agent-sandbox-v0.2.0) (2026-09-30)


### Features

* add settings, error types, and API key auth ([66bf5d2](https://github.com/superintelligenceco/agent-sandbox/commit/66bf5d29c7b8ba3a9db0d01dd4fc6e74f836e47c))
* **api:** add REST API, OpenAPI models, and server CLI ([77e7750](https://github.com/superintelligenceco/agent-sandbox/commit/77e77509c674c973aaa0464e506b88f926ca23a9))
* **backends:** define the isolation backend interface ([ffe5c45](https://github.com/superintelligenceco/agent-sandbox/commit/ffe5c45025096a23763d110cf30de0187d178c0d))
* **client:** add Python SDK ([029e29d](https://github.com/superintelligenceco/agent-sandbox/commit/029e29d73876c8dfd2deb17f66823bcede18d45c))
* **docker:** add hardened Docker backend ([5e0e653](https://github.com/superintelligenceco/agent-sandbox/commit/5e0e653c1d9402c6b470d68dd2d391ae7abcd682))
* **manager:** add sandbox lifecycle, quotas, TTL reaping, and snapshots ([3437c83](https://github.com/superintelligenceco/agent-sandbox/commit/3437c8314f3cb38abbf3abebc0c3268a09ef5c93))
* **mcp:** expose sandboxes as MCP tools ([f416016](https://github.com/superintelligenceco/agent-sandbox/commit/f416016cf5657c5cae373f3a48c4da6df50f127c))


### Documentation

* add contributing guide, security policy, and community files ([f35b4ff](https://github.com/superintelligenceco/agent-sandbox/commit/f35b4fff674193a959e34293ef3140617697b118))
* add README, OpenAPI spec, backend guide, and examples ([68e72f7](https://github.com/superintelligenceco/agent-sandbox/commit/68e72f7b86f20ee9f0ff27abf3791c1fc4653b6e))

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

[0.1.0]: https://github.com/superintelligenceco/agent-sandbox/releases/tag/v0.1.0
