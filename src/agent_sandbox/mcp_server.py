"""MCP server that exposes agent-sandbox as tools.

Run it over stdio from any MCP client::

    AGENT_SANDBOX_URL=http://localhost:8080 AGENT_SANDBOX_API_KEY=... agent-sandbox-mcp

Each tool is a thin wrapper over :class:`agent_sandbox.client.SandboxClient`.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from mcp.server.mcpserver import MCPServer

from agent_sandbox.client import SandboxClient

INSTRUCTIONS = """\
Tools for running code in disposable, isolated sandboxes.

Typical flow: sandbox_create, then sandbox_exec and the file tools. Before a risky
change, call sandbox_snapshot; if the change goes wrong, call sandbox_rollback with
that snapshot ID. Use sandbox_fork to try several approaches from one snapshot in
parallel. Call sandbox_destroy when you finish. Files live under /workspace, and
sandboxes have no network access unless you create them with network=true.
"""


def _sandbox_summary(data: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "status", "image", "network", "expires_at", "source_snapshot_id")
    return {key: data.get(key) for key in keys}


def build_server(client: SandboxClient | None = None) -> MCPServer:
    """Create the MCP server. ``client`` defaults to one configured from the environment."""
    api = client or SandboxClient()
    server: MCPServer = MCPServer(name="agent-sandbox", instructions=INSTRUCTIONS)

    @server.tool()
    def sandbox_create(
        image: str | None = None,
        network: bool = False,
        timeout_seconds: int | None = None,
        cpus: float | None = None,
        memory_mb: int | None = None,
    ) -> dict[str, Any]:
        """Create a new sandbox and return its ID. Network access is off unless network=true."""
        sandbox = api.create(
            image=image,
            network=network,
            timeout_seconds=timeout_seconds,
            cpus=cpus,
            memory_mb=memory_mb,
        )
        return _sandbox_summary(sandbox.data)

    @server.tool()
    def sandbox_list() -> list[dict[str, Any]]:
        """List live sandboxes."""
        return [_sandbox_summary(s.data) for s in api.list_sandboxes()]

    @server.tool()
    def sandbox_exec(
        sandbox_id: str,
        command: str,
        workdir: str | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Run a shell command in the sandbox and return stdout, stderr, and the exit code."""
        result = api.get(sandbox_id).exec(command, workdir=workdir, timeout_seconds=timeout_seconds)
        return asdict(result)

    @server.tool()
    def sandbox_read_file(sandbox_id: str, path: str) -> str:
        """Read a UTF-8 text file. Relative paths resolve against /workspace."""
        return api.get(sandbox_id).read_file(path).decode("utf-8", errors="replace")

    @server.tool()
    def sandbox_write_file(sandbox_id: str, path: str, content: str) -> dict[str, Any]:
        """Create or overwrite a text file under /workspace. Parent directories are created."""
        return asdict(api.get(sandbox_id).write_file(path, content))

    @server.tool()
    def sandbox_list_files(sandbox_id: str, path: str = "/workspace") -> list[dict[str, Any]]:
        """List a directory in the sandbox."""
        return [asdict(entry) for entry in api.get(sandbox_id).list_files(path)]

    @server.tool()
    def sandbox_snapshot(sandbox_id: str, name: str | None = None) -> dict[str, Any]:
        """Save the current /workspace so you can roll back to it or fork from it later."""
        return asdict(api.get(sandbox_id).snapshot(name))

    @server.tool()
    def sandbox_rollback(sandbox_id: str, snapshot_id: str) -> dict[str, Any]:
        """Restore a snapshot. Running processes stop and /tmp is cleared."""
        return _sandbox_summary(api.get(sandbox_id).rollback(snapshot_id).data)

    @server.tool()
    def sandbox_fork(snapshot_id: str, timeout_seconds: int | None = None) -> dict[str, Any]:
        """Start a new, independent sandbox from a snapshot."""
        return _sandbox_summary(api.fork(snapshot_id, timeout_seconds=timeout_seconds).data)

    @server.tool()
    def sandbox_destroy(sandbox_id: str) -> str:
        """Destroy a sandbox. Its snapshots are kept."""
        api.get(sandbox_id).destroy()
        return f"destroyed {sandbox_id}"

    return server


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
