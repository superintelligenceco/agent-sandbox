# Configuration

You configure the server with environment variables. The most common ones:

| Variable | Default | Meaning |
| --- | --- | --- |
| `AGENT_SANDBOX_API_KEYS` | none | Comma-separated keys, each at least 16 characters. Required. |
| `AGENT_SANDBOX_DEFAULT_IMAGE` | `python:3.12-slim` | Image used when a request doesn't name one. |
| `AGENT_SANDBOX_ALLOWED_IMAGES` | `*` | Comma-separated glob patterns, for example `python:*,node:22*`. |
| `AGENT_SANDBOX_ALLOW_NETWORK` | `true` | Set to `false` to refuse sandboxes that request network access. |
| `AGENT_SANDBOX_MAX_SANDBOXES` | `20` | Maximum number of live sandboxes. |
| `AGENT_SANDBOX_DEFAULT_TIMEOUT_SECONDS` | `900` | TTL when a request doesn't set one. |
| `AGENT_SANDBOX_MAX_CPUS` / `_MAX_MEMORY_MB` | `4` / `4096` | Upper bounds a request can ask for. |
| `AGENT_SANDBOX_DOCKER_RUNTIME` | empty | OCI runtime for sandboxes, for example `runsc`. See the roadmap. |
| `AGENT_SANDBOX_DATA_DIR` | `./data` | Where sandbox records and snapshot tarballs live. |



## Security model

Read this section before you expose the server to anything you don't trust.

## Every setting

The server reads these variables when it starts. Lists are comma-separated.

| Variable | Default |
| --- | --- |
| `AGENT_SANDBOX_API_KEYS` | `(none)` |
| `AGENT_SANDBOX_INSECURE_NO_AUTH` | `false` |
| `AGENT_SANDBOX_HOST` | `127.0.0.1` |
| `AGENT_SANDBOX_PORT` | `8080` |
| `AGENT_SANDBOX_DATA_DIR` | `data` |
| `AGENT_SANDBOX_DEFAULT_IMAGE` | `python:3.12-slim` |
| `AGENT_SANDBOX_ALLOWED_IMAGES` | `*` |
| `AGENT_SANDBOX_SANDBOX_USER` | `1000:1000` |
| `AGENT_SANDBOX_DOCKER_RUNTIME` | `` |
| `AGENT_SANDBOX_NETWORK_NAME` | `agent-sandbox-net` |
| `AGENT_SANDBOX_ALLOW_NETWORK` | `true` |
| `AGENT_SANDBOX_MAX_SANDBOXES` | `20` |
| `AGENT_SANDBOX_DEFAULT_TIMEOUT_SECONDS` | `900` |
| `AGENT_SANDBOX_MAX_TIMEOUT_SECONDS` | `86400` |
| `AGENT_SANDBOX_DEFAULT_CPUS` | `1.0` |
| `AGENT_SANDBOX_MAX_CPUS` | `4.0` |
| `AGENT_SANDBOX_DEFAULT_MEMORY_MB` | `512` |
| `AGENT_SANDBOX_MAX_MEMORY_MB` | `4096` |
| `AGENT_SANDBOX_DEFAULT_PIDS_LIMIT` | `256` |
| `AGENT_SANDBOX_MAX_PIDS_LIMIT` | `4096` |
| `AGENT_SANDBOX_TMP_SIZE_MB` | `256` |
| `AGENT_SANDBOX_DEFAULT_EXEC_TIMEOUT_SECONDS` | `60` |
| `AGENT_SANDBOX_MAX_EXEC_TIMEOUT_SECONDS` | `3600` |
| `AGENT_SANDBOX_MAX_EXEC_OUTPUT_BYTES` | `10485760` |
| `AGENT_SANDBOX_MAX_FILE_BYTES` | `52428800` |
| `AGENT_SANDBOX_MAX_SNAPSHOT_BYTES` | `1073741824` |
| `AGENT_SANDBOX_REAP_INTERVAL_SECONDS` | `10.0` |
