# REST API

Every `/v1` route needs an API key. The [OpenAPI spec](https://github.com/superintelligenceco/agent-sandbox/blob/main/docs/openapi.json) holds
the full request and response schemas.

| Method and path | What it does |
| --- | --- |
| `GET /healthz` | Report whether the server can reach Docker. No key needed. |
| `POST /v1/sandboxes` | Create and start a sandbox. |
| `GET /v1/sandboxes` | List live sandboxes. |
| `GET /v1/sandboxes/{id}` | Get one sandbox. |
| `DELETE /v1/sandboxes/{id}` | Destroy a sandbox and its workspace. Its snapshots remain. |
| `POST /v1/sandboxes/{id}/timeout` | Reset the TTL, counted from now. |
| `POST /v1/sandboxes/{id}/exec` | Run a command and return stdout, stderr, and the exit code. |
| `POST /v1/sandboxes/{id}/exec/stream` | Run a command and stream NDJSON events as output arrives. |
| `GET /v1/sandboxes/{id}/files?path=` | Download a file. |
| `PUT /v1/sandboxes/{id}/files?path=&mode=` | Upload a file into `/workspace`. |
| `GET /v1/sandboxes/{id}/files/list?path=` | List a directory. |
| `POST /v1/sandboxes/{id}/snapshots` | Snapshot `/workspace`. |
| `POST /v1/sandboxes/{id}/rollback` | Restore a snapshot into the sandbox. |
| `GET /v1/snapshots` | List snapshots, optionally for one sandbox. |
| `GET /v1/snapshots/{id}` | Get one snapshot. |
| `DELETE /v1/snapshots/{id}` | Delete a snapshot. |
| `POST /v1/snapshots/{id}/fork` | Start a new sandbox from a snapshot. |

Errors share one shape: `{"error": {"code": "not_found", "message": "..."}}`.

