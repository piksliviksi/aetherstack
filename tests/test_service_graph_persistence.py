from __future__ import annotations

import copy
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import yaml


REPO = Path(__file__).resolve().parents[1]
HUB = REPO / "aether-hub"
sys.path.insert(0, str(HUB))

import graph as graph_module  # noqa: E402
import matrix  # noqa: E402
import server  # noqa: E402
import services  # noqa: E402


def snapshot() -> dict:
    return {
        "models": {
            "cloud-model": {
                "available": True,
                "provider": "api",
                "tier": "cloud",
                "cost": "medium",
                "latency": "low",
                "capabilities": ["chat", "code", "reason", "tools", "long_context"],
            },
            "local-model": {
                "available": True,
                "provider": "ollama",
                "tier": "local",
                "cost": 0,
                "latency": "low",
                "capabilities": ["chat", "code", "reason", "tools", "long_context"],
            },
        }
    }


def catalog_text() -> str:
    return """version: 1
defaults:
  mode: multi_agent
  lean_mode: balanced
services:
  one:
    label: One
    lead:
      needs: [chat]
      strategy: best_score
    reviewer:
      needs: [chat]
    workstreams: []
  two:
    label: Two
    lead:
      needs: [chat]
      strategy: best_score
    reviewer:
      needs: [chat]
    workstreams: []
"""


def resolved_service(service_id: str, *, chain: list[str] | None = None, tier: str = "cloud", max_cost=None) -> dict:
    fallback = [
        {"model": alias, "tier": snapshot()["models"].get(alias, {}).get("tier")}
        for alias in (chain or ["cloud-model"])
    ]
    lead = {
        "id": "lead",
        "role": "mastermind",
        "label": "Lead",
        "available": True,
        "model": "cloud-model",
        "tier": tier,
        "strategy": "best_score",
        "max_cost": max_cost,
        "needs": ["chat"],
        "fallback_chain": fallback,
        "chain_authored": chain is not None,
    }
    return {"id": service_id, "label": service_id.title(), "agents": [lead]}


def lead_node(graph: dict) -> dict:
    return next(node for node in graph["nodes"] if node["id"].endswith("-lead"))


class ServiceGraphPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.catalog = Path(self.temp.name) / "service_catalog.yaml"
        self.catalog.write_text(catalog_text(), encoding="utf-8")
        self.catalog_patch = mock.patch.object(services, "CATALOG_PATH", self.catalog)
        self.catalog_patch.start()

    def tearDown(self) -> None:
        self.catalog_patch.stop()
        self.temp.cleanup()

    def load(self) -> dict:
        return yaml.safe_load(self.catalog.read_text(encoding="utf-8"))

    def test_unrelated_save_does_not_persist_resolved_tier(self) -> None:
        graph = graph_module.service_to_graph(resolved_service("one"))
        services.save_service_graph("one", graph)
        self.assertNotIn("tier", self.load()["services"]["one"]["lead"])

    def test_every_role_override_can_be_set_then_cleared(self) -> None:
        graph = graph_module.service_to_graph(resolved_service("one"))
        data = lead_node(graph)["data"]
        data.update({"tier": "local", "strategy": "cheapest", "max_cost": "low", "needs": ["code"]})
        data["edited_fields"] = ["tier", "strategy", "max_cost", "needs"]
        services.save_service_graph("one", graph)
        stored = self.load()["services"]["one"]["lead"]
        self.assertEqual(stored["tier"], "local")
        self.assertEqual(stored["strategy"], "cheapest")
        self.assertEqual(stored["max_cost"], "low")
        self.assertEqual(stored["needs"], ["code"])

        reloaded = graph_module.service_to_graph(
            resolved_service("one", tier="local", max_cost="low")
        )
        reloaded_data = lead_node(reloaded)["data"]
        # Match the authored values that a real resolve/reload would display.
        reloaded_data["strategy"] = "cheapest"
        reloaded_data["needs"] = ["code"]
        reloaded_data["_service_original"] = copy.deepcopy(reloaded_data["_service_original"])
        reloaded_data["_service_original"].update(
            {"tier": "local", "strategy": "cheapest", "max_cost": "low", "needs": ["code"]}
        )
        reloaded_data.update({"tier": None, "strategy": None, "max_cost": None, "needs": []})
        reloaded_data["edited_fields"] = ["tier", "strategy", "max_cost", "needs"]
        services.save_service_graph("one", reloaded)
        cleared = self.load()["services"]["one"]["lead"]
        for key in ("tier", "strategy", "max_cost", "needs"):
            self.assertNotIn(key, cleared)

    def test_exact_model_choice_clears_authored_route_chain_and_can_be_unpinned(self) -> None:
        graph = graph_module.service_to_graph(
            resolved_service("one", chain=["cloud-model", "local-model"])
        )
        data = lead_node(graph)["data"]
        data["model"] = "local-model"
        data["model_explicit"] = True
        data["edited_fields"] = ["model"]
        services.save_service_graph("one", graph)
        stored = self.load()["services"]["one"]["lead"]
        self.assertEqual(stored["pin_model"], "local-model")
        self.assertEqual(stored["fallback_chain"], [])
        self.assertNotIn("tier", stored, "model-derived tier must remain display metadata")

        reloaded = graph_module.service_to_graph(resolved_service("one", tier="local"))
        reloaded_data = lead_node(reloaded)["data"]
        reloaded_data["model"] = None
        reloaded_data["edited_fields"] = ["model"]
        services.save_service_graph("one", reloaded)
        self.assertNotIn("pin_model", self.load()["services"]["one"]["lead"])

    def test_parallel_service_saves_retain_both_updates(self) -> None:
        first = graph_module.service_to_graph(resolved_service("one"))
        second = graph_module.service_to_graph(resolved_service("two"))
        first_memory = next(node for node in first["nodes"] if node["type"] == "memory")
        second_memory = next(node for node in second["nodes"] if node["type"] == "memory")
        first_memory["data"]["action"] = "store"
        second_memory["data"].update({"scope": "project", "project_id": "shared"})
        barrier = threading.Barrier(2)
        errors: list[Exception] = []

        def save(service_id: str, value: dict) -> None:
            try:
                barrier.wait(timeout=2)
                services.save_service_graph(service_id, value)
            except Exception as exc:  # pragma: no cover - assertion reports detail
                errors.append(exc)

        threads = [
            threading.Thread(target=save, args=("one", first)),
            threading.Thread(target=save, args=("two", second)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertFalse(errors)
        saved = self.load()["services"]
        self.assertEqual(saved["one"]["memory"]["action"], "store")
        self.assertEqual(saved["two"]["memory"]["scope"], "project")
        self.assertEqual(saved["two"]["memory"]["project_id"], "shared")
        self.assertEqual(list(self.catalog.parent.glob(".service_catalog.yaml.*.tmp")), [])

    def test_subscription_aliases_score_live_cli_and_fall_back_to_local(self) -> None:
        local = snapshot()["models"]["local-model"]
        cli = {
            "available": True,
            "executor": "host_cli",
            "tier": "host_cli",
            "cost": "account",
            "latency": "low",
            "capabilities": ["chat", "code"],
        }
        self.assertTrue(matrix.tiers_match(cli, "subscription"))
        self.assertTrue(matrix.tiers_match("subscription", "host_cli"))
        self.assertGreater(
            matrix._score_model(cli, {"chat", "code"}, "subscription"),
            matrix._score_model(local, {"chat", "code"}, "subscription"),
        )
        cli["available"] = False
        self.assertLess(matrix._score_model(cli, {"chat"}, "subscription"), 0)
        self.assertGreater(matrix._score_model(local, {"chat"}, "subscription"), 0)

    def test_chain_normalization_skips_malformed_and_duplicate_entries(self) -> None:
        normalized = services._normalize_chain(
            [None, [], "cloud-model", {"model": "cloud-model"}, {"bad": "value"}, "local-model"],
            snapshot()["models"],
        )
        self.assertEqual([item["model"] for item in normalized], ["cloud-model", "local-model"])

    def test_disconnected_routes_are_rejected(self) -> None:
        value = graph_module.service_to_graph(
            resolved_service("one", chain=["cloud-model", "local-model"])
        )
        first_route = next(node["id"] for node in value["nodes"] if node["type"] == "route")
        value["edges"] = [edge for edge in value["edges"] if edge["to"] != first_route]
        with self.assertRaisesRegex(ValueError, "disconnected"):
            graph_module.graph_to_service_patch(value)

    def test_stage_bus_fans_out_without_blocking(self) -> None:
        first = server._stage_subscribe()
        second = server._stage_subscribe()
        try:
            event = {"type": "status", "phase": "answering_done", "service_id": "one"}
            server._stage_publish(event)
            self.assertEqual(first.get_nowait(), event)
            self.assertEqual(second.get_nowait(), event)
            for index in range(250):
                server._stage_publish({"index": index})
        finally:
            server._stage_unsubscribe(first)
            server._stage_unsubscribe(second)

    def test_service_graph_http_routes_return_expected_statuses(self) -> None:
        sent: list[tuple[int, dict]] = []
        get_request = SimpleNamespace(
            path="/api/services/one/graph",
            _send=lambda code, value, *args: sent.append((code, value)),
        )
        with mock.patch.object(server, "get_snapshot", return_value=snapshot()), mock.patch.object(
            server, "build_service_graph", return_value={"id": "one", "nodes": [], "edges": []}
        ):
            server.Handler.do_GET(get_request)
        self.assertEqual(sent[-1], (200, {"id": "one", "nodes": [], "edges": []}))

        invalid: list[tuple[int, dict]] = []
        post_request = SimpleNamespace(
            path="/api/services/one/graph",
            _origin_allowed=lambda: True,
            _workspace_write_authorized=lambda: True,
            _read_json=lambda: {"nodes": "invalid"},
            _send=lambda code, value, *args: invalid.append((code, value)),
        )
        with mock.patch.object(server, "save_service_graph", side_effect=ValueError("nodes must be a list")):
            server.Handler.do_POST(post_request)
        self.assertEqual(invalid[-1][0], 400)
        self.assertIn("nodes must be a list", invalid[-1][1]["error"])

        unknown: list[tuple[int, dict]] = []
        unknown_request = SimpleNamespace(
            path="/api/services/missing/graph",
            _send=lambda code, value, *args: unknown.append((code, value)),
        )
        with mock.patch.object(server, "get_snapshot", return_value=snapshot()), mock.patch.object(
            server, "build_service_graph", side_effect=ValueError("unknown service: missing")
        ):
            server.Handler.do_GET(unknown_request)
        self.assertEqual(unknown[-1][0], 404)


if __name__ == "__main__":
    unittest.main()
