"""Shared fixtures and a deterministic fake LLM client."""

from __future__ import annotations

import asyncio
from typing import Callable

import pytest


class FakeLLMClient:
    """Deterministic, network-free LLM client for tests.

    ``responder`` maps (model, messages) -> either a string (the content) or a
    callable/awaitable that produces one. Raise inside it to simulate errors,
    or ``await asyncio.sleep`` to simulate latency / timeouts.
    """

    def __init__(self, responder: Callable):
        self._responder = responder
        self.calls: list[tuple[str, list[dict]]] = []
        self.closed = False

    async def chat(self, model: str, messages: list[dict], timeout: float) -> str:
        self.calls.append((model, messages))
        result = self._responder(model, messages)
        if asyncio.iscoroutine(result):
            result = await result
        return result

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / "traces.db")
