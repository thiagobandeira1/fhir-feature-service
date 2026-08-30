"""Service configuration. Env-only (prefix ``FF_``), never from committed files."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings; every field overridable via ``FF_*`` environment variables."""

    model_config = SettingsConfigDict(env_prefix="FF_", frozen=True)

    db_path: Path = Path("fhir_features.duckdb")
    max_bundle_bytes: int = 20 * 1024 * 1024
    bind_host: str = "127.0.0.1"
    bind_port: int = 8000


def get_settings() -> Settings:
    """Read settings from the environment (fresh each call; cheap and test-friendly)."""
    return Settings()
