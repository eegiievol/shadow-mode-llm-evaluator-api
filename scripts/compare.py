"""Ask the SAME question to both the primary and candidate models and print
their answers side by side, with a match indicator.

This is a debugging/demo helper — it calls the Inference API directly (not the
shadow proxy) so you can *see* both answers, which the shadow service
deliberately hides from users.

Usage:
    python -m scripts.compare "your question"
    python -m scripts.compare            # runs a built-in demo set
"""

import json
import sys
import time
import urllib.request
import urllib.error


def load_env():
    cfg = {"base": "https://inference.do-ai.run/v1"}
    for line in open(".env"):
        line = line.strip()
        if line.startswith("DO_INFERENCE_API_KEY="):
            cfg["key"] = line.split("=", 1)[1]
        elif line.startswith("DO_INFERENCE_BASE_URL="):
            cfg["base"] = line.split("=", 1)[1]
        elif line.startswith("PRIMARY_MODEL="):
            cfg["primary"] = line.split("=", 1)[1]
        elif line.startswith("CANDIDATE_MODEL="):
            cfg["candidate"] = line.split("=", 1)[1]
    return cfg


def ask(cfg, model, question):
    body = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": question}]}
    ).encode()
    req = urllib.request.Request(
        cfg["base"].rstrip("/") + "/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {cfg['key']}", "Content-Type": "application/json"},
    )
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.load(r)
        content = d["choices"][0]["message"]["content"]
        return (content or "").strip(), (time.time() - t) * 1000
    except urllib.error.HTTPError as e:
        return f"[ERROR {e.code}] {e.read().decode()[:80]}", (time.time() - t) * 1000


def run(cfg, question):
    print("=" * 72)
    print("Q:", question)
    print("-" * 72)
    p_ans, p_ms = ask(cfg, cfg["primary"], question)
    c_ans, c_ms = ask(cfg, cfg["candidate"], question)
    match = "MATCH ✅" if p_ans == c_ans else "DIFFER ❌"
    print(f"PRIMARY   [{cfg['primary']}]  ({p_ms:.0f} ms)\n  {p_ans}\n")
    print(f"CANDIDATE [{cfg['candidate']}]  ({c_ms:.0f} ms)\n  {c_ans}\n")
    print(f"=> {match}")
    print()


DEMO = [
    # Factual / deterministic -> models usually AGREE
    "What is the capital of Japan? Answer with just the city name.",
    # Open-ended / subjective -> models usually DIFFER
    "In 3 words, describe the color blue.",
    # Structured decision under ambiguity -> often DIFFER
    'A stock is flat with mixed signals. Reply ONLY JSON {"action":"buy"} '
    'or {"action":"sell"} or {"action":"hold"}.',
]


def main():
    cfg = load_env()
    print(f"Primary  : {cfg['primary']}")
    print(f"Candidate: {cfg['candidate']}\n")
    questions = sys.argv[1:] or DEMO
    for q in questions:
        run(cfg, q)


if __name__ == "__main__":
    main()
