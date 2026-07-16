# Vouch — PRD v1.0

**One-liner:** A regression suite for your LLM calls that writes itself from production traffic. Change a prompt or swap a model; Vouch replays your real workload clusters through both versions, blind-judges the outputs, and tells you what actually changed — in your terminal or on your PR.

**Status:** Draft · **Author:** Satwik · **Date:** July 2026 · **License:** MIT

*(Working name. "Vouch" = the tool vouches that a change is safe. Alternates: Attest, Bellwether, Regress. Pick one that survives a PyPI/npm/domain search before writing code.)*

---

## 1. Problem

Every team shipping an LLM feature edits prompts weekly and swaps models quarterly (by choice or by provider deprecation). Almost none of them can answer "did that change make things worse?" with anything but vibes.

Eval platforms exist (Braintrust, LangSmith, Langfuse, promptfoo) and are barely used by product teams, because they all share one assumption: **you author the eval dataset.** Writing test cases is miserable, goes stale immediately, and requires knowing your failure modes in advance. So teams skip it, ship the prompt edit, and find out from users.

The unmet insight, validated by Frugon's HN reception (the top critical comment was "I don't see how anyone can operationalize this"): the raw material for a task-specific eval suite already exists in every team's production logs. Calls sharing a system prompt are the same task **by construction**. Cluster them, snapshot the incumbent outputs, and you have a regression baseline nobody had to write.

## 2. Non-goals (scope fence)

- **Not a cost analyzer.** Frugon exists; cost is a deflating value axis. Vouch may *report* cost deltas as a side effect of replay, but never optimizes for them.
- **Not a router or gateway.** Vouch never sits in the production hot path for routing decisions. (The capture proxy observes; it does not redirect.)
- **Not a general eval platform.** No dataset authoring UI, no human-annotation queues, no model leaderboards. Zero-authoring is the identity; the moment we add a test-case editor we've become a worse Braintrust.
- **Not hosted, in v1.** Local-first, logs never leave the machine except explicit replay/judge calls to providers using the user's own keys (Frugon's trust model, which HN accepted without a single objection).

## 3. Users

| Persona | Trigger | What they run |
|---|---|---|
| **P0: Satwik** (dogfood) | Own Claude Code transcripts; Tollgate resume item | `vouch analyze`, `vouch snapshot` |
| **P1: Solo dev / small team with an LLM feature** | About to edit a system prompt; scared | `vouch diff` locally before shipping |
| **P2: Team with CI** | Prompt strings live in the repo; PRs change them | GitHub Action comments verdict table on PR |
| **P3 (later): Team hit by deprecation notice** | Forced model swap by a date | `vouch diff --model` across whole ledger |

P0 must be fully satisfied before P1 is attempted. P1 before P2.

## 4. Core concepts

**Cluster.** A group of calls sharing a task, keyed by fingerprint: `hash(normalized_system_prompt) + first-user-message shape + token profile`. Normalization strips timestamps, UUIDs, and interpolated variables (detect via cross-call diffing: tokens that vary across >N% of calls in an otherwise-identical prompt are template slots). Clusters get human-readable auto-names from the system prompt's first clause ("Classify the sentiment…" → `classify_sentiment`).

**Snapshot.** For each cluster: K representative prompts (stratified by token length; K=25 default) plus the incumbent model's actual production outputs for them. This is the baseline. Zero API calls to create — it's extracted from logs.

**Replay.** Run the K prompts through the *candidate* configuration (new prompt text, or new model, or both) using the user's keys. Costs real money; always prints the estimated cost and asks before running.

