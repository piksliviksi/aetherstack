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
    def test_service_catalog_rejects_unknown_schema(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "catalog.yaml"
            path.write_text("schema: future.v2\nservices: {}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsupported service catalog schema"):
                services.load_service_catalog(path)

    def test_authenticated_host_cli_models_join_the_live_capability_matrix(self) -> None:
        base = matrix.annotate_availability(
            {
                "version": 1,
                "models": {"local-existing": {"provider": "ollama", "tier": "local", "capabilities": ["chat"]}},
                "capabilities": {},
                "routing": {},
            },
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
        self.assertIn("local-existing", merged["models"])
        self.assertIn("codex-cli", merged["capability_index"]["code"]["any_available"])

    def test_unreachable_host_cli_bridge_degrades_with_a_reason(self) -> None:
        with mock.patch.object(matrix, "_http_json", return_value=None):
            result = matrix.probe_host_cli_bridge("http://bridge.invalid", "token")
        self.assertFalse(result["ok"])
        self.assertEqual(result["models"], [])
        self.assertEqual(result["reason"], "host bridge unreachable")

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

    def test_distinct_ollama_size_tags_are_not_treated_as_the_same_model(self) -> None:
        base = {
            "version": 1,
            "models": {
                "large": {"tier": "local", "backend": "ollama/qwen2.5-coder:1.5b", "capabilities": ["chat"]},
                "small": {"tier": "local", "backend": "ollama/qwen2.5-coder:0.5b", "capabilities": ["chat"]},
            },
            "capabilities": {},
            "routing": {},
        }
        annotated = matrix.annotate_availability(
            base, ollama={"ok": True, "models": ["qwen2.5-coder:1.5b"]}
        )
        self.assertTrue(annotated["models"]["large"]["available"])
        self.assertFalse(annotated["models"]["small"]["available"])

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
        self.assertEqual(catalog["default_service"], "auto")
        self.assertEqual(catalog["services"][0]["id"], "auto")

    def test_auto_graph_round_trips_model_order_and_sequence_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "auto_chain.json"
            with mock.patch.object(services, "AUTO_CHAIN_FILE", state):
                graph = services.build_auto_graph(snapshot())
                routes = [node for node in graph["nodes"] if node["type"] == "route"]
                self.assertTrue(routes)
                graph["sequence_mode"] = "per_request"
                result = services.save_auto_graph(graph)
                self.assertEqual(result["sequence_mode"], "per_request")
                self.assertEqual(services.get_auto_order(), result["order"])
                self.assertEqual(services.describe_auto_mode(snapshot())["order"], result["order"])

    def test_analysis_requests_enable_worker_and_critic_by_default(self) -> None:
        result = services.plan_service(
            "coding", snapshot(), {"goal": "Analyse this codebase and identify weak spots", "verify": False}
        )
        roles = {agent["role"] for agent in result["service"]["agents"]}
        self.assertIn("worker", roles)
        self.assertIn("supervisor", roles)

    def test_every_named_preset_uses_multiple_models_when_available(self) -> None:
        for service_id in EXPECTED_SERVICES:
            with self.subTest(service_id=service_id):
                plan = services.plan_service(
                    service_id,
                    snapshot(),
                    {"goal": f"Complete the {service_id} work", "verify": False},
                )
                models = {
                    agent["model"]
                    for agent in plan["service"]["agents"]
                    if agent.get("available") and agent.get("model")
                }
                self.assertGreaterEqual(len(models), 2)

    def test_intent_only_worker_output_is_rejected(self) -> None:
        self.assertTrue(services.worker_output_needs_correction("I will inspect the code and report back."))
        self.assertTrue(
            services.worker_output_needs_correction(
                "I'll inspect aether-hub/services.py and report the reliability finding from that file once the review is complete."
            )
        )
        self.assertFalse(
            services.worker_output_needs_correction(
                "Observed result: services.py execute_service omits a critic for generic analysis. "
                "The regression test should assert the supervisor role is selected."
            )
        )

    def test_worker_is_removed_after_two_intent_only_responses(self) -> None:
        def completion(call: dict, messages: list[dict] | None = None) -> dict:
            if call.get("role") == "worker":
                return {"model": call["model"], "content": "I will inspect this and report back.", "usage": {}}
            return {
                "model": call["model"],
                "content": "Observed result: tests completed with concrete repository evidence in tests/test_services.py.",
                "usage": {},
            }

        result = services.execute_service(
            "planning",
            snapshot(),
            {"goal": "Analyse release risks", "verify": False},
            completion=completion,
        )
        worker = next(step for step in result["steps"] if step.get("role") == "worker")
        # Rejected workers keep an explicit open-claim Work Packet so the gap is visible.
        self.assertIn("rejected", worker.get("error", ""))
        self.assertTrue(worker.get("content"))
        self.assertIn("FAIL-", worker.get("content", ""))
        self.assertTrue(result.get("degraded"))

    def test_sequential_auto_skips_a_session_model_after_its_limit(self) -> None:
        snap = snapshot()
        services._auto_session_model.clear()
        services._auto_session_exhausted.clear()
        calls: list[str] = []

        def completion(call: dict, messages: list[dict] | None = None) -> dict:
            calls.append(call["model"])
            if call["model"] == "reason-pro":
                raise RuntimeError("weekly usage limit reached")
            return {"model": call["model"], "content": "continued successfully", "usage": {}}

        with mock.patch.object(services, "get_auto_order", return_value=["reason-pro", "vision-pro"]):
            first = services.execute_auto(
                snap,
                {"goal": "continue", "sequence_mode": "sequential_exhaustion"},
                completion=completion,
                session_id="strict-sequence",
            )
            self.assertEqual(first["model"], "vision-pro")
            calls.clear()
            second = services.execute_auto(
                snap,
                {"goal": "continue again", "sequence_mode": "sequential_exhaustion"},
                completion=completion,
                session_id="strict-sequence",
            )
        self.assertEqual(second["model"], "vision-pro")
        self.assertEqual(calls[0], "vision-pro")
        self.assertNotIn("reason-pro", calls)

    def test_transient_auto_failure_does_not_exhaust_the_session_model(self) -> None:
        class TemporaryFailure(RuntimeError):
            code = 503

        snap = snapshot()
        services._auto_session_model.clear()
        services._auto_session_exhausted.clear()
        services._auto_session_model["temporary-session"] = "reason-pro"
        calls: list[str] = []

        def completion(call: dict, messages: list[dict] | None = None) -> dict:
            calls.append(call["model"])
            if len(calls) == 1:
                raise TemporaryFailure("service temporarily unavailable")
            return {"model": call["model"], "content": "temporary fallback succeeded", "usage": {}}

        with mock.patch.object(services, "get_auto_order", return_value=["reason-pro", "vision-pro"]):
            services.execute_auto(
                snap,
                {"goal": "continue", "sequence_mode": "sequential_exhaustion"},
                completion=completion,
                session_id="temporary-session",
            )
        self.assertNotIn("reason-pro", services._auto_session_exhausted.get("temporary-session", set()))

    def test_auto_replaces_intent_only_output_with_completed_work(self) -> None:
        responses = iter(
            [
                "I will inspect the repository and report back.",
                "Found a concrete issue in aether-hub/services.py and verified it with the focused fallback test.",
            ]
        )

        def completion(call: dict, messages: list[dict] | None = None) -> dict:
            return {"model": call["model"], "content": next(responses), "usage": {}}

        with mock.patch.object(services, "get_auto_order", return_value=["reason-pro"]):
            result = services.execute_auto(
                snapshot(),
                {"goal": "Audit the repository"},
                completion=completion,
            )
        self.assertTrue(result["answer"].startswith("Found a concrete issue"))

    def test_auto_fails_over_when_the_correction_is_still_only_a_plan(self) -> None:
        calls: list[str] = []

        def completion(call: dict, messages: list[dict] | None = None) -> dict:
            calls.append(call["model"])
            if call["model"] == "reason-pro":
                return {"model": call["model"], "content": "I'll inspect the repository next.", "usage": {}}
            return {"model": call["model"], "content": "Found a verified defect in aether-hub/services.py.", "usage": {}}

        with mock.patch.object(services, "get_auto_order", return_value=["reason-pro", "vision-pro"]):
            result = services.execute_auto(
                snapshot(),
                {"goal": "Audit the repository"},
                completion=completion,
            )
        self.assertEqual(calls, ["reason-pro", "reason-pro", "vision-pro"])
        self.assertEqual(result["model"], "vision-pro")

    def test_auto_session_state_is_bounded_and_evicts_atomically(self) -> None:
        with services._auto_session_lock, mock.patch.object(services, "_AUTO_SESSION_MAX", 16):
            services._auto_session_model.clear()
            services._auto_session_exhausted.clear()
            services._auto_session_lru.clear()
            for index in range(20):
                sid = f"bounded-{index}"
                services._auto_session_model[sid] = "reason-pro"
                services._auto_session_exhausted[sid] = {"old-model"}
                services._touch_auto_session(sid)
            self.assertEqual(len(services._auto_session_lru), 16)
            self.assertEqual(set(services._auto_session_model), set(services._auto_session_lru))
            self.assertEqual(set(services._auto_session_exhausted), set(services._auto_session_lru))
            self.assertNotIn("bounded-0", services._auto_session_model)

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

    def test_whitehat_lead_prefers_fast_cli_with_fallbacks(self) -> None:
        snap = snapshot()
        for alias in ("grok-cli", "claude-cli", "codex-cli"):
            snap["models"][alias] = {
                "available": True,
                "executor": "host_cli",
                "provider": alias,
                "tier": "host_cli",
                "cost": "account",
                "latency": "low",
                "capabilities": ["chat", "code", "reason", "tools", "long_context"],
            }
        plan = services.plan_service(
            "whitehat-pentesting",
            snap,
            {"goal": "Review an authorized local API", "verify": False},
        )
        lead = next(call for call in plan["litellm_calls"] if call["role"] == "mastermind")
        self.assertEqual(lead["model"], "codex-cli")

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
        phases: list[str] = []

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
            on_status=lambda event: phases.append(event["phase"]),
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
        self.assertIn("answering_done", phases)
        self.assertLess(phases.index("answering"), phases.index("answering_done"))
        self.assertIn("lead", result["timings_ms"])
        self.assertIn("workers", result["timings_ms"])
        self.assertIn("review", result["timings_ms"])
        self.assertIn("answering", result["timings_ms"])
        self.assertGreaterEqual(result["timings_ms"]["total"], 0)

    def test_failed_final_answer_emits_terminal_error_phase(self) -> None:
        phases: list[str] = []

        def completion(call: dict, messages: list[dict] | None = None) -> dict:
            if messages and "Return only the final user-facing answer" in messages[0].get("content", ""):
                raise RuntimeError("final failed")
            return {"model": call["model"], "content": "draft", "usage": {}}

        with self.assertRaisesRegex(RuntimeError, "final failed"):
            services.execute_service(
                "coding",
                snapshot(),
                {"goal": "Implement a helper", "verify": False},
                completion=completion,
                on_status=lambda event: phases.append(event["phase"]),
            )
        self.assertIn("answering_error", phases)

    def test_service_retries_one_transient_backend_failure(self) -> None:
        attempts = 0

        def completion(call: dict, messages: list[dict] | None = None) -> dict:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("503 service unavailable")
            return {"model": call["model"], "content": "recovered", "usage": {}}

        result = services.execute_service(
            "coding",
            snapshot(),
            {"goal": "Implement a helper", "verify": False, "agent_budget": "minimal"},
            completion=completion,
        )
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(attempts, 3)  # lead retry plus final synthesis

    def test_intent_only_final_synthesis_is_replaced_before_success(self) -> None:
        final_attempts = 0

        def completion(call: dict, messages: list[dict] | None = None) -> dict:
            nonlocal final_attempts
            is_final = bool(messages and "Return only the final user-facing answer" in messages[0].get("content", ""))
            if is_final:
                final_attempts += 1
                content = (
                    "I will inspect the code and report back."
                    if final_attempts == 1
                    else "Found and verified a concrete fallback defect in aether-hub/services.py with a passing regression test."
                )
            else:
                content = (
                    "Checked aether-hub/services.py and verified the execution path with concrete test evidence. "
                    "The observed result includes a reproducible assertion and a referenced symbol for review."
                )
            return {"model": call["model"], "content": content, "usage": {}}

        result = services.execute_service(
            "planning",
            snapshot(),
            {"goal": "Audit fallback", "verify": False},
            completion=completion,
        )
        self.assertEqual(final_attempts, 2)
        self.assertTrue(result["answer"].startswith("Found and verified"))

    def test_final_quality_rejects_future_work_and_internal_transcripts(self) -> None:
        self.assertTrue(services.final_output_needs_correction("To begin auditing, I'll map the backend."))
        self.assertTrue(
            services.final_output_needs_correction(
                "### Final User-Facing Answer\n\nI've begun reviewing the tests. Next, I'll run them."
            )
        )
        self.assertTrue(
            services.final_output_needs_correction(
                "Found one issue.\n\nInternal supporting material:\nworker draft"
            )
        )
        self.assertFalse(
            services.final_output_needs_correction(
                "Found and verified a fallback defect in aether-hub/services.py with a passing regression test."
            )
        )

    def test_partial_worker_and_review_failures_are_marked_degraded(self) -> None:
        def completion(call: dict, messages: list[dict] | None = None) -> dict:
            if call.get("role") == "worker":
                raise RuntimeError("worker fixture failed")
            if call.get("role") == "supervisor":
                raise RuntimeError("review fixture failed")
            return {"model": call["model"], "content": "usable answer", "usage": {}}

        result = services.execute_service(
            "planning",
            snapshot(),
            {"goal": "Plan a release", "verify": False},
            completion=completion,
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["degraded"])
        self.assertTrue(any("worker fixture failed" in reason for reason in result["degraded_reasons"]))
        self.assertTrue(any("review fixture failed" in reason for reason in result["degraded_reasons"]))

    def test_worker_session_limit_continues_on_its_resolved_fallback(self) -> None:
        attempts: list[tuple[str, str]] = []

        def completion(call: dict, messages: list[dict] | None = None) -> dict:
            attempts.append((call.get("role"), call["model"]))
            if call.get("role") == "worker" and call["model"] == "budget-chat":
                raise RuntimeError("session limit reached")
            return {
                "model": call["model"],
                "content": (
                    "Checked aether-hub/services.py::_complete_with_preset_failover and observed the fallback test pass. "
                    "The recorded model sequence contains budget-chat followed by vision-pro, providing concrete evidence "
                    "that the original task continued on the next resolved worker model."
                ),
                "usage": {},
            }

        result = services.execute_service(
            "planning",
            snapshot(),
            {"goal": "Plan a release", "verify": False},
            completion=completion,
        )

        worker = next(step for step in result["steps"] if step.get("role") == "worker")
        self.assertEqual(worker["model"], "vision-pro")
        self.assertEqual(worker["failover_from"], "budget-chat")
        self.assertEqual(worker["attempted_models"], ["budget-chat", "vision-pro"])
        self.assertIn(("worker", "budget-chat"), attempts)
        self.assertIn(("worker", "vision-pro"), attempts)
        self.assertFalse(result["degraded"])

    def test_lead_and_synthesis_limits_continue_on_resolved_fallbacks(self) -> None:
        services._preset_model_cooldown.clear()
        self.addCleanup(services._preset_model_cooldown.clear)
        def completion(call: dict, messages: list[dict] | None = None) -> dict:
            if call["model"] == "reason-pro":
                raise RuntimeError("session limit reached")
            return {
                "model": call["model"],
                "content": (
                    "Checked aether-hub/services.py and verified role-wide failover with concrete test evidence. "
                    "The lead and final synthesis both continued on the next resolved model after the primary limit."
                ),
                "usage": {},
            }

        result = services.execute_service(
            "planning",
            snapshot(),
            {"goal": "Plan a release", "verify": False},
            completion=completion,
        )

        lead = result["steps"][0]
        self.assertEqual(lead["failover_from"], "reason-pro")
        self.assertNotEqual(lead["model"], "reason-pro")
        roles = {item["role"] for item in result["failovers"]}
        self.assertIn("lead-plan", roles)
        self.assertIn("answering", roles)

    def test_recently_failing_preset_model_is_skipped_during_cooldown(self) -> None:
        services._preset_model_cooldown.clear()
        self.addCleanup(services._preset_model_cooldown.clear)
        call = {"model": "reason-pro", "fallback_chain": ["reason-pro", "budget-chat"]}
        attempts: list[str] = []

        def first_completion(current: dict, _messages: list[dict] | None = None) -> dict:
            attempts.append(current["model"])
            if current["model"] == "reason-pro":
                raise RuntimeError("timed out")
            return {"model": current["model"], "content": "recovered", "usage": {}}

        services._complete_with_preset_failover(first_completion, call, [])
        attempts.clear()
        result = services._complete_with_preset_failover(first_completion, call, [])
        self.assertEqual(attempts, ["budget-chat"])
        self.assertEqual(result["failover_from"], "reason-pro")
        self.assertIn("temporarily skipped", result["failover_errors"][0]["error"])

    def test_service_plan_carries_each_roles_resolved_fallback_chain(self) -> None:
        plan = services.plan_service("planning", snapshot(), {"goal": "Plan", "verify": False})
        calls = {call["role"]: call for call in plan["litellm_calls"]}
        self.assertEqual(calls["mastermind"]["fallback_chain"][0], calls["mastermind"]["model"])
        self.assertEqual(calls["worker"]["fallback_chain"][0], calls["worker"]["model"])
        self.assertIn("local-code", calls["worker"]["fallback_chain"])

    def test_service_workspace_write_requires_trusted_authorization(self) -> None:
        plan = services.plan_service("coding", snapshot(), {"goal": "edit", "verify": False})
        plan["litellm_calls"][0]["workspace_write"] = True
        with mock.patch.object(services, "plan_service", return_value=plan):
            with self.assertRaisesRegex(PermissionError, "trusted local authorization"):
                services.execute_service(
                    "coding",
                    snapshot(),
                    {"goal": "edit", "verify": False},
                    completion=lambda *_: {},
                )

    def test_handoff_context_carries_reasoning_across_a_model_switch(self) -> None:
        """A session-scoped, server-stored reasoning trace — not client-replayed chat
        history — is what lets a second, different model continue a first model's work."""
        os.environ["AETHER_HASH_EMBED"] = "1"
        from memory import MemoryStore

        mem = MemoryStore(url="redis://127.0.0.1:1/0")  # unreachable on purpose -> local fallback
        self.assertEqual(mem.backend, "memory-fallback")

        def solo_snapshot(model_id: str) -> dict:
            return {
                "models": {
                    model_id: {
                        "available": True,
                        "availability_reason": "test",
                        "provider": model_id,
                        "tier": "cloud",
                        "cost": "low",
                        "latency": "low",
                        "capabilities": ["chat", "code", "reason", "tools", "long_context"],
                    }
                }
            }

        def completion_factory(tag: str):
            def completion(call: dict, messages: list[dict] | None = None) -> dict:
                return {"model": call["model"], "content": f"{tag}-content", "usage": {}}
            return completion

        services.execute_service(
            "coding",
            solo_snapshot("model-a"),
            {"goal": "Remember the code WATERMELON42.", "verify": False},
            completion=completion_factory("model-a"),
            memory=mem,
            session_id="test-handoff-session",
        )

        captured: list[dict] = []

        def completion_b(call: dict, messages: list[dict] | None = None) -> dict:
            captured.append({"role": call.get("role", "lead"), "model": call["model"], "messages": messages})
            return {"model": call["model"], "content": "model-b-content", "usage": {}}

        services.execute_service(
            "coding",
            solo_snapshot("model-b"),
            {"goal": "What did you note down?", "verify": False},
            completion=completion_b,
            memory=mem,
            session_id="test-handoff-session",
        )

        lead_messages = captured[0]["messages"]
        handoff_texts = [m["content"] for m in lead_messages if "model-a-content" in m.get("content", "")]
        self.assertTrue(handoff_texts, "second model's prompt should carry the first model's reasoning")
        self.assertIn("previously worked by model-a", handoff_texts[0])
        self.assertIn("now continued by model-b", handoff_texts[0])

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
