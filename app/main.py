"""FastAPI application: synchronous primary proxy + decoupled shadow evaluation.

Endpoints:
  * POST /v1/chat  - proxy to the Primary LLM, return immediately, mirror to
                     the Candidate in the background.
  * GET  /metrics  - real-time observability summary.
  * PUT  /config   - runtime update of the shadow routing percentage.
  * GET  /healthz  - liveness probe.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import RuntimeConfig, Settings
from .llm_client import DOInferenceClient, LLMClient
from .metrics import Metrics
from .shadow import ShadowExecutor, ShadowJob
from .storage import TraceStore

logger = logging.getLogger("app")


# --------------------------------------------------------------------------- #
# Request / response schemas
# --------------------------------------------------------------------------- #
class ChatRequest(BaseModel):
    messages: list[dict] = Field(..., min_length=1)


class ChatResponse(BaseModel):
    model: str
    response: str


class ConfigUpdate(BaseModel):
    shadow_percentage: float = Field(..., ge=0.0, le=100.0)


# --------------------------------------------------------------------------- #
# Application factory
# --------------------------------------------------------------------------- #
def create_app(
    settings: Settings | None = None,
    *,
    client: LLMClient | None = None,
    store: TraceStore | None = None,
) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.metrics = Metrics()
        app.state.runtime = RuntimeConfig(settings.shadow_percentage)
        app.state.store = store or TraceStore(settings.sqlite_path)
        app.state.client = client or DOInferenceClient(
            settings.do_inference_base_url, settings.do_inference_api_key
        )
        app.state.executor = ShadowExecutor(
            client=app.state.client,
            metrics=app.state.metrics,
            store=app.state.store,
            settings=settings,
            runtime=app.state.runtime,
        )
        app.state.executor.start()
        try:
            yield
        finally:
            await app.state.executor.stop()
            # Only close clients we own.
            if client is None:
                await app.state.client.aclose()

    app = FastAPI(title="Shadow-Mode LLM Evaluator", lifespan=lifespan)

    @app.post("/v1/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest) -> ChatResponse:
        metrics: Metrics = app.state.metrics
        settings_: Settings = app.state.settings
        metrics.record_request()

        # Synchronous primary call — this is the only thing the user waits on.
        try:
            primary_text = await app.state.client.chat(
                settings_.primary_model, req.messages, settings_.primary_timeout
            )
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502, detail=f"primary LLM error: {exc}"
            ) from exc

        # Fire-and-forget shadow evaluation. Non-blocking; never raises.
        app.state.executor.submit(
            ShadowJob(
                messages=req.messages,
                primary_text=primary_text,
                request_payload=req.model_dump(),
            )
        )

        return ChatResponse(model=settings_.primary_model, response=primary_text)

    @app.get("/metrics")
    async def metrics_endpoint() -> dict[str, Any]:
        snap = app.state.metrics.snapshot()
        snap["config"] = {
            "shadow_percentage": app.state.runtime.shadow_percentage,
            "queue_size": app.state.settings.shadow_queue_size,
            "queue_depth": app.state.executor.queue_depth,
            "workers": app.state.settings.shadow_workers,
        }
        return snap

    @app.put("/config")
    async def update_config(cfg: ConfigUpdate) -> dict[str, Any]:
        app.state.runtime.shadow_percentage = cfg.shadow_percentage
        return {"shadow_percentage": app.state.runtime.shadow_percentage}

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