**Verdict.** Blind pairwise judgment per prompt: baseline output vs candidate output. Judge design requirements (independently implemented; informed by what worked in Frugon's MIT-licensed judge and by the LLM-as-judge literature):
- Tie-biased: breaks only on factual error, omitted required info, or instruction-following failure
- Length/style/formatting explicitly excluded as quality signals
- Judge never sees which output is incumbent; A/B presentation order randomized per pair
- Judge model must not be either the baseline or the candidate (no self-evaluation)
- Order-inversion mapping in one explicit table, unit-tested
- Verdict parsing tolerant of markdown wrapping and trailing text; regex on `VERDICT:\s*(TIE|A|B)`
- Transient failures retry once then count as `error`, never as `loss`

**Ledger.** SQLite (`~/.vouch/ledger.db`). Append-only verdicts table:
`(cluster_fingerprint, baseline_config_hash, candidate_config_hash, judge_model, prompt_hash, verdict, latency_ms, cost_delta, created_at)`
This is the asset. Verdicts persist across runs; a config pair already judged is never re-judged (cache hit = free). Frugon's own roadmap flags statelessness as its known hole — the ledger is the structural answer.

## 5. Architecture

```
                    ┌──────────────────────────────────────┐
  ingest adapters   │              vouch core              │
┌─────────────────┐ │                                      │
│ claude-code     │─┤  normalize → LogRecord               │
│ (~/.claude/)    │ │       │                              │
│ openai-jsonl    │─┤       ▼                              │
│ capture proxy   │─┤  cluster.py ──► manifest             │    surfaces
│ (== Tollgate)   │ │       │                              │  ┌────────────┐
└─────────────────┘ │       ▼                              │  │ terminal   │
                    │  snapshot.py ─► baselines            ├─►│ markdown   │
   user's keys ────►│  replay.py ───► candidate outputs    │  │ PR comment │
                    │  judge.py ────► verdicts             │  └────────────┘
                    │       │                              │
                    │       ▼                              │
                    │  ledger.db (SQLite, append-only)     │
                    └──────────────────────────────────────┘
```

**Stack:** Python 3.12, `httpx` + `asyncio` for replay concurrency, SQLite (stdlib), `typer` for CLI, `tiktoken` fallback tokenization. The capture proxy is FastAPI + httpx + SSE passthrough — **this component is Tollgate**, name and all; it ships as `vouch capture` and independently as the Tollgate repo on the resume. Streaming SSE passthrough is table stakes (Frugon 400s on `stream:true`, which locks out nearly all real traffic — do not repeat this).

**Ingest priority order (deliberate):**
1. `--claude-code`: read `~/.claude/projects/**/*.jsonl` directly. Zero setup, and it's the audience with acute pain (quota-limited agent users — the exact user Frugon's own Show HN story described and then didn't serve).
2. `--logs file.jsonl`: OpenAI-format request/response JSONL.
3. `vouch capture`: local proxy for apps that don't log. Must support streaming, `/v1/chat/completions`, `/v1/messages` (Anthropic), and `/v1/responses` day one.

## 6. CLI surface (v1 complete set — resist additions)

```
vouch analyze  [--claude-code | --logs F | --db]   # cluster + manifest, zero network
vouch snapshot [--cluster N] [-k 25]               # freeze baselines from logs
vouch diff     --prompt-file new.txt --cluster N   # replay + judge vs baseline
vouch diff     --model claude-haiku-4-5            # same, model-swap variant
vouch capture  [--port 4141]                       # Tollgate proxy
vouch ledger   [--cluster N]                       # verdict history
```

`vouch analyze` output is the **cluster manifest** — the direct answer to "how do I operationalize this":

```
6 task clusters found (14,203 calls, 31 days)

 #  cluster                calls   incumbent          est. replay cost
 1  classify_sentiment     6,120   claude-opus-4-8    $0.41
 2  summarize_chunk        3,882   claude-opus-4-8    $0.88
 3  extract_invoice_json   2,101   gpt-4o             $0.35
 ...
 → vouch snapshot --cluster 1 && vouch diff --model claude-haiku-4-5 --cluster 1
```

## 7. GitHub Action (Phase 3)

Trigger: PR modifies a file matched by `vouch.toml` prompt-path globs (or a tracked prompt string's hash changes). Action runs `vouch diff` against the ledger's baselines, comments:

```
🔍 Vouch: prompt change detected in prompts/summarizer.txt → cluster summarize_chunk

  25 replays vs baseline · judge: gpt-5.2 (blind, order-randomized)
  ✅ 21 tie   ⚠️ 1 win   ❌ 3 loss

  Regressions (3): omitted required field `source_url` in outputs #7, #12, #19
  Verdict detail + outputs: [artifact link]
```

Requires: repo secret for provider key, ledger committed or cached (ledger-in-repo as SQLite file is fine at this scale; revisit >50MB). Fail-the-check threshold configurable; default is comment-only (precision over recall — a noisy gate gets uninstalled).

## 8. Competition — honest table

| | Authoring required | Local-first | CI-native | Zero-setup ingest | Verdict memory |
|---|---|---|---|---|---|
| **promptfoo** | Yes (YAML test cases) | Yes | Yes | No | No |
| **Braintrust / LangSmith** | Yes (datasets) | No | Partial | Via their SDK | Yes (theirs) |
| **Langfuse** | Yes (datasets from traces, manual curation) | Self-hostable | Weak | Via their SDK | Partial |
| **Frugon** | No | Yes | No | No (JSONL only, no streaming) | No (stateless) |
| **Vouch** | **No** | Yes | Yes | Claude Code + proxy | Ledger |

The defensible cell is the column: **zero authoring.** Everything else is table stakes or copyable. Braintrust could ship auto-clustering from traces; the bet is that their ICP (ML teams who already write evals) doesn't demand it, and their architecture (hosted, SDK-instrumented) can't serve the local-first agent-user wedge. This bet is checkable: if any incumbent ships zero-authoring cluster-based regression before Phase 3 completes, re-evaluate at that gate rather than pushing on.

Also honest: **promptfoo has enormous mindshare.** Positioning is "Vouch feeds promptfoo-style workflows without the YAML," not "promptfoo killer."

## 9. Phases, gates, kill criteria

Each phase ≈ 1–2 weekends. **A gate must be passed before the next phase starts. A failed gate triggers its kill criterion — write the postmortem, don't renegotiate the gate.**

### Phase 0 — Validation probe (1 weekend, ~zero code)
Cluster your own Claude Code transcripts with a throwaway script (system-prompt hash only, no normalization).
**Gate:** Do ≥70% of your calls fall into ≤15 coherent clusters a human would name the same way?
**Kill:** If clusters are mush on the friendliest possible data (your own), the core mechanic is wrong. Stop. Total sunk cost: one weekend.

### Phase 1 — `analyze` + manifest (1–2 weekends)
Ingest adapters (Claude Code + JSONL), normalization with template-slot detection, cluster manifest output.
**Gate:** `uvx vouch analyze --claude-code` produces a correct manifest on a machine that isn't yours (one friend/colleague).
**Kill:** If template-slot detection can't get clusters clean without per-user config, the zero-authoring promise is false — this becomes promptfoo-with-extra-steps. Stop or re-scope to Claude-Code-only where prompts are harness-controlled.

### Phase 2 — snapshot / replay / judge / ledger (2 weekends)
The verdict machinery. Includes the streaming-capable capture proxy (**Tollgate ships here** — independent repo, listed on resume, done before interviews regardless of Vouch's fate).
**Gate — the load-bearing one:** Take one of your real clusters. Run `vouch diff --model <cheaper>` (25 samples). Then *actually switch* that cluster in your own usage for a week. Did the judge's verdict predict your lived experience?
**Kill:** If a clean verdict preceded a real-use regression, the judge is theater and the product's one promise is false. This is the assumption Frugon never tested. Do not build Phase 3 on an untested judge.

### Phase 3 — GitHub Action + release (2 weekends)
Action, README with a real (non-synthetic) demo, eval writeup: judge-vs-reality results from Phase 2's gate published as a table — this is the credibility artifact Frugon lacked. Show HN.
**Gate:** Within 30 days: ≥10 people you don't know have *run* it (telemetry-free proxy: GitHub issues, PyPI downloads sustained past launch week, Action installs — not stars).
**Kill:** Stars-but-no-runs = Frugon's exact outcome (98 stars, 0 forks). If it happens to Vouch too, the problem is the category, not the execution. Archive with a postmortem; keep Tollgate.

### Phase 4 — exists only if Gate 3 passes
Talk to 5 actual users (the ones who filed issues) before writing any further code. Business questions (hosted ledger, team features, pricing) live entirely on the far side of those conversations. **This PRD deliberately does not spec Phase 4.**

## 10. Success metrics

- **P0:** You yourself run `vouch diff` before a real prompt/model change ≥3 times because you *want* the answer. (If the author won't dogfood it, no gate matters.)
- **Time-to-first-manifest** for a new Claude Code user: < 60 seconds, zero config.
- **Judge fidelity:** Phase 2 gate result, published.
- **Adoption:** Gate 3 numbers.

## 11. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Judge verdicts don't predict real regressions | **Fatal** | Phase 2 gate exists precisely for this; tested on self before any user |
| Clustering fails on non-harness traffic (freeform prompts) | High | Phase 1 kill/re-scope path; Claude Code wedge doesn't depend on it |
| Incumbent ships zero-authoring evals | Medium | Checkable at each gate; wedge (local-first, agent logs) is the part they structurally won't do |
| Replay costs deter usage | Medium | Cost printed before every replay; K=25 default keeps runs <$1; ledger cache makes repeats free |
| Prompt content is sensitive; teams won't run judge via external API | Medium | Local judge via Ollama as a supported (clearly labeled lower-fidelity) option |
| FreeWheel IP assignment | Low but check | Nothing here touches billing/adtech domain knowledge; generic OSS on own hardware/time. Skim the agreement anyway. |
| Author abandons at PRD stage | **Known pattern, 8 priors** | Phase 0 is one weekend and requires no design decisions. It is scheduled for **this** weekend or the project is declared dead now, honestly, at zero cost. |

## 12. Explicitly deferred

Multi-repo ledgers, hosted anything, team auth, non-OpenAI-shape provider adapters beyond Anthropic, semantic clustering via local embeddings (only if fingerprint clustering proves insufficient — don't gold-plate), cost reporting beyond incidental deltas, promptfoo export format.
