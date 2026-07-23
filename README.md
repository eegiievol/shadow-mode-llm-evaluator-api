# Shadow-Mode LLM Evaluator API Service

An API service for evaluating LLM outputs in **shadow mode** — running evaluations
against live or candidate models alongside production traffic, without affecting the
user-facing response.

## What it does

- Accepts requests to evaluate LLM responses (quality, safety, regression checks).
- Runs evaluators asynchronously in "shadow" so results never block production.
- Records scores and comparisons for offline analysis.

## Status

🚧 Early scaffolding. See issues / TODO below.

## Getting started

_TBD — stack not yet chosen._

## TODO

- [ ] Choose runtime/framework
- [ ] Define evaluation request/response schema
- [ ] Add shadow-mode dispatch pipeline
- [ ] Persistence for eval results
- [ ] Deployment (DigitalOcean App Platform / Droplet)
