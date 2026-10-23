"""Application settings loaded from environment / .env with secure defaults."""
from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# config.py lives at backend/app/core/config.py -> backend root is two levels above "core".
BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore", env_prefix="SPIDER_"
    )

    app_name: str = "SPIDER AI"
    environment: str = "development"
    database_url: str = f"sqlite:///{(BACKEND_ROOT / 'spider_ai.db').as_posix()}"
    storage_dir: Path = BACKEND_ROOT / "storage"
    rendered_dir: Path = BACKEND_ROOT / "storage" / "rendered"

    # A built interface (frontend/dist) is served from the same origin as the API, so a
    # single process can run the whole product in production. Set SPIDER_SERVE_FRONTEND=false
    # to keep the API-only behaviour used by the vite dev server.
    frontend_dist: Path = BACKEND_ROOT.parent / "frontend" / "dist"
    serve_frontend: bool = True

    # Auth. A development key is generated on the fly so the app runs without setup;
    # production deployments must provide SPIDER_SECRET_KEY.
    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    access_token_expire_minutes: int = 720

    max_upload_bytes: int = 40 * 1024 * 1024
    allowed_upload_extensions: tuple[str, ...] = (
        ".pdf", ".docx", ".txt", ".md", ".markdown", ".html", ".htm", ".csv", ".tsv",
    )

    # Provider-independent AI layer. Disabled until a key is configured; the local
    # deterministic analysis engine is always active.
    ai_provider: str = "disabled"  # disabled | openai_compatible | ollama
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str = ""
    ai_model: str = "gpt-4o-mini"
    ai_timeout_seconds: int = 60
    ai_max_input_characters: int = 60_000

    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")

    @property
    def ai_enabled(self) -> bool:
        return self.ai_provider != "disabled" and bool(self.ai_api_key or "ollama" in self.ai_provider)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    settings.rendered_dir.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
