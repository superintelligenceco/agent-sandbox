from __future__ import annotations

import pytest

from agent_sandbox.errors import InvalidRequestError
from agent_sandbox.manager import normalize_path, require_in_workspace


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("main.py", "/workspace/main.py"),
        ("src/../main.py", "/workspace/main.py"),
        ("/etc/os-release", "/etc/os-release"),
        ("/workspace/a//b/", "/workspace/a/b"),
    ],
)
def test_normalize_path(raw: str, expected: str) -> None:
    assert normalize_path(raw) == expected


@pytest.mark.parametrize("raw", ["", "a\x00b"])
def test_normalize_path_rejects_garbage(raw: str) -> None:
    with pytest.raises(InvalidRequestError):
        normalize_path(raw)


@pytest.mark.parametrize("raw", ["../etc/passwd", "/etc/passwd", "/workspace", "/workspace/..", "/workspacex/a"])
def test_writes_must_stay_in_workspace(raw: str) -> None:
    with pytest.raises(InvalidRequestError):
        require_in_workspace(raw)


def test_write_inside_workspace_is_allowed() -> None:
    assert require_in_workspace("a/b.txt") == "/workspace/a/b.txt"
