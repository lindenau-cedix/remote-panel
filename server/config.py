"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PANEL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    secret: str
    whitelist_path: Path = Path(__file__).parent / "whitelist.json"
    audit_path: Path = Path(__file__).parent / "audit.jsonl"
    bind_host: str = "127.0.0.1"
    bind_port: int = 8088
    nonce_ttl_seconds: int = 600
    rate_capacity: int = 30
    rate_refill_per_sec: float = 0.5
    log_level: str = "info"

    # SSH-wrap mode (Plan B). When all three are set, every whitelist
    # entry without an explicit `ssh` block is wrapped in
    # `ssh -i <key> -l <user> <host> -- <argv>`. Entries with their own
    # `ssh` block override these defaults. When all three are None
    # (or empty strings), the executor runs commands locally as before.
    ssh_target_host: Optional[str] = None
    ssh_target_user: Optional[str] = None
    ssh_key_path: Optional[Path] = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_empty_strings_to_none(cls, data):
        """Compose env interpolation `${PANEL_SSH_TARGET_HOST:-}` yields
        empty string when unset; treat that as "not configured"."""
        if isinstance(data, dict):
            for fld in ("ssh_target_host", "ssh_target_user"):
                v = data.get(fld)
                if isinstance(v, str) and v == "":
                    data[fld] = None
            v = data.get("ssh_key_path")
            if isinstance(v, str) and v == "":
                data["ssh_key_path"] = None
        return data

    @model_validator(mode="after")
    def _ssh_target_all_or_none(self):
        """If any SSH target field is set, all three must be."""
        present = [
            self.ssh_target_host is not None,
            self.ssh_target_user is not None,
            self.ssh_key_path is not None,
        ]
        if any(present) and not all(present):
            raise ValueError(
                "PANEL_SSH_TARGET_HOST, PANEL_SSH_TARGET_USER, and "
                "PANEL_SSH_KEY_PATH must all be set or all be unset. "
                f"Got host={self.ssh_target_host!r} "
                f"user={self.ssh_target_user!r} "
                f"key_path={self.ssh_key_path!r}."
            )
        return self