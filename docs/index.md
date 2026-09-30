# agent-sandbox

**Self-hostable, disposable sandboxes where AI agents run code, with snapshot,
rollback, and fork.**

You give an agent a sandbox. The agent writes files, runs commands, and streams
the output. Before it tries something risky, it takes a snapshot. When the
attempt goes wrong, it rolls back in one call, or forks the snapshot into several
sandboxes and tries three ideas in parallel. When the agent forgets to clean up,
the TTL reaper does it for you.

agent-sandbox is a small Python server with a REST API, a Python SDK, and an MCP
server. It runs on any Linux host with Docker, and your code never leaves your
infrastructure.

![A terminal session that creates a sandbox, runs code, snapshots, breaks the workspace, rolls back, and destroys the sandbox](assets/demo.gif)

## Where to go next

- [Quickstart](quickstart.md): install the server and run your first command in
  a sandbox.
- [Concepts](concepts.md): sandboxes, snapshots, rollback, fork, and TTLs.
- [Architecture](architecture.md): how the API, the manager, and the backends fit
  together.
- [REST API](rest-api.md), [Python SDK](python-sdk.md), and [CLI](cli.md)
  reference.
- [FAQ](faq.md) and the [security model](concepts.md#security-model).

## Install in one line

```sh
curl -fsSL https://raw.githubusercontent.com/superintelligenceco/agent-sandbox/main/install.sh | sh
```

The script downloads the standalone `agent-sandbox` executable for your OS and
CPU, checks it against the release's `SHA256SUMS`, and installs it into
`~/.local/bin`. The [Quickstart](quickstart.md) covers the Docker image, the
Compose file, and the PyPI package.
