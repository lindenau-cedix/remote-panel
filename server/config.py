"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

from pathlib import Path

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
    bind_port: int = 8000
    nonce_ttl_seconds: int = 600
    rate_capacity: int = 30
    rate_refill_per_sec: float = 0.5
    log_level: str = "info"