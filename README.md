# Vouch

A regression suite for your LLM calls that writes itself from production traffic.
Change a prompt or swap a model; Vouch replays your real workload clusters through
both versions, blind-judges the outputs, and tells you what actually changed.

**Status: Phase 2 machinery built (pre-release).** The verdict pipeline
(snapshot → replay → blind judge → ledger) and the Tollgate capture proxy are
implemented; the Phase 2 gate (does the judge predict lived experience?) is
still open. See [vouch-prd.md](vouch-prd.md) for the plan and the gate results
in [phase0/RESULT.md](phase0/RESULT.md) and [phase1/RESULT.md](phase1/RESULT.md).

## Quick start

```sh
pip install -e '.[dev]'

# 1. Cluster your traffic — zero config, zero network calls
vouch analyze --claude-code          # Claude Code transcripts
vouch analyze --logs calls.jsonl     # or OpenAI-format JSONL

# 2. Freeze a baseline from the logs (still zero API calls)
vouch snapshot --cluster 1 --logs calls.jsonl

# 3. About to swap models or edit a prompt? Replay + blind-judge it.
#    Prints the estimated cost and asks before spending anything.
vouch diff --cluster 1 --model claude-haiku-4-5
vouch diff --cluster 1 --prompt-file new_prompt.txt

# Verdict history (cached pairs are never re-judged — repeats are free)
vouch ledger

# No logs? Run the Tollgate proxy and point your app's base URL at it.
pip install -e '.[capture]'
vouch capture --port 4141
```

## Judge design

Verdicts come from blind pairwise judgment: tie-biased (breaks only on factual
error, omitted required info, or instruction-following failure), length/style
excluded as signals, A/B order randomized per pair with a unit-tested inversion
table, judge model never the baseline or candidate, transient failures count as
`error` — never as `loss`.

## How it works

Calls sharing a system prompt are the same task by construction. Vouch fingerprints
each call (normalized system prompt + template-slot detection via cross-call
diffing), clusters them, and prints a manifest: your production traffic organized
into tasks, each with its incumbent model and an estimated replay cost. That
manifest is the eval suite nobody had to write.

## License

MIT
