"""Typed application settings loaded from the environment and ``.env`` (spec §13)."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class AppEnv(StrEnum):
    DEV = "dev"
    PROD = "prod"
    TEST = "test"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class StructuredMode(StrEnum):
    AUTO = "auto"
    JSON_SCHEMA = "json_schema"
    JSON_OBJECT = "json_object"


class Settings(BaseSettings):
    """Every key here is documented in spec §13.2."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # Application
    APP_ENV: AppEnv = AppEnv.DEV
    APP_VERSION: str = "1.0.0"
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = Field(8000, ge=1024, le=65535)

    # Storage
    DATABASE_PATH: Path = Path("data/skillmirror.db")
    UPLOAD_DIR: Path = Path("data/uploads")
    KEEP_UPLOADS: bool = False
    MAX_UPLOAD_MB: int = Field(5, ge=1, le=25)
    MAX_RESUME_CHARS: int = Field(20000, ge=1000, le=100000)
    MAX_JD_CHARS: int = Field(12000, ge=500, le=100000)
    MIN_TEXT_CHARS: int = Field(200, ge=50, le=2000)

    # OpenRouter
    OPENROUTER_API_KEY: str | None = None
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL_EXTRACT: str = "openai/gpt-4o-mini"
    OPENROUTER_MODEL_ROADMAP: str = "anthropic/claude-sonnet-4.5"
    OPENROUTER_MODEL_ROADMAP_FALLBACK: str | None = None
    OPENROUTER_APP_URL: str = "http://127.0.0.1:8000"
    OPENROUTER_APP_NAME: str = "SkillMirror"
    OPENROUTER_DENY_DATA_COLLECTION: bool = True

    # LLM behaviour
    LLM_ENABLED: bool = True
    LLM_DISAMBIGUATE: bool = True
    LLM_TIMEOUT_EXTRACT_S: int = Field(60, ge=10, le=180)
    LLM_TIMEOUT_ROADMAP_S: int = Field(120, ge=30, le=300)
    LLM_MAX_TRANSPORT_RETRIES: int = Field(3, ge=1, le=5)
    LLM_STRUCTURED_MODE: StructuredMode = StructuredMode.AUTO
    LLM_CACHE_ENABLED: bool = True
    LLM_CACHE_TTL_DAYS: int = Field(30, ge=1, le=365)

    # Roadmap and scoring
    ROADMAP_DEFAULT_WEEKS: int = Field(6, ge=2, le=12)
    ROADMAP_DEFAULT_HOURS_PER_WEEK: int = Field(8, ge=1, le=40)
    SCORING_ADJACENT_CREDIT: float = Field(0.25, ge=0.0, le=0.5)

    # Jobs and limits
    JOB_MAX_CONCURRENT: int = Field(2, ge=1, le=4)
    JOB_STALE_AFTER_S: int = Field(300, ge=60, le=3600)
    MAX_ANALYSES_PER_HOUR: int = Field(10, ge=1, le=100)

    # OCR for scanned PDFs (Tesseract must be installed and on PATH)
    OCR_ENABLE: bool = False
    OCR_DPI: int = Field(300, ge=150, le=600)
    OCR_LANG: str = "eng"

    # Logging
    LOG_LEVEL: LogLevel = LogLevel.INFO
    LOG_PROMPT_CONTENT: bool = False

    @property
    def llm_available(self) -> bool:
        """True only when the feature is on *and* a key is present (spec §12.10)."""
        return self.LLM_ENABLED and bool(self.OPENROUTER_API_KEY)

    @field_validator("DATABASE_PATH", "UPLOAD_DIR", mode="before")
    @classmethod
    def _resolve_paths(cls, value: object) -> Path:
        path = Path(str(value))
        return path if path.is_absolute() else (PROJECT_ROOT / path)

    @property
    def data_dir(self) -> Path:
        return self.DATABASE_PATH.parent

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def upload_dir(self) -> Path:
        # UPLOAD_DIR is relative to the project root unless absolute.
        return self.UPLOAD_DIR if self.UPLOAD_DIR.is_absolute() else PROJECT_ROOT / self.UPLOAD_DIR


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Used by tests after environment overrides."""
    get_settings.cache_clear()
