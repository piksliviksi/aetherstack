#!/usr/bin/env python3
"""Generate LiteLLM multi-account key alias fragment (personal + enterprise)."""
from __future__ import annotations

from pathlib import Path

# (alias_base, litellm_model, env_prefix)
MODELS = [
    ("grok", "xai/grok-4.5", "XAI"),
    ("grok-4.5", "xai/grok-4.5", "XAI"),
    ("grok-4.3", "xai/grok-4.3", "XAI"),
    ("grok-4", "xai/grok-4", "XAI"),
    ("grok-4-fast", "xai/grok-4-1-fast-reasoning", "XAI"),
    ("grok-code", "xai/grok-code-fast-1", "XAI"),
    ("gpt-4.1", "openai/gpt-4.1", "OPENAI"),
    ("gpt-4.1-mini", "openai/gpt-4.1-mini", "OPENAI"),
    ("gpt-4o", "openai/gpt-4o", "OPENAI"),
    ("gpt-4o-mini", "openai/gpt-4o-mini", "OPENAI"),
    ("o3", "openai/o3", "OPENAI"),
    ("o4-mini", "openai/o4-mini", "OPENAI"),
    ("codex", "openai/gpt-4.1", "OPENAI"),
    ("claude", "anthropic/claude-sonnet-4-20250514", "ANTHROPIC"),
    ("claude-sonnet-4", "anthropic/claude-sonnet-4-20250514", "ANTHROPIC"),
    ("claude-opus-4", "anthropic/claude-opus-4-20250514", "ANTHROPIC"),
    ("claude-haiku", "anthropic/claude-3-5-haiku-latest", "ANTHROPIC"),
    ("gemini", "gemini/gemini-2.5-pro", "GOOGLE"),
    ("gemini-2.5-pro", "gemini/gemini-2.5-pro", "GOOGLE"),
    ("gemini-2.5-flash", "gemini/gemini-2.5-flash", "GOOGLE"),
    ("gemini-flash", "gemini/gemini-2.0-flash", "GOOGLE"),
    ("mistral", "mistral/mistral-large-latest", "MISTRAL"),
    ("mistral-large", "mistral/mistral-large-latest", "MISTRAL"),
    ("mistral-medium", "mistral/mistral-medium-latest", "MISTRAL"),
    ("mistral-small", "mistral/mistral-small-latest", "MISTRAL"),
    ("codestral", "mistral/codestral-latest", "MISTRAL"),
    ("pixtral", "mistral/pixtral-large-latest", "MISTRAL"),
]

SLOTS = [
    ("personal", "PERSONAL"),
    ("enterprise", "ENTERPRISE"),
]


def main() -> None:
    lines = [
        "",
        "  # ── Multi-account key slots (personal + enterprise) ───────────────",
        "  # Primary alias (no suffix) uses {PROVIDER}_API_KEY.",
        "  # -personal   → {PROVIDER}_API_KEY_PERSONAL   (personal / subscription)",
        "  # -enterprise → {PROVIDER}_API_KEY_ENTERPRISE (work / org API)",
        "  # Set both keys; use simultaneously via different model aliases.",
        "  # Regenerate: python scripts/gen-multi-key-aliases.py",
        "",
    ]
    for alias, model, prov in MODELS:
        for suffix, env_suf in SLOTS:
            env = f"{prov}_API_KEY_{env_suf}"
            name = f"{alias}-{suffix}"
            lines.append(f"  - model_name: {name}")
            lines.append("    litellm_params:")
            lines.append(f"      model: {model}")
            lines.append(f"      api_key: os.environ/{env}")
            lines.append("")

    root = Path(__file__).resolve().parents[1]
    frag = root / "litellm_multi_keys.fragment.yaml"
    frag.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {frag} ({len(MODELS) * len(SLOTS)} aliases)")


if __name__ == "__main__":
    main()
