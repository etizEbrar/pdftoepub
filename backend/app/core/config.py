from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Which deployment this process is. Production tightens several defaults —
    # see `apply_environment_defaults` — so that forgetting to set something is
    # safe rather than exposing an interactive API browser to the internet.
    environment: str = "development"  # development | staging | production

    # Server
    host: str = "127.0.0.1"
    port: int = 8000

    # Abuse protection. The upload limit is the one that matters: conversions are
    # minutes of CPU, so an unthrottled endpoint is a free way to exhaust the
    # box. Counted per client IP in-process (see api/ratelimit.py).
    rate_limit_uploads_per_hour: int = 20
    # Deliberately generous. Starting a conversion is the expensive operation and
    # is limited separately; polling progress is a cheap database read that a
    # client does once a second for the length of a conversion. Several people
    # behind one NAT address share this budget, so a tight limit here would
    # reject legitimate users long before it inconvenienced an attacker. This is
    # a flood backstop, not the primary control.
    rate_limit_requests_per_minute: int = 600
    rate_limit_enabled: bool = True

    # Comma-separated origins allowed to call the API from a browser. Empty means
    # no browser origin is allowed, which is correct for a native-app-only
    # backend: the iOS client is not subject to CORS.
    cors_allow_origins: str = ""

    # The interactive docs describe every endpoint and schema. Useful in
    # development, needless attack surface in production.
    expose_api_docs: bool = True

    # Storage
    data_dir: Path = Path(__file__).resolve().parents[2] / "data"
    job_ttl_hours: int = 24
    max_upload_mb: int = 200
    # A crafted PDF can declare an enormous page count and occupy a worker
    # indefinitely. Refuse up front rather than discovering it mid-conversion.
    max_page_count: int = 2000
    # Hard ceiling on one conversion. A 500-page book takes ~25s; anything an
    # order of magnitude beyond that is stuck, and holding a worker forever
    # denies service to everyone else.
    conversion_timeout_seconds: int = 1800
    # Conversions that run at once. Each already off-loads its CPU-bound work to
    # a thread, so this bounds memory and CPU rather than concurrency of the API.
    job_concurrency: int = 2

    # AI — off by default. A normal conversion must work with none of these set.
    ai_provider: str = "none"  # none | local | anthropic | openai | google
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-4-5-20251001"
    openai_api_key: str | None = None
    google_api_key: str | None = None
    ai_confidence_threshold: float = 0.70
    ai_no_ai_zone_threshold: float = 0.90

    # OCR — local Tesseract only. No network, no API key, no per-page cost.
    ocr_enabled: bool = True
    tesseract_binary: str = "tesseract"
    tessdata_prefix: str | None = None  # auto-detected when unset
    ocr_languages: str = "eng"  # "+"-joined Tesseract codes, e.g. "eng+tur"
    ocr_dpi: int = 300
    # A page whose native text layer holds fewer characters than this is a
    # candidate for OCR; see pipeline/ocr/classify.py for the full decision.
    ocr_min_native_chars_per_page: int = 60
    # Per-word Tesseract confidences below this are dropped rather than trusted.
    ocr_min_word_confidence: float = 40.0
    # A region whose mean OCR confidence falls below this is preserved as a
    # high-resolution image instead of as (probably wrong) text.
    #
    # Measured against upside-down Latin text, Tesseract returns confident-looking
    # nonsense in the mid-60s ("OUI] 1X9} JO" at 66.5), while genuinely readable
    # text lands in the 90s. The floor sits above that garbage band deliberately:
    # a page we can't read must become a faithful image, never invented words.
    ocr_min_region_confidence: float = 75.0
    # Above this, the upright pass is trusted outright and the rotated retries
    # are skipped — that's what keeps OCR to a single pass on normal scans.
    ocr_confident_accept_threshold: float = 88.0
    ocr_detect_rotation: bool = True

    # Image fallback rasterization
    fallback_render_dpi: int = 200
    fallback_max_pixels: int = 4_000_000  # caps memory on very large regions

    # Structural reconstruction confidence floors. Below these, the pipeline
    # prefers a faithful image fallback over a guessed semantic structure.
    table_min_confidence: float = 0.70
    formula_min_confidence: float = 0.70

    # Local text repair of extraction/OCR defects. No network, no API key.
    text_repair_enabled: bool = True

    # EPUB validation
    epubcheck_binary: str = "epubcheck"

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() == "production"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jobs.sqlite3"


def apply_environment_defaults(s: Settings) -> Settings:
    """Tighten anything whose safe value differs in production.

    Done here rather than in the field defaults so that a deployment which sets
    only ENVIRONMENT=production still gets the hardened behaviour, instead of
    inheriting development conveniences by omission.
    """
    if s.is_production:
        # Only force the *safe* direction: an operator who deliberately enabled
        # docs in production keeps them, but forgetting to think about it does
        # not expose them.
        if "EXPOSE_API_DOCS" not in _env_keys():
            s.expose_api_docs = False
        if s.host == "127.0.0.1" and "HOST" not in _env_keys():
            # A container must bind all interfaces or the platform's health
            # check can never reach it.
            s.host = "0.0.0.0"  # noqa: S104 - intentional inside a container
    return s


def _env_keys() -> set[str]:
    import os

    return {k.upper() for k in os.environ}


settings = apply_environment_defaults(Settings())
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.uploads_dir.mkdir(parents=True, exist_ok=True)
settings.jobs_dir.mkdir(parents=True, exist_ok=True)
