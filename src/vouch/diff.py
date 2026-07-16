"""The diff flow: replay a candidate config against a snapshot and judge it."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from .judge import JudgedPair, judge_pairs, render_task, validate_judge
from .pricing import price_for
from .providers import complete_many, require_key
from .store import Ledger, Snapshot, config_hash

_JUDGE_OUTPUT_TOKENS = 300


@dataclass(slots=True)
class DiffPlan:
    snapshot: Snapshot
    candidate_model: str
    system_override: str | None  # new prompt text, or None = keep production prompt
    judge_model: str
    replay_baseline: bool
    base_hash: str
    cand_hash: str
    pending: list[int]  # indexes into snapshot.items still needing a verdict
    cached: dict[str, str]  # prompt_hash -> verdict already in the ledger
    est_cost: float | None


@dataclass(slots=True)
class DiffResult:
    counts: dict[str, int] = field(default_factory=dict)
    rows: list[tuple[str, str, str | None]] = field(default_factory=list)  # (hash, verdict, reason)


def _est_tokens_for_item(item) -> tuple[int, int]:
    in_toks = item.input_tokens or max(
        1, sum(len(m.get("content", "")) for m in item.messages) // 4
    )
    out_toks = item.output_tokens or max(1, len(item.baseline_output) // 4)
    return in_toks, out_toks


def plan_diff(
    ledger: Ledger,
    snapshot: Snapshot,
    candidate_model: str | None,
    system_override: str | None,
    judge_model: str,
    replay_baseline: bool,
) -> DiffPlan:
    candidate_model = candidate_model or snapshot.incumbent
    if candidate_model == snapshot.incumbent and system_override is None:
        raise ValueError("candidate config is identical to the baseline — change --model or --prompt-file")
    validate_judge(judge_model, snapshot.incumbent, candidate_model)
    # Fail fast on missing keys before quoting a price.
    require_key(candidate_model)
    require_key(judge_model)
    if replay_baseline:
        require_key(snapshot.incumbent)

    base_hash = config_hash(snapshot.incumbent, None)
    cand_hash = config_hash(candidate_model, system_override)
    cached = ledger.cached_verdicts(
        snapshot.fingerprint, base_hash, cand_hash, judge_model
    )
    pending = [
        i for i, it in enumerate(snapshot.items) if it.prompt_hash not in cached
    ]

    est: float | None = 0.0
    for i in pending:
        in_toks, out_toks = _est_tokens_for_item(snapshot.items[i])
        legs = [(candidate_model, in_toks, out_toks)]
        if replay_baseline:
            legs.append((snapshot.incumbent, in_toks, out_toks))
        judge_in = min(in_toks, 2000) + 2 * out_toks + 200
        legs.append((judge_model, judge_in, _JUDGE_OUTPUT_TOKENS))
        for model, itk, otk in legs:
            price = price_for(model)
            if price is None:
                est = None
                break
            est = est + (itk * price[0] + otk * price[1]) / 1_000_000 if est is not None else None
        if est is None:
            break

    return DiffPlan(
        snapshot=snapshot,
        candidate_model=candidate_model,
        system_override=system_override,
        judge_model=judge_model,
        replay_baseline=replay_baseline,
        base_hash=base_hash,
        cand_hash=cand_hash,
        pending=pending,
        cached=cached,
        est_cost=est,
    )


async def _execute(plan: DiffPlan, ledger: Ledger) -> DiffResult:
    snap = plan.snapshot
    items = [snap.items[i] for i in plan.pending]

    cand_requests = [
        (it.messages, plan.system_override or it.system_prompt) for it in items
    ]
    candidate_outs = await complete_many(plan.candidate_model, cand_requests)

    if plan.replay_baseline:
        base_requests = [(it.messages, it.system_prompt) for it in items]
        baseline_outs = await complete_many(snap.incumbent, base_requests)
        baseline_texts = [c.text for c in baseline_outs]
        baseline_errors = [c.error for c in baseline_outs]
    else:
        baseline_texts = [it.baseline_output for it in items]
        baseline_errors = [None] * len(items)

    result = DiffResult(counts={"win": 0, "loss": 0, "tie": 0, "error": 0})
    for ph, verdict in plan.cached.items():
        result.counts[verdict] = result.counts.get(verdict, 0) + 1
        result.rows.append((ph, f"{verdict} (cached)", None))

    pairs = []
    pair_meta = []  # parallel: (item, candidate Completion)
    for it, cand, base_text, base_err in zip(
        items, candidate_outs, baseline_texts, baseline_errors
    ):
        err = cand.error or base_err
        if err:
            ledger.record_verdict(
                snap.fingerprint, plan.base_hash, plan.cand_hash, plan.judge_model,
                it.prompt_hash, "error", detail=err,
            )
            result.counts["error"] += 1
            result.rows.append((it.prompt_hash, "error", err))
            continue
        task = render_task(it.messages, plan.system_override or it.system_prompt)
        pairs.append((it.prompt_hash, task, base_text, cand.text))
        pair_meta.append((it, cand))

    judged: list[JudgedPair] = await judge_pairs(plan.judge_model, pairs)

    cand_price = price_for(plan.candidate_model)
    base_price = price_for(snap.incumbent)
    for jp, (it, cand) in zip(judged, pair_meta):
        cost_delta = None
        if cand_price and base_price:
            b_in, b_out = _est_tokens_for_item(it)
            c_in = cand.input_tokens or b_in
            c_out = cand.output_tokens or b_out
            cost_delta = (
                (c_in * cand_price[0] + c_out * cand_price[1])
                - (b_in * base_price[0] + b_out * base_price[1])
            ) / 1_000_000
        ledger.record_verdict(
            snap.fingerprint, plan.base_hash, plan.cand_hash, plan.judge_model,
            it.prompt_hash, jp.verdict, detail=jp.reason,
            latency_ms=jp.latency_ms, cost_delta=cost_delta,
        )
        result.counts[jp.verdict] = result.counts.get(jp.verdict, 0) + 1
        result.rows.append((it.prompt_hash, jp.verdict, jp.reason))
    return result


def run_diff(plan: DiffPlan, ledger: Ledger) -> DiffResult:
    return asyncio.run(_execute(plan, ledger))
