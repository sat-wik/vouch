# Phase 0 — Validation probe result

**Date:** 2026-07-16 · **Verdict: GATE PASSED → proceed to Phase 1**

**Gate (PRD §9):** Do ≥70% of my own Claude Code API calls fall into ≤15 coherent
clusters a human would name the same way?

## Numbers

`probe.py` over `~/.claude/projects/**/*.jsonl` — 3,402 assistant API calls,
14 transcripts, 2026-05-02 → 2026-07-16:

| # | cluster | calls | share |
|---|---|---|---|
| 1 | main:agentic-loop | 3,330 | 97.9% |
| 2 | agent:explore | 41 | 1.2% |
| 3 | agent:plan | 26 | 0.8% |
| 4 | agent:warmup | 5 | 0.1% |

**4 clusters cover 100% of calls** (need ≥70% in ≤15). Coherence check passes:
each cluster is trivially nameable (main coding loop / explore subagent / plan
subagent / warmup), and sampled thread-initiating prompts match the names.

## Deviations from the PRD's probe spec

The PRD says "system-prompt hash only." Claude Code transcripts **do not log
the system prompt** — the harness controls it. Calls were clustered by the
closest by-construction proxy: harness role of the thread (main chain vs
sidechain agent type vs slash command vs compact continuation). This is
faithful to the core-concept definition ("calls sharing a system prompt are the
same task by construction") because the harness pins the system prompt per role.

Consequence worth being honest about: **the fingerprint-hash mechanic itself is
still untested** on data that actually carries system prompts. That test is
Phase 1's JSONL adapter + a friend's machine, per the PRD's gate.

## Findings that feed Phase 1/2 design

1. **Near-degenerate distribution.** One cluster holds 97.9% of calls. Coherent
   but coarse — the regression suite for a Claude Code user is effectively "the
   main agentic loop" as a single task. That is exactly the granularity the P0
   use case needs (model swap on the main loop), so it serves P0; it just means
   manifest richness comes from non-harness data.
2. **"Incumbent" is not singular.** The main cluster's model mix is
   sonnet-4-6 (2,061) / fable-5 (877) / opus-4-8 (306) — I already swap models
   constantly, which is both evidence the product question is real and a design
   problem: `snapshot` needs a baseline-selection rule (dominant model vs most
   recent model within a window). PRD doesn't currently specify this.
3. **Slash-command traffic is negligible** in real transcripts (only built-ins
   `/model`, `/compact` appear; ~0 API calls attributable). Don't over-invest in
   command clustering in Phase 1.
4. **Probe bug worth remembering:** walking `parentUuid` to the *session* root
   absorbs mid-session command turns into the main cluster; classification must
   key off the *turn-initiating* user message. Fixed in `probe.py`; same logic
   applies to the Phase 1 Claude Code adapter.

## Kill criterion check

"If clusters are mush on the friendliest possible data, the core mechanic is
wrong." Clusters are the opposite of mush — they are clean by construction.
The unresolved risk (per PRD §9 Phase 1 kill) is template-slot detection on
freeform, non-harness prompts. That is the next thing to test, not this.
