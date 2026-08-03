#!/usr/bin/env python3
"""Safe, sandboxed if/then scripting for node behavior.

Node scripts are user-editable data (saved graphs, potentially synced/shared),
so this module must never allow arbitrary code execution: no `eval`/`exec`, no
attribute access, no imports. Conditions are parsed with Python's real
expression grammar (`ast.parse(..., mode="eval")`) for correct operator
precedence, then walked by a hand-written interpreter that only recognizes a
small whitelisted node/function set — anything else is rejected before
evaluation.
"""
from __future__ import annotations

import ast
import re
from typing import Any

import yaml

MAX_SCRIPT_CHARS = 20_000
MAX_RULES = 20

# Variables available to a script's `if:` condition.
ALLOWED_VARS = {"goal", "upstream", "model", "label", "role"}


class ScriptError(ValueError):
    """A node script is malformed or uses disallowed syntax."""


def _fn_contains(a: Any, b: Any) -> bool:
    return str(b) in str(a)


def _fn_not_contains(a: Any, b: Any) -> bool:
    return str(b) not in str(a)


MAX_MATCHES_PATTERN_CHARS = 200
MAX_MATCHES_INPUT_CHARS = 2000


def _fn_matches(a: Any, pattern: Any) -> bool:
    # Python's `re` has no timeout, so a catastrophic-backtracking pattern
    # (e.g. "(a+)+$") against attacker-influenced text — upstream output can
    # be up to MAX_STAGE_OUTPUT_CHARS (20k) and node scripts are user-editable,
    # potentially shared, graph data — can hang the executing thread
    # indefinitely. Bounding both operands' length caps the worst case;
    # it does not eliminate it, but keeps a single bad rule from being able
    # to wedge the hub for an unbounded time.
    pattern_str = str(pattern)
    if len(pattern_str) > MAX_MATCHES_PATTERN_CHARS:
        raise ScriptError(f"matches() pattern exceeds {MAX_MATCHES_PATTERN_CHARS} characters")
    text = str(a)[:MAX_MATCHES_INPUT_CHARS]
    try:
        return bool(re.search(pattern_str, text))
    except re.error as exc:
        raise ScriptError(f"invalid regex in matches(): {exc}") from exc


def _fn_lower(a: Any) -> str:
    return str(a).lower()


def _fn_upper(a: Any) -> str:
    return str(a).upper()


def _fn_len(a: Any) -> int:
    return len(str(a))


def _fn_startswith(a: Any, b: Any) -> bool:
    return str(a).startswith(str(b))


def _fn_endswith(a: Any, b: Any) -> bool:
    return str(a).endswith(str(b))


FUNCTIONS = {
    "contains": _fn_contains,
    "not_contains": _fn_not_contains,
    "matches": _fn_matches,
    "lower": _fn_lower,
    "upper": _fn_upper,
    "len": _fn_len,
    "startswith": _fn_startswith,
    "endswith": _fn_endswith,
}

_ALLOWED_NODE_TYPES = (
    ast.Expression,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.UnaryOp,
    ast.Not,
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.Gt,
    ast.LtE,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Constant,
)


def _check_node(node: ast.AST) -> None:
    if not isinstance(node, _ALLOWED_NODE_TYPES):
        raise ScriptError(f"disallowed expression syntax: {type(node).__name__}")
    for child in ast.iter_child_nodes(node):
        _check_node(child)


def _eval_node(node: ast.AST, context: dict[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, context)
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (str, int, float, bool)) and node.value is not None:
            raise ScriptError("only string/number/bool literals are allowed")
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in ALLOWED_VARS:
            raise ScriptError(
                f"unknown variable {node.id!r}; available: {', '.join(sorted(ALLOWED_VARS))}"
            )
        return context.get(node.id, "")
    if isinstance(node, ast.BoolOp):
        is_and = isinstance(node.op, ast.And)
        # Short-circuit: `matches()` can be expensive (see _fn_matches), so an
        # `and`/`or` must not evaluate every operand regardless of an earlier
        # one already deciding the result.
        result = is_and
        for value_node in node.values:
            result = bool(_eval_node(value_node, context))
            if is_and and not result:
                return False
            if not is_and and result:
                return True
        return result
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _eval_node(node.operand, context)
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, context)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval_node(comparator, context)
            if isinstance(op, ast.Eq):
                ok = left == right
            elif isinstance(op, ast.NotEq):
                ok = left != right
            elif isinstance(op, ast.Lt):
                ok = left < right
            elif isinstance(op, ast.Gt):
                ok = left > right
            elif isinstance(op, ast.LtE):
                ok = left <= right
            elif isinstance(op, ast.GtE):
                ok = left >= right
            elif isinstance(op, ast.In):
                ok = left in right
            elif isinstance(op, ast.NotIn):
                ok = left not in right
            else:
                raise ScriptError("unsupported comparison operator")
            if not ok:
                return False
            left = right
        return True
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
            raise ScriptError("unknown function call — see docs for the allowed function list")
        if node.keywords:
            raise ScriptError("keyword arguments are not supported")
        args = [_eval_node(a, context) for a in node.args]
        return FUNCTIONS[node.func.id](*args)
    raise ScriptError(f"disallowed expression syntax: {type(node).__name__}")


def evaluate_condition(expr: str, context: dict[str, Any]) -> bool:
    """Evaluate one safe if-expression. Empty/missing expression means "always true"."""
    text = str(expr or "").strip()
    if not text:
        return True
    if len(text) > 2000:
        raise ScriptError("condition expression too long")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ScriptError(f"invalid script expression: {exc}") from exc
    _check_node(tree)
    return bool(_eval_node(tree, context))


def run_script(script_yaml: str, context: dict[str, Any]) -> dict[str, Any]:
    """Parse a node's YAML script and return the first matching rule's actions.

    Returns {} when there is no script or no rule matched — callers should treat
    that as "run this node normally". Actions returned (any subset):
      - skip: bool — don't run this stage at all
      - set_model: str — override which model this stage uses
      - note: str — extra instruction appended to the stage's prompt
    """
    text = str(script_yaml or "").strip()
    if not text:
        return {}
    if len(text) > MAX_SCRIPT_CHARS:
        raise ScriptError(f"script exceeds {MAX_SCRIPT_CHARS} characters")
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ScriptError(f"invalid script YAML: {exc}") from exc
    if not parsed:
        return {}
    rules = parsed.get("rules") if isinstance(parsed, dict) else parsed
    if not isinstance(rules, list):
        raise ScriptError("script must have a top-level 'rules' list")
    if len(rules) > MAX_RULES:
        raise ScriptError(f"script has more than {MAX_RULES} rules")
    for rule in rules:
        if not isinstance(rule, dict):
            raise ScriptError("each rule must be a mapping with 'if'/'then'")
        matched = evaluate_condition(rule.get("if"), context)
        if not matched:
            continue
        then = rule.get("then") or {}
        if not isinstance(then, dict):
            raise ScriptError("'then' must be a mapping")
        actions: dict[str, Any] = {}
        if "skip" in then:
            actions["skip"] = bool(then["skip"])
        if then.get("set_model"):
            actions["set_model"] = str(then["set_model"]).strip()[:128]
        if then.get("note"):
            actions["note"] = str(then["note"]).strip()[:4000]
        return actions
    return {}
