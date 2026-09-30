from __future__ import annotations

from pathlib import Path

import pytest

from agent_sandbox.config import ConfigError, Settings


def test_requires_keys_or_explicit_insecure_mode() -> None:
    with pytest.raises(ConfigError, match="AGENT_SANDBOX_API_KEYS"):
        Settings.from_env({})
    assert Settings.from_env({"AGENT_SANDBOX_INSECURE_NO_AUTH": "true"}).insecure_no_auth


def test_parses_every_field_type() -> None:
    settings = Settings.from_env(
        {
            "AGENT_SANDBOX_API_KEYS": "aaaaaaaaaaaaaaaa, bbbbbbbbbbbbbbbb ,",
            "AGENT_SANDBOX_PORT": "9000",
            "AGENT_SANDBOX_DEFAULT_CPUS": "0.5",
            "AGENT_SANDBOX_ALLOW_NETWORK": "no",
            "AGENT_SANDBOX_DATA_DIR": "/var/lib/sandbox",
            "AGENT_SANDBOX_DEFAULT_IMAGE": "alpine:3.20",
            "UNRELATED": "ignored",
        }
    )
    assert settings.api_keys == ("aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb")
    assert settings.port == 9000
    assert settings.default_cpus == 0.5
    assert settings.allow_network is False
    assert settings.data_dir == Path("/var/lib/sandbox")
    assert settings.default_image == "alpine:3.20"


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"AGENT_SANDBOX_API_KEYS": "short"}, "at least 16"),
        ({"AGENT_SANDBOX_PORT": "eighty"}, "AGENT_SANDBOX_PORT"),
        ({"AGENT_SANDBOX_ALLOW_NETWORK": "maybe"}, "boolean"),
        ({"AGENT_SANDBOX_DEFAULT_CPUS": "8"}, "default_cpus"),
        ({"AGENT_SANDBOX_DEFAULT_MEMORY_MB": "999999"}, "default_memory_mb"),
        ({"AGENT_SANDBOX_MAX_SANDBOXES": "0"}, "max_sandboxes"),
        ({"AGENT_SANDBOX_DEFAULT_TIMEOUT_SECONDS": "999999"}, "default_timeout_seconds"),
    ],
)
def test_rejects_invalid_values(env: dict[str, str], message: str) -> None:
    env.setdefault("AGENT_SANDBOX_INSECURE_NO_AUTH", "1")
    with pytest.raises(ConfigError, match=message):
        Settings.from_env(env)
