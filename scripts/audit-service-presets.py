#!/usr/bin/env python3
"""Run every AetherStack preset against this checkout with discipline-specific prompts."""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRESET_PROMPTS = {
    "auto": "Triage the AetherStack checkout for the three highest-impact defects. Inspect code and tests, cite evidence, and name the smallest tests that would prove or disprove each finding.",
    "research": "Research how AetherStack discovers, authenticates, and routes local and subscription models. Trace primary sources in this checkout, identify unsupported assumptions or missing evidence, and run or identify research-validation tests for discovery accuracy and provenance.",
    "planning": "Audit AetherStack's current implementation as a release plan. Find dependency, sequencing, rollback, ownership, and definition-of-done gaps grounded in code. Run or identify planning-focused tests that validate upgrade, startup, and staged rollout gates.",
    "service-design": "Audit AetherStack as a local multi-model service. Trace user journeys, service boundaries, fallback/degraded states, recovery, and operator visibility. Find concrete friction and run or identify contract/journey tests reflecting service-design risks.",
    "ui-design": "Audit the AetherStack Hub and VS Code surfaces for hierarchy, consistency, responsive behavior, accessibility, focus, empty/error/loading states, and interaction clarity. Inspect the actual HTML/CSS/JS and run or identify UI and accessibility tests for each material finding.",
    "frontend": "Audit AetherStack frontend and extension code for async races, stale state, lifecycle leaks, duplicated behavioral logic, unsafe rendering, resizing, keyboard behavior, and error recovery. Run or identify focused frontend tests that reproduce the strongest findings.",
    "backend": "Audit AetherStack backend code for concurrency, authentication/authorization, state consistency, persistence, resource bounds, error leakage, observability, and failure recovery. Run or identify backend tests that directly exercise each high-risk path.",
    "coding": "Review the AetherStack codebase for concrete correctness and maintainability defects, dead code, needless duplication, fragile abstractions, and mismatched contracts. Cite paths/symbols and run or identify precise unit or integration tests for the strongest findings.",
    "testing": "Audit AetherStack's test strategy and implementation. Map critical behaviors to existing tests, find important untested branches and false-confidence tests, and propose the smallest risk-ranked test additions with exact files and assertions. Run representative tests where useful.",
    "bugfixing": "Investigate AetherStack for reproducible bugs in startup, model discovery, fallback, preset execution, streaming, and UI state. Trace likely root causes and run or identify regression tests that would fail before each fix and pass after it.",
    "whitehat-pentesting": "Perform a bounded, non-destructive security audit of AetherStack's local Hub, CLI bridge, extension, containers, secrets, browser surfaces, and workspace-write boundary. Cite concrete attack paths and run or identify safe security tests for every finding. Do not modify files or access unrelated secrets.",
    "polishing": "Audit AetherStack for user-visible rough edges, inconsistent wording/tokens, dead controls, layout problems, confusing status, and avoidable complexity. Ground findings in code and run or identify visual, structural, or interaction tests that demonstrate them.",
    "technical-writing": "Audit AetherStack documentation against implementation. Find stale commands, inaccurate architecture/fallback/security claims, broken navigation, and missing operational guidance. Run or identify documentation/link/config consistency tests for each discrepancy.",
}


def stream_run(base: str, preset: str, prompt: str, timeout: int) -> tuple[list[dict], dict | None]:
    request = urllib.request.Request(
        f"{base}/api/services/{preset}/run/stream",
        data=json.dumps(
            {
                "goal": prompt,
                "verify": True,
                "agent_budget": "adaptive",
                "token_saver": False,
                "session_id": f"preset-self-audit-{preset}-{int(time.time())}",
            }
        ).encode("utf-8"),
        headers={"Accept": "text/event-stream", "Content-Type": "application/json"},
        method="POST",
    )
    events: list[dict] = []
    result = None
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw in response:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            event = json.loads(line[5:].strip())
            if event.get("type") != "delta":
                events.append(event)
            if event.get("type") == "done":
                result = event.get("result")
            if event.get("type") == "error":
                details = " · ".join(
                    value for value in (event.get("code"), event.get("request_id")) if value
                )
                message = event.get("error") or "preset stream failed"
                raise RuntimeError(f"{message}{' · ' + details if details else ''}")
    return events, result


