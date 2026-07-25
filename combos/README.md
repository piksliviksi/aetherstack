# AetherStack LLM combos

Shareable **tier presets** and **situation packs** (coding, research, testing, …).

| Artifact | Purpose |
|----------|---------|
| [`catalog.yaml`](./catalog.yaml) | Source of truth for tiers + situations |
| [`export/*.aether-combo.json`](./export/) | Ready to download / email / import |
| Hub API | `/api/combos` on port **8766** |

## Tiers (single-model / inline)

| Id | Label | Typical model |
|----|--------|----------------|
| `fable_low` | Fable Low | `local-default` (Ollama / Metal / ROCm) |
| `low_cloud` | Low cloud | `gpt-4.1-mini` |
| `medium_sonnet` | Sonnet | `claude-sonnet-4` |
| `medium_gpt` | GPT-4.1 (flagship track) | `gpt-4.1` |
| `medium_grok` | Grok 4.5 | `grok-4.5` |
| `high_opus` | Opus | `claude-opus-4` |
| `high_o3` | o3 | `o3` |
| `high_gemini` | Gemini 2.5 Pro | `gemini-2.5-pro` |

## Situations (multi-agent combos)

| Id | Intent |
|----|--------|
| `coding` | Implement / refactor (Sonnet + GPT + local workers) |
| `research` | Deep analysis (Opus + Grok + Gemini) |
| `testing` | Cheap smoke loops (Fable / mini) |
| `review` | PR review (Opus supervisor) |
| `creative_docs` | Writing |
| `private_local` | No cloud |
| `inline_sonnet` / `inline_fable` | Single model |

## Download & import

**From GitHub:**  
https://github.com/piksliviksi/aetherstack/tree/main/combos/export

```bash
# Import a downloaded file via API
curl -s -X POST http://127.0.0.1:8766/api/combos/import \
  -H "Content-Type: application/json" \
  -d @combos/export/coding.aether-combo.json

# Or drop into combos/import/ and restart hub / GET /api/combos
```

**Email:** send the `.aether-combo.json` file; recipient imports the same way.

## Launch

```bash
# List
curl -s http://127.0.0.1:8766/api/combos | jq '.situations|keys'

# Apply coding combo (sets multi_agent + role pins)
curl -s -X POST http://127.0.0.1:8766/api/combos/coding/launch

# Plan an event with that combo
curl -s -X POST http://127.0.0.1:8766/api/combos/coding/plan \
  -H "Content-Type: application/json" \
  -d '{"goal":"Add auth middleware and tests"}'

# Export for sharing
curl -s http://127.0.0.1:8766/api/combos/research/export -o research.aether-combo.json
```

## Mac ARM GPU

Combos that use `local-default` / `private_local` / `inline_fable` run on **Apple Silicon Metal** via **host Ollama** (not ROCm). See [docs/TUTORIAL-MACOS.md](../docs/TUTORIAL-MACOS.md#apple-silicon-arm64--metal-gpu).
