"""Structured Work Packet handoffs between preset stages.

Workers receive a partition slice instead of re-reading the full lead essay.
Claims are merged so final synthesis can cite evidence without re-investigating.
"""
from __future__ import annotations

import json
import re
from typing import Any

CLAIM_STATUSES = frozenset({"supported", "inferred", "unsupported", "open"})
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
_PATH_HINT_RE = re.compile(
    r"(?:^|[\s`\"'(])((?:[\w.-]+/)+[\w.-]+\.(?:py|js|ts|tsx|jsx|md|yaml|yml|json|html|css|sh|go|rs|java|cpp|h))",
    re.IGNORECASE,
)


def empty_packet(goal: str = "") -> dict[str, Any]:
    digest = " ".join(str(goal or "").split())
    if len(digest) > 240:
        digest = digest[:237] + "..."
    return {
        "goal_digest": digest,
        "partitions": [],
        "claims": [],
        "open_questions": [],
        "covered_paths": [],
        "delta_for_next": "",
    }


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _normalize_claim(raw: Any, default_owner: str = "", index: int = 0) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    claim_text = str(raw.get("claim") or raw.get("text") or "").strip()
    if not claim_text:
        return None
    status = str(raw.get("status") or "open").strip().lower()
    if status not in CLAIM_STATUSES:
        status = "open"
    evidence: list[dict[str, str]] = []
    for item in _as_list(raw.get("evidence")):
        if isinstance(item, dict):
            ref = str(item.get("ref") or item.get("path") or item.get("url") or "").strip()
            if not ref and not item.get("note"):
                continue
            evidence.append(
                {
                    "kind": str(item.get("kind") or "quote")[:40],
                    "ref": ref[:500],
                    "note": str(item.get("note") or "")[:500],
                }
            )
        elif isinstance(item, str) and item.strip():
            evidence.append({"kind": "quote", "ref": item.strip()[:500], "note": ""})
    claim_id = str(raw.get("id") or f"C{index + 1}").strip() or f"C{index + 1}"
    return {
        "id": claim_id[:40],
        "owner": str(raw.get("owner") or default_owner or "unknown")[:80],
        "claim": claim_text[:2000],
        "status": status,
        "evidence": evidence[:12],
        "risk": str(raw.get("risk") or "medium").strip().lower()[:20] or "medium",
    }


def _normalize_partition(raw: Any, index: int = 0) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    worker_id = str(raw.get("worker_id") or raw.get("id") or f"worker-{index + 1}").strip()
    if not worker_id:
        return None
    must_do = [str(x).strip() for x in _as_list(raw.get("must_do")) if str(x).strip()]
    must_not = [str(x).strip() for x in _as_list(raw.get("must_not")) if str(x).strip()]
    acceptance = [str(x).strip() for x in _as_list(raw.get("acceptance")) if str(x).strip()]
    scope = str(raw.get("scope") or "").strip()
    if not scope and not must_do:
        scope = f"Partition for {worker_id}"
    return {
        "worker_id": worker_id[:80],
        "scope": scope[:1000],
        "must_do": must_do[:12],
        "must_not": must_not[:12]
        or ["Do not re-cover paths or tasks owned by other partitions."],
        "acceptance": acceptance[:12],
    }


def normalize_packet(raw: Any, goal: str = "") -> dict[str, Any]:
    base = empty_packet(goal)
    if not isinstance(raw, dict):
        return base
    if raw.get("goal_digest"):
        base["goal_digest"] = str(raw["goal_digest"])[:240]
    partitions = []
    for index, item in enumerate(_as_list(raw.get("partitions"))):
        part = _normalize_partition(item, index)
        if part:
            partitions.append(part)
    base["partitions"] = partitions
    claims = []
    for index, item in enumerate(_as_list(raw.get("claims"))):
        claim = _normalize_claim(item, index=index)
        if claim:
            claims.append(claim)
    base["claims"] = claims
    base["open_questions"] = [
        str(q).strip()[:500] for q in _as_list(raw.get("open_questions")) if str(q).strip()
    ][:20]
    paths: list[str] = []
    for path in _as_list(raw.get("covered_paths")):
        text = str(path).strip()
        if text and text not in paths:
            paths.append(text[:300])
    base["covered_paths"] = paths[:80]
    base["delta_for_next"] = str(raw.get("delta_for_next") or "")[:1000]
    return base


