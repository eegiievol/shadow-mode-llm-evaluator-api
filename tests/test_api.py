"""Integration tests for the HTTP API with a mocked LLM client."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from app.storage import TraceStore
from tests.conftest import FakeLLMClient


def _make_app(responder, tmp_db, **overrides):
    settings = Settings(
        shadow_workers=1,
        shadow_queue_size=10,
        shadow_percentage=100,
        primary_model="primary-x",
        candidate_model="candidate-y",
        **overrides,
    )
    client = FakeLLMClient(responder)
    store = TraceStore(tmp_db)
    app = create_app(settings, client=client, store=store)
    return app, client, store


async def _client(app):
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_chat_returns_primary_immediately(tmp_db):
    def responder(model, messages):
        # Primary and candidate can be distinguished by model name.
        return '{"action": "buy"}' if model == "primary-x" else '{"action": "buy"}'

    app, client, _ = _make_app(responder, tmp_db)
    async with app.router.lifespan_context(app):
        async with await _client(app) as http:
            resp = await http.post(
                "/v1/chat", json={"messages": [{"role": "user", "content": "hi"}]}
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["model"] == "primary-x"
            assert body["response"] == '{"action": "buy"}'


async def test_metrics_reflect_match(tmp_db):
    app, client, _ = _make_app(lambda m, msg: '{"action": "buy"}', tmp_db)
    async with app.router.lifespan_context(app):
        async with await _client(app) as http:
            for _ in range(3):
                await http.post("/v1/chat", json={"messages": [{"role": "u", "content": "x"}]})
            await asyncio.sleep(0.1)  # let shadow workers drain
            snap = (await http.get("/metrics")).json()
            assert snap["total_requests"] == 3
            assert snap["evaluations"]["exact_matches"] == 3
            assert snap["exact_match_rate_pct"] == 100.0


async def test_metrics_reflect_mismatch(tmp_db):
    def responder(model, messages):
        return '{"action": "buy"}' if model == "primary-x" else '{"action": "sell"}'

    app, _, store = _make_app(responder, tmp_db)
    async with app.router.lifespan_context(app):
        async with await _client(app) as http:
            await http.post("/v1/chat", json={"messages": [{"role": "u", "content": "x"}]})
            await asyncio.sleep(0.1)
            snap = (await http.get("/metrics")).json()
            assert snap["evaluations"]["mismatches"] == 1
            assert snap["exact_match_rate_pct"] == 0.0
    assert store.count() == 1  # mismatch was persisted


async def test_primary_failure_returns_502(tmp_db):
    def responder(model, messages):
        if model == "primary-x":
            raise httpx.ConnectError("primary down")
        return '{"action": "buy"}'

    app, _, _ = _make_app(responder, tmp_db)
    async with app.router.lifespan_context(app):
        async with await _client(app) as http:
            resp = await http.post(
                "/v1/chat", json={"messages": [{"role": "u", "content": "x"}]}
            )
            assert resp.status_code == 502


async def test_candidate_failure_does_not_affect_primary(tmp_db):
    def responder(model, messages):
        if model == "candidate-y":
            raise RuntimeError("candidate down")
        return '{"action": "buy"}'

    app, _, _ = _make_app(responder, tmp_db)
    async with app.router.lifespan_context(app):
        async with await _client(app) as http:
            resp = await http.post(
                "/v1/chat", json={"messages": [{"role": "u", "content": "x"}]}
            )
            assert resp.status_code == 200  # user is unaffected
            await asyncio.sleep(0.1)
            snap = (await http.get("/metrics")).json()
            assert snap["shadow"]["errors"] == 1


async def test_put_config_updates_percentage(tmp_db):
    app, _, _ = _make_app(lambda m, msg: '{"action": "buy"}', tmp_db)
    async with app.router.lifespan_context(app):
        async with await _client(app) as http:
            resp = await http.put("/config", json={"shadow_percentage": 25})
            assert resp.status_code == 200
            assert resp.json()["shadow_percentage"] == 25.0
            snap = (await http.get("/metrics")).json()
            assert snap["config"]["shadow_percentage"] == 25.0


async def test_config_percentage_zero_skips_shadow(tmp_db):
    app, _, _ = _make_app(lambda m, msg: '{"action": "buy"}', tmp_db)
    async with app.router.lifespan_context(app):
        async with await _client(app) as http:
            await http.put("/config", json={"shadow_percentage": 0})
            await http.post("/v1/chat", json={"messages": [{"role": "u", "content": "x"}]})
            await asyncio.sleep(0.1)
            snap = (await http.get("/metrics")).json()
            assert snap["shadow"]["skipped"] == 1
            assert snap["shadow"]["enqueued"] == 0


async def test_healthz(tmp_db):
    app, _, _ = _make_app(lambda m, msg: '{"action": "buy"}', tmp_db)
    async with app.router.lifespan_context(app):
        async with await _client(app) as http:
            assert (await http.get("/healthz")).json()["status"] == "ok"


async def test_debug_chat_returns_both_models(tmp_db):
    def responder(model, messages):
        return '{"action": "buy"}' if model == "primary-x" else '{"action": "sell"}'

    app, _, _ = _make_app(responder, tmp_db)
    async with app.router.lifespan_context(app):
        async with await _client(app) as http:
            resp = await http.post(
                "/debug/chat", json={"messages": [{"role": "u", "content": "x"}]}
            )
            assert resp.status_code == 200
            d = resp.json()
            assert d["primary"]["model"] == "primary-x"
            assert d["candidate"]["model"] == "candidate-y"
            assert d["primary"]["action"] == "buy"
            assert d["candidate"]["action"] == "sell"
            assert d["action_match"] is False


async def test_debug_chat_isolates_candidate_error(tmp_db):
    def responder(model, messages):
        if model == "candidate-y":
            raise RuntimeError("candidate down")
        return '{"action": "buy"}'

    app, _, _ = _make_app(responder, tmp_db)
    async with app.router.lifespan_context(app):
        async with await _client(app) as http:
            d = (await http.post("/debug/chat", json={"messages": [{"role": "u", "content": "x"}]})).json()
            assert d["primary"]["response"] == '{"action": "buy"}'
            assert d["candidate"]["error"] is not None
            assert d["action_match"] is False


async def test_index_serves_chat_ui(tmp_db):
    app, _, _ = _make_app(lambda m, msg: '{"action": "buy"}', tmp_db)
    async with app.router.lifespan_context(app):
        async with await _client(app) as http:
            resp = await http.get("/")
            assert resp.status_code == 200
            assert "Shadow-Mode LLM Evaluator" in resp.text
