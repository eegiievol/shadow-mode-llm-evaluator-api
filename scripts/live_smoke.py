"""Live end-to-end smoke test against the real DigitalOcean Inference API.

Drives the actual FastAPI app in-process (real DOInferenceClient reading the
key from .env) via an in-memory ASGI transport: a single POST /v1/chat, then a
burst, then reads /metrics. No persistent server needed.
"""

import asyncio
import json

import httpx
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app


async def main() -> None:
    settings = Settings()
    print(f"Primary  : {settings.primary_model}")
    print(f"Candidate: {settings.candidate_model}")
    print(f"Base URL : {settings.do_inference_base_url}\n")

    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://live", timeout=60) as http:
            prompt = {
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "You are a trading assistant. Reply with ONLY a JSON "
                            'object of the form {"action": "buy"} or '
                            '{"action": "sell"} or {"action": "hold"}. '
                            "Market is rallying hard. No prose."
                        ),
                    }
                ]
            }

            print("=== 1. Single POST /v1/chat (live primary) ===")
            r = await http.post("/v1/chat", json=prompt)
            print("status:", r.status_code)
            print("body  :", json.dumps(r.json(), indent=2)[:400], "\n")

            print("=== 2. Burst of 12 requests (mirrored to candidate) ===")
            results = await asyncio.gather(
                *[http.post("/v1/chat", json=prompt) for _ in range(12)],
                return_exceptions=True,
            )
            ok = sum(1 for x in results if not isinstance(x, Exception) and x.status_code == 200)
            print(f"primary responses OK: {ok}/12\n")

            print("=== 3. Draining shadow pool... ===")
            await asyncio.sleep(8)

            print("=== 4. GET /metrics (live) ===")
            m = await http.get("/metrics")
            print(json.dumps(m.json(), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
