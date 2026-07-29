from __future__ import annotations

import sys
import json
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
HUB = REPO / "aether-hub"
sys.path.insert(0, str(HUB))

import services  # noqa: E402
import activity_words  # noqa: E402
import matrix  # noqa: E402
import openai_gateway  # noqa: E402
from agents import get_runtime  # noqa: E402


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
    def test_authenticated_host_cli_models_join_the_live_capability_matrix(self) -> None:
        base = matrix.annotate_availability(
            {"version": 1, "models": {}, "capabilities": {}, "routing": {}},
            ollama={"ok": False, "models": []},
        )
        merged = matrix.merge_host_cli_models(
            base,
            {
                "ok": True,
                "models": [
                    {
                        "alias": "codex-cli",
                        "provider": "codex-cli",
                        "backend": "host-cli/codex",
                        "capabilities": ["chat", "code", "reason", "tools"],
                        "available": True,
                    },
                    {"alias": "untrusted-cli", "capabilities": ["chat"], "available": True},
                ],
            },
        )
        self.assertTrue(merged["models"]["codex-cli"]["available"])
        self.assertEqual(merged["models"]["codex-cli"]["executor"], "host_cli")
        self.assertNotIn("untrusted-cli", merged["models"])
        self.assertIn("codex-cli", merged["capability_index"]["code"]["any_available"])

    def test_operator_can_disable_an_unhealthy_host_cli_alias(self) -> None:
        base = matrix.annotate_availability(
            {"version": 1, "models": {}, "capabilities": {}, "routing": {}},
            ollama={"ok": False, "models": []},
        )
        bridge = {
            "ok": True,
            "models": [
                {"alias": "codex-cli", "capabilities": ["chat"]},
                {"alias": "grok-cli", "capabilities": ["chat"]},
            ],
        }
        with mock.patch.dict(os.environ, {"AETHER_DISABLED_MODELS": "grok-cli"}):
            merged = matrix.merge_host_cli_models(base, bridge)
        self.assertIn("codex-cli", merged["models"])
        self.assertNotIn("grok-cli", merged["models"])
        self.assertEqual(merged["host_cli"]["disabled_models"], ["grok-cli"])

    def test_catalog_has_requested_services_without_model_or_provider_pins(self) -> None:
        catalog = services.load_service_catalog()
        self.assertEqual(set(catalog["services"]), EXPECTED_SERVICES)
        for service in catalog["services"].values():
            blueprints = [service["lead"], service["reviewer"], *(service.get("workstreams") or [])]
            for blueprint in blueprints:
                self.assertNotIn("model", blueprint)
                self.assertNotIn("provider", blueprint)
                self.assertNotIn("maker", blueprint)
            self.assertTrue(service.get("activities"))
            self.assertTrue(service.get("match"))

    def test_service_catalog_reports_host_cli_bridge_state(self) -> None:
        snap = snapshot()
        snap["host_cli"] = {"ok": False, "models": [], "reason": "bridge token not configured"}
        catalog = services.list_services(snap)
        self.assertEqual(catalog["host_cli"]["reason"], "bridge token not configured")

    def test_auto_selection_follows_catalog_task_language(self) -> None:
        cases = {
            "Research current primary sources and fact-check the evidence": "research",
            "Plan milestones and dependencies for this delivery": "planning",
            "Design an accessible UI flow and design system": "ui-design",
            "Research and design the UI for a local service": "ui-design",
            "Reproduce this crash, isolate the root cause, and fix the bug": "bugfixing",
            "Fix a reproducible HTTP 500 and add a regression test": "bugfixing",
        }
        for goal, expected in cases.items():
            with self.subTest(goal=goal):
                result = services.classify_service(goal, snapshot())
                self.assertEqual(result["service_id"], expected)
                self.assertIn(result["confidence"], {"high", "medium"})

    def test_resolution_uses_only_currently_available_models(self) -> None:
        resolved = services.resolve_service("coding", snapshot())
        self.assertTrue(resolved["ready"])
        self.assertGreaterEqual(len(resolved["agents"]), 4)
        self.assertNotIn("offline-model", resolved["models"])
        self.assertTrue(all(agent.get("available") for agent in resolved["agents"]))

    def test_research_service_builds_small_assurance_graph(self) -> None:
        graph = services.build_service_graph("research", snapshot())
        self.assertEqual(graph["service_id"], "research")
        labels = [node.get("data", {}).get("label") for node in graph["nodes"]]
        self.assertIn("Research lead", labels)
        self.assertIn("Evidence critic", labels)
        self.assertIn("Final synthesis", labels)
        workers = [node for node in graph["nodes"] if node["type"] == "worker"]
        self.assertEqual(len(workers), 1)
        lead = next(node for node in graph["nodes"] if node["id"].endswith("-lead"))
        reviewer = next(node for node in graph["nodes"] if node["id"].endswith("-review"))
        outgoing = [edge for edge in graph["edges"] if edge["from"] == lead["id"]]
        incoming = [edge for edge in graph["edges"] if edge["to"] == reviewer["id"]]
        self.assertEqual(len(outgoing), len(workers))
        self.assertEqual(len(incoming), len(workers))
        self.assertEqual(set(graph["resolved_models"]), set(graph["resolved_models"]) & set(snapshot()["models"]))

    def test_agent_budget_starts_small_and_expands_only_when_needed(self) -> None:
        simple = services.plan_service(
            "coding", snapshot(), {"goal": "Rename this label", "verify": False}
        )
        self.assertEqual(simple["service"]["agent_count"], 2)
        self.assertFalse(simple["service"]["agent_policy"]["assurance_gate"])

        complex_plan = services.plan_service(
            "coding",
            snapshot(),
            {"goal": "Compare multiple architecture approaches in parallel", "verify": False},
        )
        self.assertEqual(complex_plan["service"]["agent_count"], 3)
        self.assertTrue(complex_plan["service"]["agent_policy"]["parallel_worker"])

        full = services.plan_service(
            "coding", snapshot(), {"goal": "Implement", "verify": False, "agent_budget": "full"}
        )
        self.assertGreater(full["service"]["agent_count"], simple["service"]["agent_count"])

    def test_health_failure_reroutes_to_another_capable_model(self) -> None:
        initial = services.resolve_service("research", snapshot())
        failed = initial["agents"][0]["model"]
        resolved = services.resolve_verified_service(
            "research", snapshot(), verifier=lambda alias: alias != failed
        )
        self.assertIn(failed, resolved["failed_models"])
        self.assertNotEqual(resolved["agents"][0].get("model"), failed)

    def test_host_cli_completion_uses_authenticated_bridge_not_litellm(self) -> None:
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({
                    "model": "codex-cli",
                    "choices": [{"message": {"content": "bridge answer"}}],
                    "usage": {},
                }).encode()

        with mock.patch.object(services, "CLI_BRIDGE_TOKEN", "test-bridge-token"), mock.patch.object(
            services.urllib.request, "urlopen", return_value=Response()
        ) as urlopen:
            result = services._chat_completion(
                {"model": "codex-cli"}, [{"role": "user", "content": "hello"}]
            )
        request = urlopen.call_args.args[0]
        self.assertTrue(request.full_url.startswith(services.CLI_BRIDGE_URL))
        self.assertNotIn(services.LITELLM_BASE_URL, request.full_url)
        self.assertEqual(result["content"], "bridge answer")

    def test_service_plan_carries_lean_and_safety_policy(self) -> None:
        plan = services.plan_service(
            "whitehat-pentesting",
            snapshot(),
            {"goal": "Review an authorized local API", "verify": False, "lean_mode": "strict"},
        )
        self.assertEqual(plan["lean_mode"], "strict")
        self.assertGreaterEqual(len(plan["litellm_calls"]), 3)
        system_text = "\n".join(
            call["messages"][0]["content"] for call in plan["litellm_calls"]
        )
        self.assertIn("explicit authorization", system_text)
        self.assertIn("Never remove validation", system_text)

    def test_minimal_service_plan_does_not_reintroduce_removed_reviewer(self) -> None:
        plan = services.plan_service(
            "coding",
            snapshot(),
            {"goal": "Write a clamp helper", "verify": False, "agent_budget": "minimal"},
        )
        roles = {call["role"] for call in plan["litellm_calls"]}
        self.assertNotIn("supervisor", roles)
        self.assertNotIn("supervisor", {agent["role"] for agent in plan["agents"]})
        self.assertFalse(
            any(
                str(edge.get(key) or "").endswith("-supervisor")
                for edge in plan["edges"]
                for key in ("from", "to")
            )
        )

    def test_minimal_local_service_deduplicates_same_backend_worker(self) -> None:
        snap = snapshot()
        snap["models"] = {
            "local-a": {
                "available": True,
                "provider": "ollama",
                "backend": "ollama/llama3.1:8b",
                "tier": "local",
                "cost": 0,
                "capabilities": ["chat", "code", "reason", "tools", "long_context", "cheap"],
            },
            "local-b": {
                "available": True,
                "provider": "ollama",
                "backend": "ollama/llama3.1:8b",
                "tier": "local",
                "cost": 0,
                "capabilities": ["chat", "code", "reason", "tools", "long_context", "cheap"],
            },
        }
        plan = services.plan_service(
            "coding",
            snap,
            {"goal": "Write a clamp helper", "verify": False, "agent_budget": "minimal"},
        )
        self.assertEqual([call["role"] for call in plan["litellm_calls"]], ["mastermind"])

    def test_short_minimal_token_saver_plan_prefers_a_full_fit_local_model(self) -> None:
        snap = snapshot()
        snap["models"]["local-code"]["capabilities"].append("reason")
        plan = services.plan_service(
            "planning",
            snap,
            {
                "goal": "Return one short API validation action",
                "verify": False,
                "token_saver": True,
                "agent_budget": "minimal",
            },
        )
        self.assertTrue(plan["litellm_calls"])
        self.assertTrue(all(call["model"] == "local-code" for call in plan["litellm_calls"]))

    def test_combined_chat_executes_lead_workers_review_and_synthesis(self) -> None:
        calls: list[tuple[str, str, list[dict] | None]] = []

        def completion(call: dict, messages: list[dict] | None = None) -> dict:
            calls.append((call.get("role", "lead"), call["model"], messages))
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
        self.assertGreaterEqual(len(calls), 4)
        self.assertEqual(result["usage"]["total_tokens"], len(calls) * 5)
        self.assertEqual(result["activation"]["service"], "planning")
        self.assertEqual(get_runtime()["service"], "planning")
        self.assertIn("interactive coding and project copilot", calls[-1][2][0]["content"])
        self.assertIn("Return only the final user-facing answer", calls[-1][2][0]["content"])
        self.assertIn("never mention a lead", calls[-1][2][0]["content"])
        self.assertIn("no undeclared names", calls[-1][2][0]["content"])

    def test_activity_word_database_is_locally_editable(self) -> None:
        old_path = activity_words.DB_PATH
        with tempfile.TemporaryDirectory() as td:
            try:
                activity_words.DB_PATH = Path(td) / "activity_words.json"
                activity_words.DB_PATH.write_text(
                    json.dumps({"schema": "test", "words": []}), encoding="utf-8"
                )
                item = activity_words.add_word(
                    {"text": "Mõtteid mudimas...", "language": "et", "tone": "playful"}
                )
                self.assertEqual(activity_words.list_words()["words"][0]["text"], "Mõtteid mudimas...")
                self.assertTrue(activity_words.delete_word(item["id"])["ok"])
                self.assertEqual(activity_words.list_words()["words"], [])
            finally:
                activity_words.DB_PATH = old_path


