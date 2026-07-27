"""Centralized, environment-driven configuration for Page Pulse.

All tunables (timeouts, concurrency limits, cache TTLs, rate limits)
live here and are overridable via environment variables or a `.env`
file, so the same image can be promoted from dev -> staging -> prod
without a code change.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the Page Pulse service."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- General ---
    app_name: str = "Page Pulse"
    app_version: str = "1.0.0"
    environment: Literal["development", "staging", "production", "test"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    log_json: bool = True

    # --- HTTP server ---
    host: str = "0.0.0.0"
    port: int = 8000

    # --- Outbound HTTP (httpx) ---
    request_timeout_seconds: float = Field(default=8.0, gt=0, le=60)
    connect_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    max_redirects: int = Field(default=5, ge=0, le=20)
    user_agent: str = "PagePulse-Audit-Bot/1.0 (+https://example.com/bot)"

    # --- Concurrency control ---
    max_concurrent_audits: int = Field(default=20, ge=1, le=1000)

    # --- Caching (Redis) ---
    redis_url: str = "redis://localhost:6379/0"
    cache_enabled: bool = True
    cache_ttl_seconds: int = Field(default=300, ge=0, le=86_400)
    cache_key_prefix: str = "pagepulse:audit:"

    # --- Rate limiting (SlowAPI + Redis storage) ---
    rate_limit_enabled: bool = True
    rate_limit_default: str = "60/minute"
    rate_limit_audit: str = "10/minute"
    rate_limit_storage_url: str = "redis://localhost:6379/1"

    # --- Security / SSRF protections ---
    allowed_schemes: tuple[str, ...] = ("http", "https")
    block_private_networks: bool = True
    max_url_length: int = Field(default=2048, ge=64, le=8192)

    # --- CORS ---
    cors_allow_origins: tuple[str, ...] = ("*",)

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.upper()


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (singleton for process lifetime)."""
    return Settings()
