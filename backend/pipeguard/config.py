from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "PipeGuard API"
    app_env: str = "development"
    database_url: str = "sqlite:///./pipeguard.db"
    # Seconds to wait for a PostgreSQL connection before giving up. libpq's own
    # default is to wait forever, which turns an unreachable database into a
    # process that never starts and never says why.
    database_connect_timeout: int = 10
    null_rate_threshold: float = 0.05
    duplicate_rate_threshold: float = 0.01
    freshness_hours_threshold: float = 24.0
    row_count_drop_threshold: float = 0.30
    row_count_history_size: int = 5
    # Newest runs to keep per pipeline; older ones are pruned with their checks
    # and analyses. Set to 0 to disable pruning and retain every run.
    run_retention_limit: int = 500
    # Shared secret required to report a run. Empty disables the ingest endpoint
    # entirely: it accepts writes from outside, so it must not be open by default.
    ingest_api_key: str = ""
    llm_enabled: bool = False
    llm_provider: Literal["openai", "anthropic"] = "openai"
    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str = ""
    llm_model: str = Field(default="", max_length=120)
    llm_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    llm_max_output_tokens: int = Field(default=1024, ge=128, le=4096)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
