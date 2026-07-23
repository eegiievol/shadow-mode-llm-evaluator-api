"""Bounded, decoupled shadow-evaluation pool.

Design goals (per spec):
  * The candidate's latency / errors must NEVER affect the primary response.
    -> The primary path only ever calls ``submit()``, which is non-blocking.
  * Background work must be bounded to protect the primary application
    footprint. -> A fixed-size ``asyncio.Queue`` plus a fixed number of worker
    tasks caps both the queue depth and the concurrency. When the queue is
    full we SHED LOAD (drop the evaluation) instead of growing memory.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Any

from .config import RuntimeConfig, Settings
from .evaluator import evaluate
from .llm_client import LLMClient
from .metrics import Metrics
from .storage import TraceStore

logger = logging.getLogger("shadow")


@dataclass
class ShadowJob:
    messages: list[dict]
    primary_text: str | None
    request_payload: Any


class ShadowExecutor:
    def __init__(
        self,
        *,
        client: LLMClient,
        metrics: Metrics,
        store: TraceStore,
        settings: Settings,
        runtime: RuntimeConfig,
        rng: random.Random | None = None,
    ) -> None:
        self._client = client
        self._metrics = metrics
        self._store = store
        self._settings = settings
        self._runtime = runtime
        self._rng = rng or random.Random()
        self._queue: asyncio.Queue[ShadowJob] = asyncio.Queue(
            maxsize=settings.shadow_queue_size
        )
        self._workers: list[asyncio.Task] = []

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        if self._workers:
            return
        for i in range(self._settings.shadow_workers):
            self._workers.append(
                asyncio.create_task(self._worker_loop(), name=f"shadow-worker-{i}")
            )

    async def stop(self) -> None:
        for task in self._workers:
            task.cancel()
        for task in self._workers:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._workers.clear()

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    # ------------------------------------------------------------------ #
    # Producer side (called from the synchronous request path)
    # ------------------------------------------------------------------ #
    def submit(self, job: ShadowJob) -> bool:
        """Enqueue a shadow evaluation without ever blocking the caller.

        Returns True if the job was accepted, False if it was sampled out or
        shed due to a full queue.
        """
        # Sampling: only mirror a configurable percentage of traffic.
        if self._rng.uniform(0.0, 100.0) > self._runtime.shadow_percentage:
            self._metrics.shadow_skipped += 1
            return False

        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull:
            # LOAD SHEDDING: drop the evaluation rather than grow memory.
            self._metrics.shadow_shed += 1
            return False

        self._metrics.shadow_enqueued += 1
        return True

    # ------------------------------------------------------------------ #
    # Consumer side (background workers)
    # ------------------------------------------------------------------ #
    async def _worker_loop(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                await self._process(job)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a worker must never die
                logger.exception("unexpected error in shadow worker")
                self._metrics.shadow_errors += 1
            finally:
                self._queue.task_done()

    async def _process(self, job: ShadowJob) -> None:
        try:
            candidate_text = await asyncio.wait_for(
                self._client.chat(
                    self._settings.candidate_model,
                    job.messages,
                    self._settings.candidate_timeout,
                ),
                timeout=self._settings.candidate_timeout,
            )
        except asyncio.TimeoutError:
            self._metrics.shadow_timeouts += 1
            return
        except Exception:  # noqa: BLE001 - candidate failures are isolated
            self._metrics.shadow_errors += 1
            return

        result = evaluate(job.primary_text, candidate_text)
        self._metrics.shadow_completed += 1

        if result.action_match:
            self._metrics.exact_matches += 1
            return

        self._metrics.mismatches += 1
        await self._store.record_mismatch(
            primary_model=self._settings.primary_model,
            candidate_model=self._settings.candidate_model,
            request=job.request_payload,
            primary_output=job.primary_text,
            candidate_output=candidate_text,
            primary_action=result.primary_action,
            candidate_action=result.candidate_action,
        )
