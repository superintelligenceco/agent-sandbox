"""Property-based tests for the pure logic every request depends on."""

from __future__ import annotations

import json
import posixpath

import pytest
from hypothesis import given
from hypothesis import strategies as st

from agent_sandbox.backends.base import WORKSPACE, SandboxSpec
from agent_sandbox.config import ConfigError, _parse_bool, _parse_list
from agent_sandbox.errors import InvalidRequestError
from agent_sandbox.manager import SandboxRecord, SnapshotRecord, normalize_path, require_in_workspace

# Path segments biased toward the characters that matter for traversal.
segment = st.one_of(
    st.sampled_from(["", ".", "..", "...", "workspace", "etc", "a", "b"]),
    st.text(alphabet=st.characters(blacklist_characters="/\x00"), max_size=8),
)
raw_path = st.builds(
    lambda leading, parts: ("/" if leading else "") + "/".join(parts),
    st.booleans(),
    st.lists(segment, min_size=1, max_size=8),
).filter(bool)


@given(raw_path)
def test_normalize_path_is_absolute_and_idempotent(path: str) -> None:
    normalized = normalize_path(path)
    assert normalized.startswith("/")
    assert normalize_path(normalized) == normalized
    assert ".." not in normalized.split("/")


@given(raw_path)
def test_require_in_workspace_never_escapes(path: str) -> None:
    try:
        result = require_in_workspace(path)
    except InvalidRequestError:
        return
    assert result.startswith(WORKSPACE + "/")
    assert posixpath.commonpath([result, WORKSPACE]) == WORKSPACE
    assert result != WORKSPACE


@given(st.text(), st.text())
def test_nul_bytes_are_always_rejected(head: str, tail: str) -> None:
    with pytest.raises(InvalidRequestError):
        normalize_path(head + "\x00" + tail)


@given(
    st.lists(st.text(alphabet=st.characters(blacklist_characters=",", blacklist_categories=["Z", "Cc"]), min_size=1))
)
def test_parse_list_round_trips_comma_joined_values(items: list[str]) -> None:
    assert _parse_list(",".join(items)) == tuple(item for item in items if item.strip())
    assert _parse_list(" , ".join(items)) == tuple(item.strip() for item in items if item.strip())


@given(st.text())
def test_parse_bool_accepts_only_known_words(raw: str) -> None:
    known = {"1", "true", "yes", "on", "0", "false", "no", "off", ""}
    try:
        value = _parse_bool("X", raw)
    except ConfigError:
        assert raw.strip().lower() not in known
    else:
        assert value is (raw.strip().lower() in {"1", "true", "yes", "on"})


specs = st.builds(
    SandboxSpec,
    image=st.text(min_size=1, max_size=40),
    cpus=st.floats(min_value=0.1, max_value=64, allow_nan=False),
    memory_mb=st.integers(min_value=16, max_value=1 << 20),
    pids_limit=st.integers(min_value=1, max_value=1 << 16),
    network=st.booleans(),
    read_only_rootfs=st.booleans(),
    env=st.dictionaries(st.text(min_size=1, max_size=10), st.text(max_size=20), max_size=5),
)
timestamps = st.floats(min_value=0, max_value=4e9, allow_nan=False)


@given(st.text(min_size=1), specs, timestamps, timestamps, st.none() | st.text(min_size=1))
def test_sandbox_record_survives_a_json_round_trip(
    sandbox_id: str, spec: SandboxSpec, created: float, expires: float, source: str | None
) -> None:
    record = SandboxRecord(sandbox_id, spec, created, expires, source)
    assert SandboxRecord.from_json(json.loads(json.dumps(record.to_json()))) == record


@given(st.text(min_size=1), st.text(min_size=1), timestamps, st.integers(min_value=0), specs, st.none() | st.text())
def test_snapshot_record_survives_a_json_round_trip(
    snapshot_id: str, sandbox_id: str, created: float, size: int, spec: SandboxSpec, name: str | None
) -> None:
    record = SnapshotRecord(snapshot_id, sandbox_id, created, size, spec, name)
    assert SnapshotRecord.from_json(json.loads(json.dumps(record.to_json()))) == record
