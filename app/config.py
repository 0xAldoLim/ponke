from decimal import Decimal
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet
from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: str = "development"
    app_secret_key: SecretStr = SecretStr("")
    telegram_bot_token: SecretStr = SecretStr("")
    allowed_telegram_user_ids: str = ""
    openai_api_key: SecretStr = SecretStr("")
    openai_primary_model: str = "gpt-6-astra"
    openai_fast_model: str = ""
    database_url: SecretStr = SecretStr("postgresql+asyncpg://ponke:ponke@localhost:5432/ponke")
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    google_redirect_uri: str = "http://localhost:8000/oauth/google/callback"
    google_calendar_id: str = "primary"
    user_timezone: str = "Asia/Jakarta"
    default_currency: str = "IDR"
    daily_briefing_enabled: bool = True
    daily_briefing_time: str = "07:00"
    daily_briefing_sections: str = "today,reminders,finance,notable,priorities"
    max_upload_bytes: int = 10_000_000
    requests_per_minute: int = 12
    large_transaction_threshold: Decimal = Decimal("10000000")
    model_timeout_seconds: int = 90
    primary_input_cost_per_million: Decimal | None = None
    primary_output_cost_per_million: Decimal | None = None
    fast_input_cost_per_million: Decimal | None = None
    fast_output_cost_per_million: Decimal | None = None

    @field_validator(
        "primary_input_cost_per_million",
        "primary_output_cost_per_million",
        "fast_input_cost_per_million",
        "fast_output_cost_per_million",
        mode="before",
    )
    @classmethod
    def blank_cost(cls, value):
        return None if value == "" else value

    @field_validator("user_timezone")
    @classmethod
    def valid_timezone(cls, value):
        ZoneInfo(value)
        return value

    @field_validator("daily_briefing_time")
    @classmethod
    def valid_time(cls, value):
        from datetime import time

        time.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def validate_limits(self):
        if self.requests_per_minute < 1 or not 1 <= self.max_upload_bytes <= 20_000_000:
            raise ValueError("Invalid rate or upload limit")
        return self

    @property
    def allowed_ids(self) -> set[int]:
        return {int(item.strip()) for item in self.allowed_telegram_user_ids.split(",") if item.strip()}

    def validate_runtime(self):
        if not self.allowed_ids:
            raise ValueError("ALLOWED_TELEGRAM_USER_IDS must not be empty")
        for field in ("telegram_bot_token", "openai_api_key", "app_secret_key"):
            if not getattr(self, field).get_secret_value():
                raise ValueError(f"Missing {field.upper()}")
        Fernet(self.app_secret_key.get_secret_value().encode())
        if self.app_env == "production" and not self.database_url.get_secret_value().startswith(
            "postgresql+"
        ):
            raise ValueError("Production requires PostgreSQL")
