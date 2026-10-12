"""Load local settings without requiring credentials for the offline demo."""
import os
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr, field_validator
from ai_pulse.storage import ROOT


class Settings(BaseModel):
    timezone: str = 'America/New_York'
    story_count: int = Field(default=5, ge=1, le=5)
    lookback_hours: int = Field(default=48, ge=1, le=72)
    gemini_api_key: SecretStr | None = None
    gemini_model: str | None = None
    ollama_model: str = 'qwen2:7b'

    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls, value):
        """Reject a timezone name that Python cannot use for date display."""
        ZoneInfo(value)
        return value


def load_settings() -> Settings:
    """Read local environment settings and validate their allowed values."""
    load_dotenv(ROOT / '.env')
    return Settings(
        timezone=os.getenv('APP_TIMEZONE', 'America/New_York'),
        story_count=os.getenv('DIGEST_STORY_COUNT', '5'),
        lookback_hours=os.getenv('NEWS_LOOKBACK_HOURS', '48'),
        gemini_api_key=os.getenv('GEMINI_API_KEY'),
        gemini_model=os.getenv('GEMINI_MODEL'),
        ollama_model=os.getenv('OLLAMA_MODEL', 'qwen2:7b'),
    )
