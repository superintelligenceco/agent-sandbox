"""Keep the README honest: run its Python example and check what it documents."""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi.testclient import TestClient

import agent_sandbox.client
from agent_sandbox.cli import main
from agent_sandbox.config import ENV_PREFIX, Settings
from tests.conftest import API_KEY
from tests.unit.test_mcp import EXPECTED_TOOLS

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text()


def code_blocks(lang: str) -> list[str]:
    return re.findall(rf"```{lang}\n(.*?)```", README, flags=re.DOTALL)


def test_python_example_runs(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    (block,) = [b for b in code_blocks("python") if "SandboxClient" in b]
    real = agent_sandbox.client.SandboxClient

    def client_on_test_server(*args: Any, **kwargs: Any) -> agent_sandbox.client.SandboxClient:
        return real(api_key=API_KEY, http_client=cast("httpx.Client", api))

    monkeypatch.setattr(agent_sandbox.client, "SandboxClient", client_on_test_server)
    exec(compile(block, "README.md", "exec"), {})  # noqa: S102


def test_documented_cli_commands_parse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    commands = [
        shlex.split(line.split("#")[0])
        for block in code_blocks("sh")
        for line in block.splitlines()
        if line.startswith("agent-sandbox ")
    ]
    assert commands, "the README should show at least one agent-sandbox command"
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    for argv in commands:
        assert main(argv[1:]) == 0, argv


def test_documented_settings_exist() -> None:
    fields = {ENV_PREFIX + name.upper() for name in Settings.__dataclass_fields__}
    documented = set(re.findall(r"`(AGENT_SANDBOX_[A-Z_]+)`", README))
    compose_only = {"AGENT_SANDBOX_API_KEY", "AGENT_SANDBOX_VERSION", "AGENT_SANDBOX_URL"}
    # "AGENT_SANDBOX_MAX_CPUS` / `_MAX_MEMORY_MB" documents two settings in one row.
    assert documented - compose_only <= fields


def test_documented_mcp_tools_match_the_server() -> None:
    sentence = README[README.index("The server exposes") :].split(".")[0]
    assert set(re.findall(r"`(sandbox_[a-z_]+)`", sentence)) == EXPECTED_TOOLS


def test_compose_file_uses_the_documented_variables() -> None:
    compose = (ROOT / "docker-compose.yml").read_text()
    for name in ("AGENT_SANDBOX_API_KEY", "AGENT_SANDBOX_VERSION", "AGENT_SANDBOX_PORT", "AGENT_SANDBOX_DEFAULT_IMAGE"):
        assert f"${{{name}" in compose, name
