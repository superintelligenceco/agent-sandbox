# Architecture

```mermaid
flowchart LR
    subgraph Clients
        A[Agent or app] -->|Python SDK| API
        M[MCP client] -->|stdio| MCP[agent-sandbox-mcp]
        MCP -->|HTTP| API
        C[curl] -->|HTTP| API
    end

    subgraph Server["agent-sandbox server"]
        API[FastAPI routes<br/>auth, validation, NDJSON streaming]
        MGR[SandboxManager<br/>quotas, TTL reaper, snapshots]
        STORE[(data dir<br/>records + snapshot tarballs)]
        IF{{Backend interface}}
        API --> MGR
        MGR --> STORE
        MGR --> IF
    end

    IF --> DOCKER[DockerBackend<br/>Docker Engine API]
    IF -.-> FC[Firecracker<br/>roadmap]
    IF -.-> GV[gVisor runtime<br/>roadmap]

    DOCKER --> S1[sandbox container<br/>+ workspace volume]
    DOCKER --> S2[sandbox container<br/>+ workspace volume]
```

- **API layer** ([`api.py`](https://github.com/superintelligenceco/agent-sandbox/blob/main/src/agent_sandbox/api.py)) validates requests with
  Pydantic, checks the API key, and maps errors to HTTP status codes.
- **Manager** ([`manager.py`](https://github.com/superintelligenceco/agent-sandbox/blob/main/src/agent_sandbox/manager.py)) owns IDs, quotas,
  TTLs, locking, and snapshot storage. It persists sandbox records so a restarted
  server picks up its sandboxes and removes orphans.
- **Backend** ([`backends/base.py`](https://github.com/superintelligenceco/agent-sandbox/blob/main/src/agent_sandbox/backends/base.py)) is the
  interface an isolation technology implements: create, destroy, exec, file I/O,
  and workspace export and import as tar streams.
- **Docker backend** ([`backends/docker.py`](https://github.com/superintelligenceco/agent-sandbox/blob/main/src/agent_sandbox/backends/docker.py))
  implements that interface with hardened containers.

A snapshot is a tar of `/workspace` stored in the data directory. Rollback
destroys the container, creates a fresh one with the same spec, and extracts the
tar into the new workspace. Fork does the same into a new sandbox ID.

## Request flow

```mermaid
sequenceDiagram
    participant Agent
    participant API as FastAPI routes
    participant Manager as SandboxManager
    participant Backend as DockerBackend
    Agent->>API: POST /v1/sandboxes/{id}/snapshots
    API->>API: check the API key
    API->>Manager: snapshot(id)
    Manager->>Backend: export_workspace(id)
    Backend-->>Manager: tar stream of /workspace
    Manager->>Manager: write the tarball and the record to the data dir
    Manager-->>API: SnapshotInfo
    API-->>Agent: 201 {"id": "snap_..."}
```

The [decision records](adr/index.md) explain why the pieces look the way they do.
