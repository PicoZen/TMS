from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "TMS-OC"
    app_version: str = "1.0.0"
    debug: bool = False
    log_level: str = "INFO"

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/tms_oc",
        validation_alias="DATABASE_URL",
    )

    secret_key: str = Field(
        default="your-secret-key-change-in-production",
        validation_alias="JWT_SECRET",
    )
    algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(
        default=15,
        validation_alias="ACCESS_TOKEN_EXPIRE_MINUTES",
    )
    refresh_token_expire_days: int = Field(
        default=7,
        validation_alias="REFRESH_TOKEN_EXPIRE_DAYS",
    )

    llm_provider: str = Field(
        default="openai",
        validation_alias="LLM_PROVIDER",
    )
    openai_api_key: str = Field(
        default="",
        validation_alias="OPENAI_KEY",
    )
    mistral_api_key: str = Field(
        default="",
        validation_alias="MISTRAL_KEY",
    )
    mistral_model: str = Field(
        default="mistral-large-latest",
        validation_alias="MISTRAL_MODEL",
    )
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        validation_alias="OLLAMA_URL",
    )
    llm_model: str = "gpt-4o-mini"
    llm_timeout: float = 5.0
    # Number of retry attempts the Celery classification task makes when the
    # LLM call fails, on top of the initial attempt (so 3 = up to 4 total
    # tries). Exponential backoff between attempts is computed by Celery
    # from llm_retry_backoff_max below. See src/tasks/classification_tasks.py.
    llm_max_retries: int = Field(default=3, validation_alias="LLM_MAX_RETRIES")
    llm_retry_backoff_base: float = Field(
        default=1.0, validation_alias="LLM_RETRY_BACKOFF_BASE"
    )
    llm_retry_backoff_max: int = Field(
        default=600, validation_alias="LLM_RETRY_BACKOFF_MAX"
    )

    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias="REDIS_URL",
    )

    # Celery broker (RabbitMQ). Redis above remains the Celery result backend
    # and the rate-limiter store - only the broker moved to RabbitMQ.
    celery_broker_url: str = Field(
        default="amqp://guest:guest@localhost:5672//",
        validation_alias="CELERY_BROKER_URL",
    )

    api_v1_prefix: str = "/api/v1"

    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:8000"],
        validation_alias="CORS_ORIGINS",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()