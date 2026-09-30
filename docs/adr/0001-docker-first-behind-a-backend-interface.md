# 0001. Docker first, behind a backend interface

Status: accepted, 2026-09-30

## Context

A sandbox server needs an isolation technology. Docker is on almost every Linux
host people self-host on, needs no extra kernel setup, and pulls any OCI image.
MicroVMs such as Firecracker isolate better but need KVM, root filesystem images,
and an in-VM agent. gVisor sits in between and plugs into Docker as an OCI
runtime.

## Decision

Ship one backend, `DockerBackend`, and put it behind the abstract `Backend`
class in `agent_sandbox.backends.base`. The manager owns IDs, quotas, TTLs,
locking, path validation, and snapshot storage, so a backend only creates and
destroys environments, runs commands, moves files, and exports and imports the
workspace as tar streams. The Docker backend hardens every container: non-root
user, all capabilities dropped, `no-new-privileges`, read-only root filesystem,
no network unless requested, and pids, memory, and CPU limits.

## Consequences

- The server installs with one `docker compose up`, and tests run on any CI
  runner with Docker.
- Sandboxes share the host kernel. The README and the docs state that limit
  plainly instead of implying VM-grade isolation.
- `AGENT_SANDBOX_DOCKER_RUNTIME=runsc` can already pass gVisor through, and a
  Firecracker backend can implement the same interface later without touching
  the API or the manager.
- An in-memory fake of the interface (`tests/fakes.py`) lets the unit tests run
  without Docker.
