"""Client for the DigitalOcean Serverless Inference API (OpenAI-compatible).

The concrete client is defined by the :class:`LLMClient` Protocol so tests can
inject a deterministic fake without any network access.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import httpx


@runtime_checkable
class LLMClient(Protocol):
    async def chat(self, model: str, messages: list[dict], timeout: float) -> str:
        """Return the assistant message content for a chat completion."""
        ...

    async def aclose(self) -> None:
        ...


class DOInferenceClient:
    """Calls the DigitalOcean Serverless Inference chat completions endpoint."""

    def __init__(self, base_url: str, api_key: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    async def chat(self, model: str, messages: list[dict], timeout: float) -> str:
        resp = await self._client.post(
            "/chat/completions",
            json={"model": model, "messages": messages},
            timeout=timeout,
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data["choices"][0]["message"]["content"]

    async def aclose(self) -> None:
        await self._client.aclose()
