"""Configuration management for SEO Outreach Agent FastAPI application."""

import os
from typing import List
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",  # Ignore extra environment variables not defined in this model
    }

    # Application
    app_name: str = "SEO Outreach Agent API"
    app_version: str = "1.0.0"
    environment: str = Field(default="development", description="Environment name")
    debug: bool = Field(default=False, description="Debug mode")
    log_level: str = Field(default="INFO", description="Logging level")

    # API
    api_v1_prefix: str = "/api/v1"
    docs_url: str = "/docs"
    redoc_url: str = "/redoc"

    # CORS
    cors_origins: List[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:8000"],
        description="Allowed CORS origins",
    )

    # Rate Limiting
    rate_limit_per_minute: int = Field(
        default=10, description="Rate limit per IP per minute"
    )
    rate_limit_per_hour: int = Field(
        default=100, description="Rate limit per IP per hour"
    )

    # OpenAI
    openai_api_key: str = Field(..., description="OpenAI API key")
    openai_model: str = Field(default="gpt-4o", description="OpenAI model to use")

    # SMTP (Optional)
    smtp_host: str = Field(default="", description="SMTP host")
    smtp_port: int = Field(default=587, description="SMTP port")
    smtp_user: str = Field(default="", description="SMTP username")
    smtp_password: str = Field(default="", description="SMTP password")
    from_email: str = Field(default="", description="From email address")
    from_name: str = Field(default="SEO Outreach", description="From name")

    # Output Directory
    output_dir: str = Field(
        default="output", description="Output directory for results"
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        """Parse CORS origins from string or list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v):
        """Validate log level."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of {valid_levels}")
        return v.upper()

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v):
        """Validate environment."""
        valid_envs = ["development", "staging", "production"]
        if v.lower() not in valid_envs:
            raise ValueError(f"Environment must be one of {valid_envs}")
        return v.lower()


# Global settings instance
settings = Settings()
