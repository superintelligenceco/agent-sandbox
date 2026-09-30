# Quickstart

You need a Linux host with Docker. The server drives Docker to create one
container per sandbox.

## 1. Install the server

Pick one of these options.

=== "Executable"

    ```sh
    curl -fsSL https://raw.githubusercontent.com/superintelligenceco/agent-sandbox/main/install.sh | sh
    export AGENT_SANDBOX_API_KEY=$(openssl rand -hex 24)
    AGENT_SANDBOX_API_KEYS=$AGENT_SANDBOX_API_KEY agent-sandbox serve
    ```

    Set `AGENT_SANDBOX_VERSION=v0.2.1` before `sh` to pin a release. Your user
    needs access to the Docker socket.

=== "Docker Compose"

    ```sh
    curl -fsSLO https://github.com/superintelligenceco/agent-sandbox/releases/latest/download/docker-compose.yml
    export AGENT_SANDBOX_API_KEY=$(openssl rand -hex 24)
    docker compose up -d
    ```

    Or let the installer write the key and start the stack:
    `curl -fsSL https://raw.githubusercontent.com/superintelligenceco/agent-sandbox/main/install.sh | AGENT_SANDBOX_INSTALL=compose sh`.

=== "PyPI"

    ```sh
    pip install "sic-agent-sandbox[server,mcp]"
    export AGENT_SANDBOX_API_KEY=$(openssl rand -hex 24)
    AGENT_SANDBOX_API_KEYS=$AGENT_SANDBOX_API_KEY agent-sandbox serve
    ```

    The distribution is `sic-agent-sandbox`. The import package is
    `agent_sandbox`, and the commands are `agent-sandbox` and
    `agent-sandbox-mcp`.

The API listens on `http://localhost:8080`. Check it with
`curl localhost:8080/healthz`.

## 2. Run code in a sandbox

```sh
API=http://localhost:8080/v1
sb() { curl -s -H "Authorization: Bearer $AGENT_SANDBOX_API_KEY" -H "Content-Type: application/json" "$@"; }
SB=$(sb -X POST $API/sandboxes -d '{"image": "python:3.12-slim"}' | jq -r .id)
sb -X PUT "$API/sandboxes/$SB/files?path=app.py" --data-binary 'print(sum(range(10)))'
sb -X POST $API/sandboxes/$SB/exec -d '{"command": "python3 app.py"}'
```

The last call returns `{"stdout": "45\n", "stderr": "", "exit_code": 0, ...}`.

## 3. Snapshot, break, and roll back

```sh
SNAP=$(sb -X POST $API/sandboxes/$SB/snapshots -d '{}' | jq -r .id)
sb -X POST $API/sandboxes/$SB/exec -d '{"command": "rm app.py"}'
sb -X POST $API/sandboxes/$SB/rollback -d "{\"snapshot_id\": \"$SNAP\"}"
sb -X POST $API/sandboxes/$SB/exec -d '{"command": "python3 app.py"}'
sb -X DELETE $API/sandboxes/$SB
```

After the rollback, `app.py` is back and prints `45` again.

## 4. Use it from Python

```python
from agent_sandbox.client import SandboxClient

with SandboxClient() as client, client.create(image="python:3.12-slim") as sandbox:
    sandbox.write_file("app.py", "print('hello')\n")
    good = sandbox.snapshot("working")
    sandbox.exec("rm app.py")
    sandbox.rollback(good)
    print(sandbox.exec("python3 app.py").stdout)
```

`SandboxClient` reads `AGENT_SANDBOX_URL` and `AGENT_SANDBOX_API_KEY` from the
environment. The SDK depends only on `httpx`, so `pip install sic-agent-sandbox`
is enough on the client side.

## 5. Connect an MCP client

Install the `mcp` extra and point your MCP client at `agent-sandbox-mcp`:

```json
{
  "mcpServers": {
    "agent-sandbox": {
      "command": "agent-sandbox-mcp",
      "env": {
        "AGENT_SANDBOX_URL": "http://localhost:8080",
        "AGENT_SANDBOX_API_KEY": "replace-with-your-key"
      }
    }
  }
}
```
