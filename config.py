"""Configuration management for WhatsApp AI Assistant."""

from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Application settings
    app_name: str = "WhatsApp AI Assistant"
    debug: bool = False
    log_level: str = "INFO"

    # Database settings
    database_url: str = Field(default="postgresql://localhost:5432/whatsapp_ai", description="PostgreSQL connection string")
    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis connection string")

    # WhatsApp API settings
    whatsapp_api_key: str = Field(default="dev_whatsapp_key", description="WhatsApp API key")
    whatsapp_api_url: str = Field(default="https://api.whatsapp.com", description="WhatsApp API base URL")
    whatsapp_webhook_verify_token: str = Field(default="dev_verify_token", description="WhatsApp webhook verification token")

    # Payment provider settings
    payment_provider: str = Field(default="paystack", description="Payment provider (paystack, stripe, etc.)")
    payment_api_key: str = Field(default="dev_payment_key", description="Payment provider API key")
    payment_webhook_secret: str = Field(default="dev_webhook_secret", description="Payment webhook secret key")

    # Logistics/delivery settings
    logistics_provider: Optional[str] = Field(default=None, description="Logistics provider name")
    logistics_api_key: Optional[str] = Field(default=None, description="Logistics API key")

    # AI/OpenAI settings
    openai_api_key: Optional[str] = Field(default=None, description="OpenAI API key for AI features")

    # Business settings
    default_currency: str = Field(default="NGN", description="Default currency code")
    session_timeout_minutes: int = Field(default=30, description="Session timeout in minutes")


# Global settings instance
settings = Settings()
