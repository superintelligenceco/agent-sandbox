from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_sandbox import __version__
from agent_sandbox.cli import main

ROOT = Path(__file__).resolve().parents[2]


def test_openapi_file_is_current(tmp_path: Path) -> None:
    out = tmp_path / "openapi.json"
    assert main(["openapi", "-o", str(out)]) == 0
    committed = (ROOT / "docs" / "openapi.json").read_text()
    assert out.read_text() == committed, "run `agent-sandbox openapi -o docs/openapi.json`"
    spec = json.loads(committed)
    assert spec["info"]["version"] == __version__


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--version"])
    assert capsys.readouterr().out.strip() == f"agent-sandbox {__version__}"


def test_serve_refuses_to_start_without_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AGENT_SANDBOX_API_KEYS", "AGENT_SANDBOX_INSECURE_NO_AUTH"):
        monkeypatch.delenv(name, raising=False)
    assert main(["serve"]) == 2
