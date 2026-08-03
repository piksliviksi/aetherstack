#!/usr/bin/env python3
"""Node scripting: safe if/then evaluation, and the sandbox boundary around it."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

from node_script import ScriptError, evaluate_condition, run_script  # noqa: E402


def test_no_script_means_run_normally() -> None:
    assert run_script("", {"goal": "x"}) == {}
    assert run_script(None, {"goal": "x"}) == {}


def test_first_matching_rule_wins() -> None:
    script = """
rules:
  - if: contains(goal, "security")
    then: { set_model: claude-opus-4, note: "escalate" }
  - if: true
    then: { skip: true }
"""
    result = run_script(script, {"goal": "audit this for security issues", "upstream": "", "model": "", "label": "", "role": ""})
    assert result == {"set_model": "claude-opus-4", "note": "escalate"}


def test_falls_through_to_a_later_rule() -> None:
    script = """
rules:
  - if: contains(goal, "nope")
    then: { skip: true }
  - if: len(goal) > 3
    then: { note: "long goal" }
"""
    result = run_script(script, {"goal": "hello world", "upstream": "", "model": "", "label": "", "role": ""})
    assert result == {"note": "long goal"}


def test_no_rule_matches_returns_empty() -> None:
    script = """
rules:
  - if: contains(goal, "nope")
    then: { skip: true }
"""
    assert run_script(script, {"goal": "hello", "upstream": "", "model": "", "label": "", "role": ""}) == {}


def test_boolean_and_comparison_operators() -> None:
    ctx = {"goal": "fix the bug", "upstream": "tests failing", "model": "claude-cli", "label": "", "role": ""}
    assert evaluate_condition('contains(goal, "bug") and contains(upstream, "failing")', ctx) is True
    assert evaluate_condition('contains(goal, "bug") and not contains(upstream, "passing")', ctx) is True
    assert evaluate_condition('model == "claude-cli"', ctx) is True
    assert evaluate_condition('model != "claude-cli"', ctx) is False
    assert evaluate_condition('len(goal) > 100', ctx) is False
    assert evaluate_condition('"bug" in goal', ctx) is True


def test_unknown_variable_is_rejected() -> None:
    with pytest.raises(ScriptError, match="unknown variable"):
        evaluate_condition("secret_env_var == 'x'", {"goal": "x"})


def test_unknown_function_is_rejected() -> None:
    with pytest.raises(ScriptError, match="unknown function"):
        evaluate_condition("__import__('os')", {"goal": "x"})


def test_attribute_access_is_rejected() -> None:
    with pytest.raises(ScriptError):
        evaluate_condition("goal.__class__", {"goal": "x"})


def test_arbitrary_python_statements_are_rejected_not_executed() -> None:
    # A script trying to smuggle in a statement (not an expression) must fail
    # to parse/validate rather than silently running as code.
    with pytest.raises(ScriptError):
        evaluate_condition("import os; os.system('echo pwned')", {"goal": "x"})


def test_malformed_yaml_is_a_script_error_not_a_crash() -> None:
    with pytest.raises(ScriptError, match="invalid script YAML"):
        run_script("rules: [unterminated", {"goal": "x"})


def test_rules_must_be_a_list() -> None:
    with pytest.raises(ScriptError, match="top-level 'rules' list"):
        run_script("rules: not-a-list", {"goal": "x"})


def test_script_length_is_bounded() -> None:
    with pytest.raises(ScriptError, match="exceeds"):
        run_script("rules:\n" + ("  - if: true\n    then: {skip: true}\n" * 2000), {"goal": "x"})


def test_and_short_circuits_without_evaluating_the_right_operand() -> None:
    # The right operand uses an invalid regex that would raise ScriptError if
    # evaluated - `and` short-circuiting on a false left operand must skip it.
    ctx = {"goal": "no match here", "upstream": "", "model": "", "label": "", "role": ""}
    assert evaluate_condition('contains(goal, "nope") and matches(upstream, "(unclosed")', ctx) is False


def test_or_short_circuits_without_evaluating_the_right_operand() -> None:
    ctx = {"goal": "found it", "upstream": "", "model": "", "label": "", "role": ""}
    assert evaluate_condition('contains(goal, "found") or matches(upstream, "(unclosed")', ctx) is True


def test_matches_rejects_an_overlong_pattern_instead_of_evaluating_it() -> None:
    ctx = {"goal": "x", "upstream": "y" * 100, "model": "", "label": "", "role": ""}
    with pytest.raises(ScriptError, match="pattern exceeds"):
        evaluate_condition(f'matches(upstream, "{"a" * 300}")', ctx)


def test_matches_bounds_the_input_text_length() -> None:
    # A catastrophic pattern against a huge upstream block is capped by
    # truncating the input matches() actually searches, not by evaluating
    # against the full (up to 20k char) upstream text.
    huge = "a" * 50_000
    ctx = {"goal": "x", "upstream": huge, "model": "", "label": "", "role": ""}
    # A benign match still works within the bound.
    assert evaluate_condition('matches(upstream, "^a+$")', ctx) is True
