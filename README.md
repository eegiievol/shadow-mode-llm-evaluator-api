# Shadow-Mode LLM Evaluator API Service

A production-style API proxy that serves customer traffic from a **Primary LLM**
while asynchronously mirroring the exact same traffic to a **Candidate LLM** in
the background. It compares the two outputs with a deterministic heuristic and
exposes real-time metrics on how the candidate performs versus the primary.

Built on FastAPI + the DigitalOcean Serverless Inference API (OpenAI-compatible).

## Contents

- [How it works](#how-it-works)
- [Endpoints](#endpoints)
- [Setup](#setup)
- [Running the service](#running-the-service)
- [Curl walkthrough: mutating the metrics](#curl-walkthrough-mutating-the-metrics)
- [How this service bounds memory footprint under load](#how-this-service-bounds-memory-footprint-under-load)
- [Testing](#testing)
- [CI/CD](#cicd)
- [Configuration reference](#configuration-reference)
- [Architecture](#architecture)

## How it works

1. `POST /v1/chat` routes the request to the **Primary** model and returns its
   response to the caller **immediately**.
2. The same request is handed off (non-blocking) to a **bounded background
   pool**, which calls the **Candidate** model.
3. A **deterministic evaluator** checks: (a) did both models return valid,
   parseable JSON? (b) do the extracted `action` values match exactly?
4. `GET /metrics` reports totals, shadow errors/timeouts, and the exact-match
   rate.

The candidate's latency, errors, or failures **never** delay or affect the
user-facing primary response — the two paths only communicate through a bounded
queue.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/chat` | Proxy to the Primary LLM, return immediately, mirror to Candidate in the background. |
| `GET`  | `/metrics` | Real-time counters + exact-match-rate %. |
| `PUT`  | `/config` | Update the shadow routing percentage at runtime (0–100). |
| `GET`  | `/healthz` | Liveness probe. |

## Setup

Requires Python 3.11+.

```bash
git clone git@github.com:eegiievol/shadow-mode-llm-evaluator-api.git
cd shadow-mode-llm-evaluator-api

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env and set DO_INFERENCE_API_KEY (create one in the DigitalOcean
# console: Agent Platform -> Serverless Inference -> Model access keys).
```

## Running the service

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Interactive API docs are then available at `http://localhost:8000/docs`.

> **Note:** every endpoint except `POST /v1/chat` works without an API key. The
> chat endpoint needs a valid `DO_INFERENCE_API_KEY` to reach the live models.

## Curl walkthrough: mutating the metrics

Start the server, then in another terminal:

**1. Baseline — all counters zero:**

```bash
curl -s localhost:8000/metrics | jq
```

**2. Send chat traffic (mirrored to the candidate in the background):**

```bash
curl -s -X POST localhost:8000/v1/chat \
  -H 'content-type: application/json' \
  -d '{"messages":[{"role":"user","content":"Reply ONLY with JSON like {\"action\":\"buy\"}"}]}' | jq
```

**3. Watch the metrics move** — `total_requests`, `shadow.completed`, and the
`exact_match_rate_pct` update as the shadow pool drains:

```bash
curl -s localhost:8000/metrics | jq
```

**4. Throttle shadow mirroring to 50% at runtime:**

```bash
curl -s -X PUT localhost:8000/config \
  -H 'content-type: application/json' \
  -d '{"shadow_percentage": 50}' | jq
```

After this, roughly half of subsequent requests increment `shadow.skipped`
instead of being evaluated. Set it to `0` to pause shadowing entirely, or `100`
to mirror everything.

**5. Demonstrate load shedding** — fire a burst larger than the queue can hold
and watch `shadow.shed` climb:

```bash
for i in $(seq 1 500); do
  curl -s -X POST localhost:8000/v1/chat \
    -H 'content-type: application/json' \
    -d '{"messages":[{"role":"user","content":"go"}]}' >/dev/null &
done; wait
curl -s localhost:8000/metrics | jq '.shadow'
```

## How this service bounds memory footprint under load

Background evaluation is deliberately capped by **two fixed-size structures**:

- **A bounded `asyncio.Queue`** (`SHADOW_QUEUE_SIZE`) — the maximum number of
  pending evaluations that can be buffered.
- **A fixed worker pool** (`SHADOW_WORKERS`) — the maximum number of candidate
  calls in flight at any moment.

The synchronous request path only ever calls `ShadowExecutor.submit()`, which is
**non-blocking**. When traffic bursts faster than the workers can drain the
queue, `put_nowait` raises `QueueFull` and the service **sheds load** — the
evaluation is dropped and the `shadow.shed` counter is incremented, rather than
letting an unbounded backlog accumulate.

As a result, background memory is **`O(SHADOW_QUEUE_SIZE + SHADOW_WORKERS)`**
irrespective of request volume. A traffic spike degrades *shadow coverage*
(some evaluations are skipped) but never the primary application's footprint or
latency. This is the load-shedding trade-off: we prefer dropping observability
data over risking memory exhaustion of the primary service.

Optionally, `PUT /config` lets you proactively throttle the mirror percentage
(e.g. from 100% to 50%) to reduce candidate cost/pressure without a redeploy.

## Testing

```bash
python -m pytest
```

The suite (25 tests) uses a network-free fake LLM client and covers:

- **Evaluator** — matching/mismatching actions, invalid JSON, missing `action`,
  non-object payloads, structured actions, null inputs.
- **Metrics** — snapshot shape and match-rate math.
- **Shadow pool** — load shedding when the queue is full, percentage sampling,
  candidate timeouts, error isolation, and mismatch persistence to SQLite.
- **API (integration)** — immediate primary return, metrics reflecting
  match/mismatch, `502` on primary failure, candidate failure *not* affecting
  the user, `PUT /config`, and health.

## CI/CD

`.github/workflows/ci.yml` runs the full `pytest` suite on every push and pull
request, across Python 3.11 and 3.12.

## Configuration reference

All settings are read from the environment (or a `.env` file). See
[`.env.example`](.env.example).

| Variable | Default | Description |
|----------|---------|-------------|
| `DO_INFERENCE_BASE_URL` | `https://inference.do-ai.run/v1` | Inference API base URL. |
| `DO_INFERENCE_API_KEY` | _(empty)_ | Serverless Inference model access key. |
| `PRIMARY_MODEL` | `llama3.3-70b-instruct` | Model that serves users. |
| `CANDIDATE_MODEL` | `deepseek-3.2` | Model evaluated in shadow. |
| `PRIMARY_TIMEOUT` | `30` | Primary call timeout (s). |
| `CANDIDATE_TIMEOUT` | `10` | Candidate call timeout (s). |
| `SHADOW_QUEUE_SIZE` | `100` | Bounded queue depth (memory cap). |
| `SHADOW_WORKERS` | `4` | Background worker concurrency. |
| `SHADOW_PERCENTAGE` | `100` | % of traffic mirrored (runtime-adjustable). |
| `SQLITE_PATH` | `traces.db` | SQLite file for mismatch traces. |

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for the full flow diagram
and a description of the synchronous return path vs. the decoupled shadow pool.

For a point-by-point mapping of every assessment requirement to its
implementation and test, see
[`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md).

### Extensions implemented

- **Persistent traces** — mismatched payloads (where Primary != Candidate) are
  streamed asynchronously to a local SQLite file (`SQLITE_PATH`) for debugging.
- **Dynamic configuration** — `PUT /config` updates the shadow routing
  percentage at runtime.