def write_outputs(records: list[dict], json_path: Path, md_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = [
        "# AetherStack Preset Self-Audit",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "Each preset inspected AetherStack from its own field of expertise and was asked to find or run tests that reflect that discipline.",
        "",
    ]
    for record in records:
        lines.extend(
            [
                f"## `{record['preset']}`",
                "",
                f"- Status: **{record['status']}**",
                f"- Duration: `{record['duration_seconds']}s`",
                f"- Models: `{', '.join(record.get('models') or []) or 'none'}`",
                f"- Phases: `{', '.join(record.get('phases') or []) or 'none'}`",
                f"- Degraded: `{record.get('degraded', False)}`",
                "",
                "### Audit prompt",
                "",
                record["prompt"],
                "",
                "### Result",
                "",
                record.get("answer") or record.get("error") or "No result returned.",
                "",
            ]
        )
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hub", default="http://127.0.0.1:8766")
    parser.add_argument("--timeout", type=int, default=420)
    parser.add_argument("--json", type=Path, default=ROOT / "output" / "preset-self-audit.json")
    parser.add_argument("--markdown", type=Path, default=ROOT / "AetherStack Preset Self-Audit.md")
    parser.add_argument("presets", nargs="*", help="Optional preset names; defaults to every preset")
    args = parser.parse_args()
    presets = args.presets or list(PRESET_PROMPTS)
    unknown = [preset for preset in presets if preset not in PRESET_PROMPTS]
    if unknown:
        parser.error(f"unknown preset(s): {', '.join(unknown)}")
    existing: dict[str, dict] = {}
    if args.json.exists():
        try:
            existing = {
                record["preset"]: record
                for record in json.loads(args.json.read_text(encoding="utf-8"))
                if isinstance(record, dict) and record.get("preset") in PRESET_PROMPTS
            }
        except (OSError, ValueError, TypeError):
            existing = {}
    records: list[dict] = [existing[preset] for preset in PRESET_PROMPTS if preset in existing]
    failed = False
    for preset in presets:
        print(f"[{preset}] starting", flush=True)
        started = time.monotonic()
        try:
            events, result = stream_run(args.hub.rstrip("/"), preset, PRESET_PROMPTS[preset], args.timeout)
            if not result or not result.get("ok"):
                raise RuntimeError(f"no successful result: {result}")
            phases = [event["phase"] for event in events if event.get("type") == "status" and event.get("phase")]
            models: list[str] = []
            for event in events:
                for model in [event.get("model"), *(event.get("models") or [])]:
                    if model and model not in models:
                        models.append(model)
            record = {
                "preset": preset,
                "status": "passed",
                "duration_seconds": round(time.monotonic() - started, 2),
                "prompt": PRESET_PROMPTS[preset],
                "models": models,
                "phases": phases,
                "degraded": bool(result.get("degraded")),
                "degraded_reasons": result.get("degraded_reasons") or [],
                "timings_ms": result.get("timings_ms") or {},
                "answer": result.get("answer") or "",
                "steps": result.get("steps") or [],
                "failovers": result.get("failovers") or [],
            }
        except Exception as exc:
            failed = True
            record = {
                "preset": preset,
                "status": "failed",
                "duration_seconds": round(time.monotonic() - started, 2),
                "prompt": PRESET_PROMPTS[preset],
                "error": str(exc),
            }
        existing[preset] = record
        records = [existing[name] for name in PRESET_PROMPTS if name in existing]
        write_outputs(records, args.json, args.markdown)
        print(f"[{preset}] {record['status']} in {record['duration_seconds']}s", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