def extract_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    fence = _JSON_FENCE_RE.search(raw)
    candidates: list[str] = []
    if fence:
        candidates.append(fence.group(1))
    # Prefer outermost object if the model mixed prose + JSON.
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        candidates.append(raw[start : end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return data
    return None


def parse_work_packet(text: Any, goal: str = "", default_owner: str = "") -> dict[str, Any]:
    """Parse a model response into a Work Packet; never raises."""
    raw = extract_json_object(str(text or ""))
    if raw is None:
        packet = empty_packet(goal)
        prose = str(text or "").strip()
        if prose:
            owner = default_owner or "unknown"
            # Unique id per owner so parallel free-text workers do not collide on C1.
            packet["claims"] = [
                {
                    "id": f"C-{owner}-1"[:40],
                    "owner": owner,
                    "claim": prose[:2000],
                    "status": "inferred",
                    "evidence": [{"kind": "path", "ref": p, "note": ""} for p in extract_path_hints(prose)[:3]],
                    "risk": "medium",
                }
            ]
            packet["covered_paths"] = extract_path_hints(prose)
        return packet
    packet = normalize_packet(raw, goal=goal)
    if default_owner:
        for claim in packet["claims"]:
            if claim.get("owner") in {"", "unknown"}:
                claim["owner"] = default_owner
            # Avoid cross-owner id collisions when models omit ids.
            cid = str(claim.get("id") or "")
            if cid in {"C1", "C2", "C3"} or (cid.startswith("C") and cid[1:].isdigit()):
                claim["id"] = f"{cid}-{claim.get('owner')}"[:40]
    if not packet["covered_paths"]:
        packet["covered_paths"] = extract_path_hints(str(text or ""))
    return packet


def extract_path_hints(text: str) -> list[str]:
    found: list[str] = []
    for match in _PATH_HINT_RE.finditer(str(text or "")):
        path = match.group(1).strip("`'\"")
        if path and path not in found:
            found.append(path)
    return found[:40]


def partitions_from_workers(worker_calls: list[dict[str, Any]], goal: str = "") -> list[dict[str, Any]]:
    """Deterministic partitions when the lead omitted structured ownership."""
    partitions: list[dict[str, Any]] = []
    for index, call in enumerate(worker_calls or []):
        task_id = str(call.get("task_id") or f"worker-{index + 1}")
        label = ""
        for message in call.get("messages") or []:
            if message.get("role") == "user":
                label = str(message.get("content") or "").split("\n", 1)[0].strip()
                break
        label = label or task_id
        partitions.append(
            {
                "worker_id": task_id,
                "scope": f"Own the '{label}' workstream only.",
                "must_do": [
                    f"Complete only the '{label}' slice of the goal.",
                    "Return evidence-backed claims for this partition.",
                ],
                "must_not": [
                    "Do not re-do other workstreams.",
                    "Do not restate the full repository research.",
                ],
                "acceptance": [
                    "At least one supported or open claim with concrete evidence or an explicit gap.",
                ],
            }
        )
    if not partitions and goal:
        partitions.append(
            {
                "worker_id": "primary",
                "scope": "Primary investigation of the user goal.",
                "must_do": ["Address the user goal with evidence."],
                "must_not": ["Do not invent paths or symbols."],
                "acceptance": ["Supported claims or explicit open gaps."],
            }
        )
    return partitions


def ensure_partitions(packet: dict[str, Any], worker_calls: list[dict[str, Any]], goal: str = "") -> dict[str, Any]:
    packet = normalize_packet(packet, goal=goal)
    if len(packet["partitions"]) >= max(1, len(worker_calls or [])):
        # Align worker_ids when counts match but ids are generic.
        if worker_calls and len(packet["partitions"]) == len(worker_calls):
            for part, call in zip(packet["partitions"], worker_calls):
                task_id = str(call.get("task_id") or "").strip()
                if task_id:
                    part["worker_id"] = task_id
        return packet
    fallback = partitions_from_workers(worker_calls, goal=goal)
    # Keep any lead-authored partitions first, then fill remaining workers.
    existing_ids = {p["worker_id"] for p in packet["partitions"]}
    for part in fallback:
        if part["worker_id"] not in existing_ids:
            packet["partitions"].append(part)
            existing_ids.add(part["worker_id"])
    if not packet["partitions"]:
        packet["partitions"] = fallback
    return packet


def partition_for_worker(packet: dict[str, Any], task_id: str, index: int = 0) -> dict[str, Any]:
    partitions = list((packet or {}).get("partitions") or [])
    task_id = str(task_id or "")
    for part in partitions:
        if str(part.get("worker_id") or "") == task_id:
            return part
    if 0 <= index < len(partitions):
        return partitions[index]
    return {
        "worker_id": task_id or f"worker-{index + 1}",
        "scope": "Assigned workstream only.",
        "must_do": ["Complete your assigned slice with evidence."],
        "must_not": ["Do not redo other partitions."],
        "acceptance": ["Return claims for this partition only."],
    }


def merge_packets(*packets: dict[str, Any], goal: str = "") -> dict[str, Any]:
    merged = empty_packet(goal)
    claim_ids: set[str] = set()
    path_set: list[str] = []
    for packet in packets:
        if not isinstance(packet, dict):
            continue
        if packet.get("goal_digest") and not merged["goal_digest"]:
            merged["goal_digest"] = str(packet["goal_digest"])[:240]
        for part in packet.get("partitions") or []:
            if part not in merged["partitions"]:
                merged["partitions"].append(part)
        for claim in packet.get("claims") or []:
            cid = str(claim.get("id") or "")
            owner = str(claim.get("owner") or "unknown")
            # Key by id+owner so two workers both returning "C1" do not drop evidence.
            merge_key = f"{cid}::{owner}" if cid else ""
            if merge_key and merge_key in claim_ids:
                existing = next(
                    c
                    for c in merged["claims"]
                    if str(c.get("id") or "") == cid and str(c.get("owner") or "") == owner
                )
                rank = {"supported": 3, "inferred": 2, "open": 1, "unsupported": 0}
                if rank.get(claim.get("status"), 0) > rank.get(existing.get("status"), 0):
                    existing.update(claim)
                continue
            if not cid:
                claim = {**claim, "id": f"C{len(merged['claims']) + 1}-{owner}"[:40]}
                cid = claim["id"]
                merge_key = f"{cid}::{owner}"
            # If same id different owner, namespace the id to keep both.
            if cid in {str(c.get("id")) for c in merged["claims"]}:
                claim = {**claim, "id": f"{cid}-{owner}"[:40]}
                merge_key = f"{claim['id']}::{owner}"
            claim_ids.add(merge_key)
            merged["claims"].append(claim)
        for question in packet.get("open_questions") or []:
            if question not in merged["open_questions"]:
                merged["open_questions"].append(question)
        for path in packet.get("covered_paths") or []:
            if path not in path_set:
                path_set.append(path)
        if packet.get("delta_for_next"):
            merged["delta_for_next"] = str(packet["delta_for_next"])[:1000]
    merged["covered_paths"] = path_set[:80]
    return normalize_packet(merged, goal=goal)


def coverage_gaps(packet: dict[str, Any]) -> list[str]:
    """Return human-readable gaps: partitions with no claims."""
    packet = packet or {}
    claims = list(packet.get("claims") or [])
    gaps: list[str] = []
    for part in packet.get("partitions") or []:
        worker_id = str(part.get("worker_id") or "")
        owned = [c for c in claims if str(c.get("owner") or "") == worker_id]
        if not owned:
            gaps.append(f"partition uncovered: {worker_id}")
    return gaps


def force_open_claims_for_gaps(packet: dict[str, Any], gaps: list[str]) -> dict[str, Any]:
    packet = normalize_packet(packet)
    existing = {str(c.get("id")) for c in packet["claims"]}
    for gap in gaps:
        worker_id = gap.split(":", 1)[-1].strip() if ":" in gap else gap
        claim_id = f"GAP-{worker_id}"[:40]
        if claim_id in existing:
            continue
        packet["claims"].append(
            {
                "id": claim_id,
                "owner": worker_id,
                "claim": f"Partition '{worker_id}' produced no evidence-backed claims.",
                "status": "open",
                "evidence": [],
                "risk": "high",
            }
        )
        existing.add(claim_id)
    return packet


def worker_failure_claim(task_id: str, reason: str, goal: str = "") -> dict[str, Any]:
    packet = empty_packet(goal)
    packet["partitions"] = [
        {
            "worker_id": task_id,
            "scope": "Failed workstream",
            "must_do": [],
            "must_not": [],
            "acceptance": [],
        }
    ]
    packet["claims"] = [
        {
            "id": f"FAIL-{task_id}"[:40],
            "owner": task_id,
            "claim": f"Worker could not complete partition: {reason}",
            "status": "open",
            "evidence": [],
            "risk": "high",
        }
    ]
    packet["open_questions"] = [f"Re-run or reassign partition {task_id}."]
    return packet


def format_packet_compact(packet: dict[str, Any], max_chars: int = 6000) -> str:
    text = json.dumps(normalize_packet(packet), ensure_ascii=False, indent=2)
    if len(text) <= max_chars:
        return text
    slim = normalize_packet(packet)
    for claim in slim.get("claims") or []:
        claim["claim"] = str(claim.get("claim") or "")[:400]
        claim["evidence"] = (claim.get("evidence") or [])[:3]
    text = json.dumps(slim, ensure_ascii=False, indent=2)
    return text[: max_chars - 20] + "\n…(truncated)"


def claims_table(packet: dict[str, Any], max_chars: int = 8000) -> str:
    lines = ["Claim id | status | risk | owner | claim | evidence"]
    lines.append("--- | --- | --- | --- | --- | ---")
    for claim in (packet or {}).get("claims") or []:
        evidence = "; ".join(
            f"{e.get('kind')}:{e.get('ref') or e.get('note')}" for e in (claim.get("evidence") or [])[:3]
        )
        lines.append(
            f"{claim.get('id')} | {claim.get('status')} | {claim.get('risk')} | "
            f"{claim.get('owner')} | {str(claim.get('claim') or '')[:240]} | {evidence[:240]}"
        )
    text = "\n".join(lines)
    return text if len(text) <= max_chars else text[: max_chars - 20] + "\n…(truncated)"


def supported_claim_count(packet: dict[str, Any]) -> int:
    return sum(1 for c in (packet or {}).get("claims") or [] if c.get("status") == "supported")


def honest_incomplete_answer(goal: str, packet: dict[str, Any], extra_reasons: list[str] | None = None) -> str:
    """User-facing answer when models cannot produce supported work."""
    packet = normalize_packet(packet, goal=goal)
    reasons = list(extra_reasons or [])
    open_claims = [c for c in packet["claims"] if c.get("status") in {"open", "unsupported", "inferred"}]
    lines = [
        "Could not complete the request with supported evidence.",
        "",
        f"Goal: {packet.get('goal_digest') or goal}",
        "",
        "### Open / unsupported claims",
    ]
    if open_claims:
        for claim in open_claims[:12]:
            lines.append(f"- **{claim.get('id')}** ({claim.get('status')}, {claim.get('owner')}): {claim.get('claim')}")
    else:
        lines.append("- No structured claims were produced by the team.")
    if packet.get("open_questions"):
        lines.extend(["", "### Open questions"])
        for question in packet["open_questions"][:10]:
            lines.append(f"- {question}")
    if reasons:
        lines.extend(["", "### Degraded reasons"])
        for reason in reasons[:10]:
            lines.append(f"- {reason}")
    lines.extend(
        [
            "",
            "### What would unblock this",
            "- Provide a narrower goal, attach the relevant files, or free a stronger model seat.",
            "- Re-run after fixing provider limits or local model availability.",
        ]
    )
    return "\n".join(lines)


def lead_work_packet_instruction() -> str:
    return (
        "Also produce a Work Packet as a single fenced JSON object after your short plan. "
        "Schema keys: goal_digest, partitions[{worker_id,scope,must_do,must_not,acceptance}], "
        "claims[{id,owner,claim,status,evidence[{kind,ref,note}],risk}], open_questions, "
        "covered_paths, delta_for_next. "
        "Partition work so workers do not overlap paths or tasks. "
        "Mark claim status as open|inferred|supported|unsupported. "
        "Do not invent file paths; if unsure use status inferred or open without a path."
    )


def worker_work_packet_instruction(partition: dict[str, Any], packet: dict[str, Any]) -> str:
    covered = ", ".join((packet or {}).get("covered_paths") or []) or "(none yet)"
    return (
        f"Your partition only (JSON):\n{json.dumps(partition, ensure_ascii=False)}\n\n"
        f"goal_digest: {(packet or {}).get('goal_digest') or ''}\n"
        f"delta_for_next: {(packet or {}).get('delta_for_next') or ''}\n"
        f"Already covered_paths (do not re-cover): {covered}\n"
        f"Open questions: {json.dumps((packet or {}).get('open_questions') or [], ensure_ascii=False)}\n\n"
        "Return completed, evidence-backed findings for THIS partition only. "
        "Prefer a fenced JSON Work Packet with claims for your worker_id, updated covered_paths, "
        "and open_questions. Do not restate the full lead plan or redo other partitions. "
        "For each material claim include evidence (path/symbol, command+result, or labelled inference). "
        "Challenge at least one assumption in your scope or state no contradiction after checking."
    )


def review_work_packet_instruction(packet: dict[str, Any], gaps: list[str]) -> str:
    return (
        "Review the Work Packet claims. Do not re-implement or re-research the whole goal.\n"
        f"Coverage gaps: {json.dumps(gaps)}\n"
        f"Claims table:\n{claims_table(packet)}\n\n"
        "Rank material issues: unsupported claims, uncovered partitions, contradictions, missing tests. "
        "Cite claim ids. Prescribe exact corrections for the final answer. "
        "If evidence is insufficient, say what cannot honestly be concluded."
    )


def final_work_packet_instruction(goal: str, packet: dict[str, Any], review_text: str) -> str:
    return (
        f"Original user goal:\n{goal}\n\n"
        f"Work Packet claims (merge only; do not invent high-risk facts):\n{claims_table(packet)}\n\n"
        f"Open questions: {json.dumps((packet or {}).get('open_questions') or [], ensure_ascii=False)}\n\n"
        f"Reviewer notes:\n{(review_text or '')[:6000]}\n\n"
        "Produce the final user-facing answer now. Cite claim ids where you rely on them "
        "(for example [C1]). Prefer supported claims; mark residual uncertainty briefly. "
        "If there are no supported claims, write an honest incomplete report of open gaps "
        "instead of promising future work. No process commentary about leads/workers."
    )
