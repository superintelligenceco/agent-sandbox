from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import httpx
import pytest
from fastapi.testclient import TestClient
from mcp.types import CallToolResult, TextContent

from agent_sandbox.client import SandboxClient
from agent_sandbox.mcp_server import build_server
from tests.conftest import API_KEY

EXPECTED_TOOLS = {
    "sandbox_create",
    "sandbox_list",
    "sandbox_exec",
    "sandbox_read_file",
    "sandbox_write_file",
    "sandbox_list_files",
    "sandbox_snapshot",
    "sandbox_rollback",
    "sandbox_fork",
    "sandbox_destroy",
}


@pytest.fixture
def call(api: TestClient) -> Any:
    server = build_server(SandboxClient(api_key=API_KEY, http_client=cast("httpx.Client", api)))

    def _call(tool: str, /, **arguments: Any) -> Any:
        result = asyncio.run(server.call_tool(tool, arguments))
        assert not getattr(result, "is_error", False), result
        assert isinstance(result, CallToolResult)
        if result.structured_content is not None:
            return result.structured_content.get("result", result.structured_content)
        first = result.content[0]
        assert isinstance(first, TextContent)
        return json.loads(first.text)

    _call.server = server  # type: ignore[attr-defined]
    return _call


def test_lists_all_tools(call: Any) -> None:
    tools = asyncio.run(call.server.list_tools())
    assert {tool.name for tool in tools} == EXPECTED_TOOLS
    assert all(tool.description for tool in tools)


def test_tools_drive_the_api(call: Any) -> None:
    sandbox = call("sandbox_create", timeout_seconds=60)
    sid = sandbox["id"]
    assert call("sandbox_exec", sandbox_id=sid, command="echo mcp")["stdout"] == "mcp\n"
    call("sandbox_write_file", sandbox_id=sid, path="plan.txt", content="v1")
    assert call("sandbox_read_file", sandbox_id=sid, path="plan.txt") == "v1"
    assert [f["name"] for f in call("sandbox_list_files", sandbox_id=sid)] == ["plan.txt"]

    snap = call("sandbox_snapshot", sandbox_id=sid, name="v1")
    call("sandbox_write_file", sandbox_id=sid, path="plan.txt", content="v2")
    assert call("sandbox_rollback", sandbox_id=sid, snapshot_id=snap["id"])["source_snapshot_id"] == snap["id"]
    assert call("sandbox_read_file", sandbox_id=sid, path="plan.txt") == "v1"

    fork = call("sandbox_fork", snapshot_id=snap["id"])
    assert {s["id"] for s in call("sandbox_list")} == {sid, fork["id"]}
    assert call("sandbox_destroy", sandbox_id=fork["id"]) == f"destroyed {fork['id']}"
    call("sandbox_destroy", sandbox_id=sid)
    assert call("sandbox_list") == []
