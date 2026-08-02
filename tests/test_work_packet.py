"""Unit tests for structured Work Packet handoffs."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HUB = Path(__file__).resolve().parents[1] / "aether-hub"
sys.path.insert(0, str(HUB))

import work_packet as wp  # noqa: E402
import services  # noqa: E402


class WorkPacketTests(unittest.TestCase):
    def test_parse_fenced_json_and_partitions(self) -> None:
        text = """
Plan: split the work.

```json
{
  "goal_digest": "fix auth",
  "partitions": [
    {"worker_id": "implementer", "scope": "auth routes", "must_do": ["patch login"], "must_not": ["touch UI"], "acceptance": ["test login"]},
    {"worker_id": "tester", "scope": "tests", "must_do": ["add regression"], "must_not": ["rewrite app"], "acceptance": ["pytest green"]}
  ],
  "claims": [
    {"id": "C1", "owner": "lead", "claim": "login lacks rate limit", "status": "open", "evidence": [], "risk": "high"}
  ],
  "open_questions": ["Is redis available?"],
  "covered_paths": [],
  "delta_for_next": "workers own implementation vs tests"
}
```
"""
        packet = wp.parse_work_packet(text, goal="fix auth")
        self.assertEqual(packet["goal_digest"], "fix auth")
        self.assertEqual(len(packet["partitions"]), 2)
        self.assertEqual(packet["claims"][0]["id"], "C1")

    def test_ensure_partitions_fills_from_workers(self) -> None:
        packet = wp.empty_packet("goal")
        workers = [{"task_id": "ws-a", "messages": [{"role": "user", "content": "Source scout\n\nContext"}]},
                   {"task_id": "ws-b", "messages": [{"role": "user", "content": "Analyst\n\nContext"}]}]
        filled = wp.ensure_partitions(packet, workers, goal="goal")
        self.assertEqual([p["worker_id"] for p in filled["partitions"]], ["ws-a", "ws-b"])

    def test_coverage_gaps_and_force_open(self) -> None:
        packet = {
            "partitions": [{"worker_id": "a", "scope": "x", "must_do": [], "must_not": [], "acceptance": []}],
            "claims": [],
        }
        gaps = wp.coverage_gaps(packet)
        self.assertTrue(gaps)
        forced = wp.force_open_claims_for_gaps(packet, gaps)
        self.assertEqual(forced["claims"][0]["status"], "open")

    def test_merge_prefers_supported(self) -> None:
        a = wp.normalize_packet({"claims": [{"id": "C1", "claim": "x", "status": "open"}]})
        b = wp.normalize_packet({"claims": [{"id": "C1", "claim": "x fixed", "status": "supported", "evidence": [{"kind": "path", "ref": "a.py"}]}]})
        merged = wp.merge_packets(a, b)
        self.assertEqual(merged["claims"][0]["status"], "supported")

    def test_worker_prompt_is_partition_scoped(self) -> None:
        def completion(call: dict, messages: list[dict] | None = None) -> dict:
            blob = "\n".join(str(m.get("content") or "") for m in (messages or []))
            if call.get("role") == "worker":
                self.assertIn("Your partition only", blob)
                self.assertNotIn("Lead plan:\n", blob)
                return {
                    "model": call["model"],
                    "content": (
                        '```json\n{"claims":[{"id":"C9","owner":"worker","claim":"Observed result in services.py: handoffs use partitions.",'
                        '"status":"supported","evidence":[{"kind":"path","ref":"aether-hub/services.py"}],"risk":"medium"}],'
                        '"covered_paths":["aether-hub/services.py"]}\n```'
                    ),
                    "usage": {},
                }
            if call.get("role") == "supervisor":
                return {
                    "model": call["model"],
                    "content": "Claim C9 is supported. No uncovered partitions.",
                    "usage": {},
                }
            # lead / final
            if "Work Packet claims" in blob or "Cite claim ids" in blob:
                return {
                    "model": call["model"],
                    "content": "Found [C9]: partition handoffs land in services.py execute_service. Verified via unit test.",
                    "usage": {},
                }
            return {
                "model": call["model"],
                "content": (
                    'Short plan.\n```json\n{"goal_digest":"partition test","partitions":[],'
                    '"claims":[{"id":"C0","owner":"lead","claim":"need worker check","status":"open","evidence":[],"risk":"low"}],'
                    '"open_questions":[],"covered_paths":[],"delta_for_next":"workers verify"}\n```'
                ),
                "usage": {},
            }

        result = services.execute_service(
            "planning",
            {
                "models": {
                    "reason-pro": {"available": True, "availability_reason": "test", "latency": "low", "capabilities": ["reason", "chat", "tools", "code"], "tier": "cloud", "cost": 1},
                    "vision-pro": {"available": True, "availability_reason": "test", "latency": "low", "capabilities": ["reason", "chat", "tools", "code", "vision"], "tier": "cloud", "cost": 1},
                    "local-default": {"available": True, "availability_reason": "test", "latency": "low", "capabilities": ["chat", "code", "tools"], "tier": "local", "cost": 0},
                }
            },
            {"goal": "Check partition handoffs", "verify": False},
            completion=completion,
        )
        self.assertTrue(result.get("ok"))
        self.assertIn("work_packet", result)
        self.assertGreaterEqual(len(result["work_packet"].get("partitions") or []), 1)
        self.assertIn("[C9]", result.get("answer") or "")

    def test_honest_incomplete_when_final_stays_intent_only(self) -> None:
        def completion(call: dict, messages: list[dict] | None = None) -> dict:
            if call.get("role") == "worker":
                return {"model": call["model"], "content": "I will inspect and report back later without evidence.", "usage": {}}
            return {"model": call["model"], "content": "I will inspect the repository and report findings next.", "usage": {}}

        result = services.execute_service(
            "coding",
            {
                "models": {
                    "reason-pro": {"available": True, "availability_reason": "test", "latency": "low", "capabilities": ["reason", "chat", "tools", "code"], "tier": "cloud", "cost": 1},
                    "local-default": {"available": True, "availability_reason": "test", "latency": "low", "capabilities": ["chat", "code", "tools"], "tier": "local", "cost": 0},
                }
            },
            {"goal": "Implement a focused fix", "verify": False},
            completion=completion,
        )
        self.assertTrue(result.get("ok"))
        self.assertTrue(result.get("honest_incomplete") or result.get("degraded"))
        self.assertIn("Could not complete", result.get("answer") or "")


if __name__ == "__main__":
    unittest.main()