class OpenAIGatewayTests(unittest.TestCase):
    def test_models_only_expose_available_chat_aliases_with_capabilities(self) -> None:
        value = openai_gateway.model_list(snapshot())
        ids = {item["id"] for item in value["data"]}
        self.assertIn("local-code", ids)
        self.assertNotIn("offline-model", ids)
        local = next(item for item in value["data"] if item["id"] == "local-code")
        self.assertTrue(local["aetherstack"]["supports_tools"])

    def test_unsupported_tool_fields_are_removed_before_backend_call(self) -> None:
        snap = snapshot()
        snap["models"]["plain-chat"] = {
            "available": True,
            "provider": "ollama",
            "tier": "local",
            "capabilities": ["chat"],
        }
        captured = {}

        def proxy(payload: dict) -> dict:
            captured.update(payload)
            return {"id": "one", "model": payload["model"], "choices": [{"message": {"content": "ok"}}]}

        value, wanted_stream = openai_gateway.chat_completion(
            {
                "model": "plain-chat",
                "messages": [{"role": "user", "content": "hello"}],
                "tools": [{"type": "function", "function": {"name": "lookup"}}],
                "tool_choice": "auto",
                "stream": True,
                "stream_options": {"include_usage": True},
            },
            snap,
            proxy=proxy,
        )
        self.assertTrue(wanted_stream)
        self.assertNotIn("tools", captured)
        self.assertNotIn("tool_choice", captured)
        self.assertNotIn("stream_options", captured)
        self.assertIn("does not support tool calls", captured["messages"][0]["content"])
        self.assertEqual(value["choices"][0]["message"]["content"], "ok")

    def test_host_cli_completion_uses_bridge_and_can_be_encoded_as_sse(self) -> None:
        snap = snapshot()
        snap["models"]["codex-cli"] = {
            "available": True,
            "provider": "codex-cli",
            "executor": "host_cli",
            "capabilities": ["chat", "code", "tools"],
        }
        value, wanted_stream = openai_gateway.chat_completion(
            {"model": "codex-cli", "messages": [{"role": "user", "content": "hello"}], "stream": True},
            snap,
            cli_completion=lambda payload: {"model": payload["model"], "content": "bridge answer", "usage": {}},
        )
        self.assertTrue(wanted_stream)
        stream = openai_gateway.stream_bytes(value).decode("utf-8")
        self.assertIn("bridge answer", stream)
        self.assertTrue(stream.endswith("data: [DONE]\n\n"))

    def test_each_service_has_editable_markdown_loaded_into_graph_nodes(self) -> None:
        for service_id in EXPECTED_SERVICES:
            resolved = services.resolve_service(service_id, snapshot())
            self.assertTrue(resolved["behavior_markdown"], service_id)
            self.assertEqual(resolved["behavior_source"], f"{service_id}.md")
            graph = services.build_service_graph(service_id, snapshot())
            agents = [node for node in graph["nodes"] if node["type"] in {"master", "worker", "analyser"}]
            self.assertTrue(agents)
            self.assertTrue(all(node["data"]["instructions_md"] for node in agents))


if __name__ == "__main__":
    unittest.main()
