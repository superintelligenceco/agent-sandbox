# CLI reference

The package installs two commands: `agent-sandbox` runs the server, and
`agent-sandbox-mcp` runs the MCP server. The standalone executable on each
release is the same `agent-sandbox` command, bundled with Python.

## agent-sandbox

```text
usage: agent-sandbox [-h] [--version] {serve,openapi} ...
```

| Option | Meaning |
| --- | --- |
| `--version` | Print the version and exit. |

### agent-sandbox serve

Run the REST API server. The server reads its settings from `AGENT_SANDBOX_*`
environment variables (see [Configuration](configuration.md)) and refuses to
start without at least one API key in `AGENT_SANDBOX_API_KEYS`.

| Option | Default | Meaning |
| --- | --- | --- |
| `--host HOST` | `AGENT_SANDBOX_HOST` or `127.0.0.1` | Bind address. |
| `--port PORT` | `AGENT_SANDBOX_PORT` or `8080` | Port. |

```sh
AGENT_SANDBOX_API_KEYS=$(openssl rand -hex 24) agent-sandbox serve --port 8080
```

### agent-sandbox openapi

Print the OpenAPI 3.1 document of the REST API. The command doesn't need Docker
or an API key.

| Option | Meaning |
| --- | --- |
| `-o`, `--output FILE` | Write to a file instead of stdout. |

```sh
agent-sandbox openapi -o openapi.json
```

## agent-sandbox-mcp

Run the MCP server over stdio. It talks to a running agent-sandbox server
through the Python SDK, so it reads `AGENT_SANDBOX_URL` and
`AGENT_SANDBOX_API_KEY`. It exposes ten tools: `sandbox_create`, `sandbox_list`,
`sandbox_exec`, `sandbox_read_file`, `sandbox_write_file`, `sandbox_list_files`,
`sandbox_snapshot`, `sandbox_rollback`, `sandbox_fork`, and `sandbox_destroy`.

```sh
AGENT_SANDBOX_URL=http://localhost:8080 AGENT_SANDBOX_API_KEY=<key> agent-sandbox-mcp
```
