from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Server
    host: str = "127.0.0.1"
    port: int = 8000

    # Storage
    data_dir: Path = Path(__file__).resolve().parents[2] / "data"
    job_ttl_hours: int = 24
    max_upload_mb: int = 200

    # AI — off by default. A normal conversion must work with none of these set.
    ai_provider: str = "none"  # none | local | anthropic | openai | google
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-4-5-20251001"
    openai_api_key: str | None = None
    google_api_key: str | None = None
    ai_confidence_threshold: float = 0.70
    ai_no_ai_zone_threshold: float = 0.90

    # EPUB validation
    epubcheck_binary: str = "epubcheck"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jobs.sqlite3"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.uploads_dir.mkdir(parents=True, exist_ok=True)
settings.jobs_dir.mkdir(parents=True, exist_ok=True)
