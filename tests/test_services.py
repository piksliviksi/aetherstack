from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
HUB = REPO / "aether-hub"
sys.path.insert(0, str(HUB))

import services  # noqa: E402


EXPECTED_SERVICES = {
    "research",
    "planning",
    "service-design",
    "ui-design",
    "frontend",
    "backend",
    "coding",
    "testing",
    "bugfixing",
    "whitehat-pentesting",
    "polishing",
    "technical-writing",
}


def snapshot() -> dict:
    common = {"available": True, "availability_reason": "test", "latency": "low"}
    return {
        "models": {
            "local-code": {
                **common,
                "provider": "ollama",
                "tier": "local",
                "cost": 0,
                "capabilities": ["chat", "code", "tools", "cheap", "fast", "private"],
            },
            "reason-pro": {
                **common,
                "provider": "openai",
                "tier": "cloud",
                "cost": "high",
                "capabilities": ["chat", "code", "reason", "tools", "long_context"],
            },
            "vision-pro": {
                **common,
                "provider": "google",
                "tier": "cloud",
                "cost": "medium",
                "capabilities": ["chat", "code", "reason", "vision", "long_context"],
            },
            "budget-chat": {
                **common,
                "provider": "mistral",
                "tier": "cloud",
                "cost": "low",
                "capabilities": ["chat", "code", "tools", "cheap", "fast"],
            },
            "offline-model": {
                "available": False,
                "availability_reason": "missing key",
                "provider": "anthropic",
                "tier": "cloud",
                "cost": "high",
                "capabilities": ["chat", "code", "reason", "tools", "long_context"],
            },
        }
    }


class DynamicServiceTests(unittest.TestCase):
    def test_catalog_has_requested_services_without_model_or_provider_pins(self) -> None:
        catalog = services.load_service_catalog()
        self.assertEqual(set(catalog["services"]), EXPECTED_SERVICES)
        for service in catalog["services"].values():
            blueprints = [service["lead"], service["reviewer"], *(service.get("workstreams") or [])]
            for blueprint in blueprints:
                self.assertNotIn("model", blueprint)
                self.assertNotIn("provider", blueprint)
                self.assertNotIn("maker", blueprint)

    def test_resolution_uses_only_currently_available_models(self) -> None:
        resolved = services.resolve_service("coding", snapshot())
        self.assertTrue(resolved["ready"])
        self.assertGreaterEqual(len(resolved["agents"]), 4)
        self.assertNotIn("offline-model", resolved["models"])
        self.assertTrue(all(agent.get("available") for agent in resolved["agents"]))

    def test_health_failure_reroutes_to_another_capable_model(self) -> None:
        initial = services.resolve_service("research", snapshot())
        failed = initial["agents"][0]["model"]
        resolved = services.resolve_verified_service(
            "research", snapshot(), verifier=lambda alias: alias != failed
        )
        self.assertIn(failed, resolved["failed_models"])
        self.assertNotEqual(resolved["agents"][0].get("model"), failed)

    def test_service_plan_carries_lean_and_safety_policy(self) -> None:
        plan = services.plan_service(
            "whitehat-pentesting",
            snapshot(),
            {"goal": "Review an authorized local API", "verify": False, "lean_mode": "strict"},
        )
        self.assertEqual(plan["lean_mode"], "strict")
        self.assertGreaterEqual(len(plan["litellm_calls"]), 4)
        system_text = "\n".join(
            call["messages"][0]["content"] for call in plan["litellm_calls"]
        )
        self.assertIn("explicit authorization", system_text)
        self.assertIn("Never remove validation", system_text)

    def test_combined_chat_executes_lead_workers_review_and_synthesis(self) -> None:
        calls: list[tuple[str, str]] = []

        def completion(call: dict, messages: list[dict] | None = None) -> dict:
            calls.append((call.get("role", "lead"), call["model"]))
            return {
                "model": call["model"],
                "content": f"response-{len(calls)}",
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            }

        result = services.execute_service(
            "planning",
            snapshot(),
            {"goal": "Plan a verified release", "verify": False, "token_saver": True},
            completion=completion,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["answer"], f"response-{len(calls)}")
        self.assertGreaterEqual(len(calls), 5)
        self.assertEqual(result["usage"]["total_tokens"], len(calls) * 5)


if __name__ == "__main__":
    unittest.main()
