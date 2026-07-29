#!/usr/bin/env python3
"""Live, cross-platform AetherStack smoke test using only the Python standard library."""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICES = (
    "research", "planning", "service-design", "ui-design", "frontend", "backend",
    "coding", "testing", "bugfixing", "whitehat-pentesting", "polishing", "technical-writing",
)


def env_file_value(name: str) -> str | None:
    path = ROOT / ".env"
    if not path.exists():
        return None
    value = None
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        if raw.lstrip().startswith("#") or "=" not in raw:
            continue
        key, candidate = raw.split("=", 1)
        if key.strip() == name:
            value = candidate.strip().strip("\"'")
    return value


def json_request(url: str, method: str = "GET", body: dict | None = None, headers: dict | None = None, timeout: int = 30) -> tuple[int, dict, dict]:
    payload = None if body is None else json.dumps(body).encode()
    request_headers = dict(headers or {})
    if payload is not None:
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=payload, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return response.status, json.loads(raw or b"{}"), dict(response.headers)
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            parsed = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            parsed = {"error": raw.decode(errors="replace")[:500]}
        return error.code, parsed, dict(error.headers)


def plain_request(url: str, timeout: int = 15) -> tuple[int, bytes, dict]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.status, response.read(), dict(response.headers)


def service_stream(url: str, body: dict, timeout: int = 300) -> tuple[int, dict | None]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    deltas = 0
    done = None
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw in response:
            line = raw.decode(errors="replace").strip()
            if not line.startswith("data:"):
                continue
            event = json.loads(line[5:].strip())
            if event.get("type") == "delta" and event.get("text"):
                deltas += 1
            elif event.get("type") == "done":
                done = event.get("result")
            elif event.get("type") == "error":
                raise RuntimeError(event.get("error") or "service stream failed")
    return deltas, done


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all-services", action="store_true", help="Run one real prompt through every service preset")
    parser.add_argument("--skip-inference", action="store_true", help="Check control-plane APIs without generating or embedding")
    parser.add_argument("--hub", default="http://127.0.0.1:8766")
    parser.add_argument("--gateway", default="http://127.0.0.1:4000")
    parser.add_argument("--webui", default="http://127.0.0.1:3000")
    parser.add_argument("--ollama-url")
    args = parser.parse_args()

    configured_ollama = args.ollama_url or os.getenv("OLLAMA_BASE_URL") or env_file_value("OLLAMA_BASE_URL") or "http://127.0.0.1:11434"
    ollama = configured_ollama.replace("host.docker.internal", "127.0.0.1").replace("gateway.docker.internal", "127.0.0.1").rstrip("/")
    api_key = os.getenv("LITELLM_MASTER_KEY") or env_file_value("LITELLM_MASTER_KEY") or "sk-aether-local"
    auth = {"Authorization": f"Bearer {api_key}"}
    results: dict[str, object] = {"ok": False, "ollama": ollama, "checks": []}

    def passed(name: str, detail: object = "ok") -> None:
        results["checks"].append({"name": name, "ok": True, "detail": detail})

    status, webui_body, webui_headers = plain_request(f"{args.webui}/")
    check(status == 200 and webui_body, "Open WebUI proxy did not return a page")
    normalized_headers = {key.lower(): value for key, value in webui_headers.items()}
    check("no-store" in normalized_headers.get("cache-control", "").lower(), "Open WebUI response is missing no-store cache protection")
    passed("open-webui", "HTTP 200, no-store")

    status, live, _ = json_request(f"{args.gateway}/health/liveliness")
    check(status == 200, f"LiteLLM liveliness failed: {live}")
    passed("litellm-liveliness")

    status, health, _ = json_request(f"{args.hub}/api/health")
    check(status == 200 and health.get("ok"), f"AetherHub health failed: {health}")
    passed("hub-health", health.get("discover"))

    status, catalog, _ = json_request(f"{args.hub}/api/services")
    ids = [service.get("id") for service in catalog.get("services", [])]
    check(all(service in ids for service in SERVICES), f"service catalog is incomplete: {ids}")
    check(all(service.get("ready") or service.get("degraded") for service in catalog["services"]), "one or more service presets have no runnable agent")
    passed("service-catalog", {"count": len(ids), "providers": catalog.get("available_providers")})

    status, matrix, _ = json_request(f"{args.hub}/api/matrix")
    available = sorted(alias for alias, meta in matrix.get("models", {}).items() if meta.get("available"))
    check("local-default" in available and "local-embed" in available, f"required local aliases are unavailable: {available}")
    passed("capability-matrix", available)

    status, activity, _ = json_request(f"{args.hub}/api/activity-words")
    check(len(activity.get("words", [])) >= 3, "activity-word database is empty")
    passed("activity-words", len(activity["words"]))

    for endpoint, name in (("/api/graphs/node-types", "graph-node-types"), ("/api/combos/guide", "combo-guide"), ("/api/bootstrap", "bootstrap-plan")):
        status, payload, _ = json_request(f"{args.hub}{endpoint}")
        check(status == 200 and payload, f"{name} failed: {payload}")
        passed(name)

    status, selection, _ = json_request(f"{args.hub}/api/services/classify", "POST", {"goal": "Fix a reproducible HTTP 500 and add a regression test"})
    check(status == 200 and selection.get("service_id") in SERVICES, f"intent classification failed: {selection}")
    passed("intent-classification", selection.get("service_id"))

    status, plan, _ = json_request(f"{args.hub}/api/services/coding/plan", "POST", {"goal": "Write a typed add function", "verify": False, "agent_budget": "minimal"})
    check(status == 200 and plan.get("litellm_calls"), f"coding plan failed: {plan}")
    passed("dynamic-plan", [call.get("model") for call in plan["litellm_calls"]])

    status, tags, _ = json_request(f"{ollama}/api/tags")
    check(status == 200 and tags.get("models"), f"Ollama has no models: {tags}")
    passed("ollama-models", [model.get("name") for model in tags["models"]])

    with socket.create_connection(("127.0.0.1", 6379), timeout=3) as redis_socket:
        redis_socket.sendall(b"*1\r\n$4\r\nPING\r\n")
        check(b"PONG" in redis_socket.recv(64), "Redis did not answer PING")
    passed("redis")

    if not args.skip_inference:
        completion_body = {"model": "local-default", "messages": [{"role": "user", "content": "Reply with exactly AETHER_SMOKE_OK"}], "max_tokens": 24, "temperature": 0}
        status, completion, _ = json_request(f"{args.gateway}/v1/chat/completions", "POST", completion_body, auth, 180)
        text = (((completion.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        check(status == 200 and text, f"LiteLLM completion failed: {completion}")
        passed("litellm-inference", {"model": completion.get("model"), "text": text[:80]})

        status, embedding, _ = json_request(f"{args.gateway}/v1/embeddings", "POST", {"model": "local-embed", "input": "AetherStack smoke test"}, auth, 180)
        vector = (((embedding.get("data") or [{}])[0]).get("embedding") or [])
        check(status == 200 and len(vector) > 100, f"embedding failed: {embedding}")
        passed("embedding", {"dimensions": len(vector)})

        status, hub_completion, _ = json_request(f"{args.hub}/v1/chat/completions", "POST", completion_body, auth, 180)
        hub_text = ((((hub_completion.get("choices") or [{}])[0]).get("message") or {}).get("content") or "").strip()
        check(status == 200 and hub_text, f"Hub OpenAI facade failed: {hub_completion}")
        passed("hub-openai-facade", hub_text[:80])

        deltas, streamed = service_stream(
            f"{args.hub}/api/services/planning/run/stream",
            {"goal": "Return one short action for validating a local API.", "verify": False, "token_saver": True, "agent_budget": "minimal"},
        )
        check(deltas > 0 and streamed and streamed.get("ok") and streamed.get("answer"), f"service SSE stream failed: {streamed}")
        passed("service-sse", {"deltas": deltas, "service": streamed.get("service_id")})

        status, ps, _ = json_request(f"{ollama}/api/ps")
        loaded = ps.get("models") or []
        check(status == 200 and loaded, "Ollama has no loaded model after inference")
        passed("ollama-loaded-model", [{"name": item.get("name"), "vram": item.get("size_vram")} for item in loaded])

        if args.all_services:
            service_results = []
            for service in SERVICES:
                started = time.monotonic()
                status, run, _ = json_request(
                    f"{args.hub}/api/services/{service}/run", "POST",
                    {"goal": f"For a smoke test, return one short actionable sentence about {service}.", "verify": False, "token_saver": True, "agent_budget": "minimal"},
                    timeout=300,
                )
                check(status == 200 and run.get("ok") and run.get("answer"), f"service {service} failed: {run}")
                service_results.append({"service": service, "seconds": round(time.monotonic() - started, 1)})
            passed("all-service-inference", service_results)

    results["ok"] = True
    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}, indent=2), file=sys.stderr)
        raise SystemExit(1)
