"""Server configuration loaded from environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

ENV_PREFIX = "AGENT_SANDBOX_"


class ConfigError(ValueError):
    """Raised when the configuration is invalid."""


def _parse_bool(name: str, raw: str) -> bool:
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off", ""}:
        return False
    raise ConfigError(f"{name} must be a boolean, got {raw!r}")


def _parse_list(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    """Runtime settings for the sandbox server.

    Every field maps to an ``AGENT_SANDBOX_<FIELD_NAME>`` environment variable.
    """

    api_keys: tuple[str, ...] = ()
    insecure_no_auth: bool = False
    host: str = "127.0.0.1"
    port: int = 8080
    data_dir: Path = Path("./data")

    default_image: str = "python:3.12-slim"
    allowed_images: tuple[str, ...] = ("*",)
    sandbox_user: str = "1000:1000"
    docker_runtime: str = ""
    network_name: str = "agent-sandbox-net"
    allow_network: bool = True

    max_sandboxes: int = 20
    default_timeout_seconds: int = 900
    max_timeout_seconds: int = 86_400
    default_cpus: float = 1.0
    max_cpus: float = 4.0
    default_memory_mb: int = 512
    max_memory_mb: int = 4096
    default_pids_limit: int = 256
    max_pids_limit: int = 4096
    tmp_size_mb: int = 256

    default_exec_timeout_seconds: int = 60
    max_exec_timeout_seconds: int = 3600
    max_exec_output_bytes: int = 10 * 1024 * 1024
    max_file_bytes: int = 50 * 1024 * 1024
    max_snapshot_bytes: int = 1024 * 1024 * 1024

    reap_interval_seconds: float = 10.0

    def validate(self) -> Settings:
        """Check cross-field invariants and return ``self``."""
        if not self.api_keys and not self.insecure_no_auth:
            raise ConfigError(
                "set AGENT_SANDBOX_API_KEYS to one or more comma-separated keys, "
                "or set AGENT_SANDBOX_INSECURE_NO_AUTH=true for local development"
            )
        for key in self.api_keys:
            if len(key) < 16:
                raise ConfigError("API keys must be at least 16 characters long")
        if self.default_cpus > self.max_cpus:
            raise ConfigError("default_cpus exceeds max_cpus")
        if self.default_memory_mb > self.max_memory_mb:
            raise ConfigError("default_memory_mb exceeds max_memory_mb")
        if self.default_timeout_seconds > self.max_timeout_seconds:
            raise ConfigError("default_timeout_seconds exceeds max_timeout_seconds")
        if self.default_exec_timeout_seconds > self.max_exec_timeout_seconds:
            raise ConfigError("default_exec_timeout_seconds exceeds max_exec_timeout_seconds")
        if self.default_pids_limit > self.max_pids_limit:
            raise ConfigError("default_pids_limit exceeds max_pids_limit")
        if self.max_sandboxes < 1:
            raise ConfigError("max_sandboxes must be at least 1")
        return self

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """Build settings from ``env`` (defaults to ``os.environ``)."""
        source = os.environ if env is None else env
        values: dict[str, object] = {}
        for name, f in cls.__dataclass_fields__.items():
            env_name = ENV_PREFIX + name.upper()
            if env_name not in source:
                continue
            raw = source[env_name]
            default = f.default
            try:
                if isinstance(default, bool):
                    values[name] = _parse_bool(env_name, raw)
                elif isinstance(default, int):
                    values[name] = int(raw)
                elif isinstance(default, float):
                    values[name] = float(raw)
                elif isinstance(default, tuple):
                    values[name] = _parse_list(raw)
                elif isinstance(default, Path):
                    values[name] = Path(raw)
                else:
                    values[name] = raw
            except ValueError as exc:
                if isinstance(exc, ConfigError):
                    raise
                raise ConfigError(f"invalid value for {env_name}: {raw!r}") from exc
        return cls(**values).validate()  # type: ignore[arg-type]
