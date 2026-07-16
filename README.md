# Vouch

A regression suite for your LLM calls that writes itself from production traffic.
Change a prompt or swap a model; Vouch replays your real workload clusters through
both versions, blind-judges the outputs, and tells you what actually changed.

**Status: Phase 1 (pre-release).** `vouch analyze` works; snapshot/diff/judge land
in Phase 2. See [vouch-prd.md](vouch-prd.md) for the full plan and
[phase0/RESULT.md](phase0/RESULT.md) for the validation-probe result.

## Quick start

```sh
pip install -e '.[dev]'

# Cluster your Claude Code transcripts — zero config, zero network calls
vouch analyze --claude-code

# Or an OpenAI-format request/response JSONL log
vouch analyze --logs calls.jsonl
```

## How it works

Calls sharing a system prompt are the same task by construction. Vouch fingerprints
each call (normalized system prompt + template-slot detection via cross-call
diffing), clusters them, and prints a manifest: your production traffic organized
into tasks, each with its incumbent model and an estimated replay cost. That
manifest is the eval suite nobody had to write.

## License

MIT
