from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignore extra fields in .env
    )

    # Database - single connection URL
    database_url: str

    # Connection pool settings
    db_pool_min_size: int = 10
    db_pool_max_size: int = 20
    db_pool_max_queries: int = 50000
    db_pool_max_inactive_connection_lifetime: float = 300.0
    db_command_timeout: float = 60.0

    # API settings
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Environment
    environment: str = "development"


# Global settings instance
settings = Settings()
