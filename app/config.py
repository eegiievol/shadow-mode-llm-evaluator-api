"""Application configuration.

`Settings` holds start-up configuration sourced from the environment.
`RuntimeConfig` holds values that can be mutated while the server is running
(currently just the shadow routing percentage, changed via ``PUT /config``).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Immutable start-up settings loaded from the environment / .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # DigitalOcean Serverless Inference API (OpenAI-compatible)
    do_inference_base_url: str = "https://inference.do-ai.run/v1"
    do_inference_api_key: str = ""

    primary_model: str = "llama3.3-70b-instruct"
    candidate_model: str = "openai-gpt-4o-mini"

    primary_timeout: float = 30.0
    candidate_timeout: float = 10.0

    # Bounded shadow pool
    shadow_queue_size: int = 100
    shadow_workers: int = 4
    shadow_percentage: float = 100.0

    sqlite_path: str = "traces.db"


class RuntimeConfig:
    """Mutable runtime configuration.

    Kept deliberately tiny and process-local. Access is safe from asyncio
    coroutines because attribute assignment is atomic under the single-threaded
    event loop.
    """

    def __init__(self, shadow_percentage: float) -> None:
        self._shadow_percentage = _clamp_pct(shadow_percentage)

    @property
    def shadow_percentage(self) -> float:
        return self._shadow_percentage

    @shadow_percentage.setter
    def shadow_percentage(self, value: float) -> None:
        self._shadow_percentage = _clamp_pct(value)


def _clamp_pct(value: float) -> float:
    return max(0.0, min(100.0, float(value)))
