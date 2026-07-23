"""Tests for the bounded shadow executor: load shedding, sampling, isolation,
timeouts, and mismatch persistence."""

from __future__ import annotations

import asyncio
import random

import pytest

from app.config import RuntimeConfig, Settings
from app.metrics import Metrics
from app.shadow import ShadowExecutor, ShadowJob
from app.storage import TraceStore
from tests.conftest import FakeLLMClient


def _job(primary='{"action": "buy"}'):
    return ShadowJob(
        messages=[{"role": "user", "content": "hi"}],
        primary_text=primary,
        request_payload={"messages": []},
    )


def _make(settings, client, store, *, seed=1234):
    metrics = Metrics()
    runtime = RuntimeConfig(settings.shadow_percentage)
    ex = ShadowExecutor(
        client=client,
        metrics=metrics,
        store=store,
        settings=settings,
        runtime=runtime,
        rng=random.Random(seed),
    )
    return ex, metrics, runtime


async def test_load_shedding_when_queue_full(tmp_db):
    """With workers blocked, submits beyond queue capacity are shed, not queued."""
    release = asyncio.Event()

    async def slow_responder(model, messages):
        await release.wait()
        return '{"action": "buy"}'

    settings = Settings(shadow_workers=1, shadow_queue_size=2, shadow_percentage=100)
    client = FakeLLMClient(slow_responder)
    store = TraceStore(tmp_db)
    ex, metrics, _ = _make(settings, client, store)
    ex.start()
    try:
        await asyncio.sleep(0.05)  # let the single worker start and block on get()

        # The 5 submits run synchronously with no await between them, so the
        # worker never gets scheduled to dequeue. The bounded queue accepts
        # exactly `queue_size` (2) and sheds the remaining 3.
        accepted = [ex.submit(_job()) for _ in range(5)]

        assert metrics.shadow_enqueued == 2
        assert metrics.shadow_shed == 3
        assert sum(accepted) == 2

        # Sanity: the queue is capped at its bound, never growing unboundedly.
        assert ex.queue_depth <= settings.shadow_queue_size
    finally:
        release.set()
        await ex.stop()


async def test_sampling_skips_when_percentage_zero(tmp_db):
    settings = Settings(shadow_workers=1, shadow_queue_size=10, shadow_percentage=0)
    client = FakeLLMClient(lambda m, msg: '{"action": "buy"}')
    ex, metrics, _ = _make(settings, client, TraceStore(tmp_db))
    ex.start()
    try:
        for _ in range(5):
            assert ex.submit(_job()) is False
        assert metrics.shadow_skipped == 5
        assert metrics.shadow_enqueued == 0
    finally:
        await ex.stop()


async def test_timeout_counted(tmp_db):
    async def too_slow(model, messages):
        await asyncio.sleep(1.0)
        return '{"action": "buy"}'

    settings = Settings(
        shadow_workers=1, shadow_queue_size=10,
        shadow_percentage=100, candidate_timeout=0.05,
    )
    client = FakeLLMClient(too_slow)
    ex, metrics, _ = _make(settings, client, TraceStore(tmp_db))
    ex.start()
    try:
        ex.submit(_job())
        await asyncio.sleep(0.3)
        assert metrics.shadow_timeouts == 1
        assert metrics.shadow_completed == 0
    finally:
        await ex.stop()


async def test_candidate_error_isolated(tmp_db):
    def boom(model, messages):
        raise RuntimeError("candidate exploded")

    settings = Settings(shadow_workers=1, shadow_queue_size=10, shadow_percentage=100)
    client = FakeLLMClient(boom)
    ex, metrics, _ = _make(settings, client, TraceStore(tmp_db))
    ex.start()
    try:
        ex.submit(_job())
        await asyncio.sleep(0.1)
        assert metrics.shadow_errors == 1
    finally:
        await ex.stop()


async def test_mismatch_persisted_to_sqlite(tmp_db):
    settings = Settings(shadow_workers=1, shadow_queue_size=10, shadow_percentage=100)
    # Candidate disagrees with the primary action -> mismatch.
    client = FakeLLMClient(lambda m, msg: '{"action": "sell"}')
    store = TraceStore(tmp_db)
    ex, metrics, _ = _make(settings, client, store)
    ex.start()
    try:
        ex.submit(_job(primary='{"action": "buy"}'))
        await asyncio.sleep(0.1)
        assert metrics.mismatches == 1
        assert metrics.exact_matches == 0
        assert store.count() == 1
    finally:
        await ex.stop()


async def test_exact_match_not_persisted(tmp_db):
    settings = Settings(shadow_workers=1, shadow_queue_size=10, shadow_percentage=100)
    client = FakeLLMClient(lambda m, msg: '{"action": "buy"}')
    store = TraceStore(tmp_db)
    ex, metrics, _ = _make(settings, client, store)
    ex.start()
    try:
        ex.submit(_job(primary='{"action": "buy"}'))
        await asyncio.sleep(0.1)
        assert metrics.exact_matches == 1
        assert store.count() == 0
    finally:
        await ex.stop()
