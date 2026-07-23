# Requirements Compliance Matrix

Maps every requirement from the assessment brief (*Q3: Shadow-Mode LLM Evaluator
API Service*) to where it is implemented and how it was verified.

Legend: ✅ met · ➕ extension (bonus) met

## Functional Expectations

| # | Requirement | Status | Where | Verified by |
|---|-------------|--------|-------|-------------|
| F1 | **Synchronous Primary Proxy** — `POST /v1/chat` routes to the Primary LLM via the DO Serverless Inference API and returns the response to the user immediately | ✅ | [`app/main.py`](../app/main.py) `chat()`; [`app/llm_client.py`](../app/llm_client.py) `DOInferenceClient.chat()` | `test_chat_returns_primary_immediately`; live against `llama3.3-70b-instruct` |
| F2 | **Asynchronous Shadow Execution** — same request routed to the Candidate in the background; its latency/errors/failure never delay or impact the primary response | ✅ | [`app/main.py`](../app/main.py) non-blocking `executor.submit()`; [`app/shadow.py`](../app/shadow.py) | `test_candidate_failure_does_not_affect_primary`; `test_candidate_error_isolated`; `test_timeout_counted` |
| F3 | **Deterministic Evaluation** — (1) both return valid, parseable JSON? (2) extract `action` from both and assert exact match | ✅ | [`app/evaluator.py`](../app/evaluator.py) `evaluate()` | `tests/test_evaluator.py` (8 cases: match, differ, invalid JSON, missing action, non-object, null, structured action) |
| F4 | **Observability API** — `GET /metrics` returns total requests processed, shadow errors/timeouts, and the exact-match-rate % | ✅ | [`app/main.py`](../app/main.py) `metrics_endpoint()`; [`app/metrics.py`](../app/metrics.py) `snapshot()` | `tests/test_metrics.py`; `test_metrics_reflect_match` / `_mismatch` |

## Engineering Expectations

| # | Requirement | Status | Where | Verified by |
|---|-------------|--------|-------|-------------|
| E1 | **Architecture Flow Diagram** — API layer, synchronous immediate-return path, decoupled background shadow pool | ✅ | [`docs/architecture.md`](architecture.md) (mermaid) | Renders on GitHub; all three elements labelled |
| E2 | **Bounded Concurrency (Load Shedding)** — background tasks tightly managed; under bursts the shadow queue sheds load / drops evaluations to bound memory | ✅ | [`app/shadow.py`](../app/shadow.py) fixed `asyncio.Queue(maxsize=…)` + fixed worker pool; `put_nowait` → `QueueFull` → drop + `shadow.shed++` | `test_load_shedding_when_queue_full` |
| E3 | **Testing** — unit and integration tests covering all scenarios | ✅ | [`tests/`](../tests) — 28 tests | `pytest` (28 passed) |
| E4 | **CI/CD** — GitHub Actions pipeline running the test suite on push | ✅ | [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) (Python 3.11 + 3.12) | GitHub Actions runs #1–#4 green |
| E5 | **Documentation** — README with setup, step-by-step curl usage to mutate metrics, and a "how this service bounds memory footprint under load" section | ✅ | [`README.md`](../README.md) | Sections: *Setup*, *Curl walkthrough: mutating the metrics*, *How this service bounds memory footprint under load* |

## Extensions & Next Steps (bonus)

| # | Requirement | Status | Where | Verified by |
|---|-------------|--------|-------|-------------|
| X1 | **Persistent Traces** — asynchronously stream mismatched payloads (Primary != Candidate) to a local SQLite file | ➕ ✅ | [`app/storage.py`](../app/storage.py) `TraceStore` (writes via `asyncio.to_thread`) | `test_mismatch_persisted_to_sqlite`; `test_exact_match_not_persisted`; live rows on the Droplet |
| X2 | **Dynamic Configuration** — `PUT /config` for runtime updates to the shadow routing percentage (throttle 100% → 50% etc.) | ➕ ✅ | [`app/main.py`](../app/main.py) `update_config()`; [`app/config.py`](../app/config.py) `RuntimeConfig` | `test_put_config_updates_percentage`; `test_config_percentage_zero_skips_shadow` |

## Design decisions worth noting for review

- **Shadow fires after the primary returns, not simultaneously.** The brief's
  hard constraint is that the candidate *"must never delay or impact the primary
  response."* We satisfy this by awaiting only the primary on the request path,
  then handing the request to the background pool via a non-blocking `submit()`.
  Candidate work runs concurrently across requests, fully decoupled from the
  user-facing path. Firing the candidate strictly in parallel with the primary
  would add no user-visible benefit and would shadow requests whose primary
  failed (nothing to compare against).
- **`action` match semantics.** A match requires both payloads to be valid JSON
  objects *and* both to expose a non-null, exactly-equal `action`. Two `null`
  actions or a valid-but-actionless payload count as **not** a match — the
  evaluator is asserting agreement on a real decision, not absence of one.
- **Metrics are lock-free.** All counters are mutated only from the single
  asyncio event loop (request handlers + shadow workers), so integer increments
  are atomic between `await` points — no locking overhead.
- **Model availability is tier-gated.** On the test account only a subset of the
  listed models are authorized for chat completions (`llama3.3-70b-instruct`,
  `deepseek-3.2`, `llama-4-maverick`, `gemma-4-31B-it`, `mistral-3-14B`);
  OpenAI/Anthropic models return `403 "not available for your subscription
  tier"`. The default pair (`llama3.3-70b-instruct` primary + `deepseek-3.2`
  candidate) is a verified-working cross-family combination.

## How to reproduce verification

```bash
pip install -r requirements.txt
pytest                       # 28 unit + integration tests
python -m scripts.live_smoke # live end-to-end against DO (needs a key in .env)
python -m scripts.compare    # see both models answer side by side
```
