from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Prefixed so the app never picks up unrelated variables such as CLAUDE_EFFORT,
    # which Claude Code itself sets in its environment.
    model_config = SettingsConfigDict(
        env_prefix="COPILOT_", env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True
    )

    anthropic_api_key: str | None = Field(
        None, validation_alias=AliasChoices("ANTHROPIC_API_KEY", "COPILOT_ANTHROPIC_API_KEY")
    )
    claude_model: str = "claude-opus-5"
    claude_effort: str = "medium"

    # Synthetic market
    market_seed: int = 42
    market_history_size: int = 50_000

    frontend_origin: str = "http://localhost:3000"

    # Guardrails
    chat_rate_limit_per_minute: int = 10
    max_agent_iterations: int = 8


@lru_cache
def get_settings() -> Settings:
    return Settings()
