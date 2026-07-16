# Phase 1 — `analyze` + manifest result

**Date:** 2026-07-16 · **Verdict: GATE PASSED → Phase 2 unlocked**

**Gate (PRD §9):** `vouch analyze --claude-code` produces a correct manifest on
a machine that isn't the author's.

## Result

Installed via `pip install "git+https://github.com/sat-wik/vouch.git"` on a
friend's machine; the manifest came out correct with zero config.

## Honest caveats

1. **The kill criterion wasn't fully exercised.** Phase 1's kill condition is
   about template-slot detection failing on freeform prompts. A Claude Code run
   clusters by harness role (task hints), not fingerprints — so the friend's
   run validates the adapter and zero-config install, not slot detection on
   real non-harness traffic. Slot detection is covered by unit tests and a
   synthetic JSONL run only. First real freeform-log user should be watched.
2. One known bug was found and fixed during dogfooding before the gate: slot
   detection originally used value cardinality instead of the share of calls
   deviating from the modal value, which failed to merge low-cardinality
   template slots (e.g. 4 store names across 60 calls). Regression-tested.

## Carried forward to Phase 2

- Baseline-selection rule for `snapshot` (dominant vs most-recent model) —
  still unspecified in the PRD; Phase 0 showed model mix within a cluster is
  the norm, not the exception.
- Main-loop replay cost (~$10 at K=25) blows past the PRD's "<$1 per run"
  target because agentic prompts run ~90K input tokens with cache included.
  Snapshot sampling and/or cost accounting needs a decision.
