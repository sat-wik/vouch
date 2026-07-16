"""Blind pairwise judge (PRD §4).

Design requirements implemented here:
- Tie-biased: breaks only on factual error, omitted required info, or
  instruction-following failure.
- Length/style/formatting explicitly excluded as quality signals.
- Judge never sees which output is incumbent; A/B order randomized per pair.
- Judge model must not be the baseline or candidate model.
- Order-inversion mapping in one explicit table, unit-tested.
- Verdict parsing tolerant of markdown wrapping and trailing text.
- Transient failures retry once (in providers.complete) then count as
  `error`, never as `loss`.
"""

from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass

import httpx

from .providers import complete

_VERDICT_RE = re.compile(r"VERDICT[:\s*_]*\**\s*(TIE|A|B)\b", re.IGNORECASE)
_REASON_RE = re.compile(r"REASON[:\s*_]*\**\s*(.+)", re.IGNORECASE)

# The one explicit order-inversion table (unit-tested).
# Key: (candidate_shown_as_A, judge's letter) -> verdict for the CANDIDATE.
INVERSION: dict[tuple[bool, str], str] = {
    (True, "A"): "win",
    (True, "B"): "loss",
    (True, "TIE"): "tie",
    (False, "A"): "loss",
    (False, "B"): "win",
    (False, "TIE"): "tie",
}

JUDGE_SYSTEM = """\
You compare two AI assistant responses to the same task and decide whether one \
is materially better at the task, or whether they are equivalent.

Rules:
- Default to TIE. Break the tie only if one response contains a factual error, \
omits information the task requires, or fails to follow the task's instructions.
- Length, verbosity, style, tone, and formatting are NOT quality signals. A \
shorter or plainer response is not worse.
- Judge task success only. Do not reward extra unrequested content.

Reply with exactly two lines:
VERDICT: TIE or A or B
REASON: one sentence naming the specific defect (or "equivalent")\
"""

_MAX_TASK_CHARS = 6000
_MAX_OUTPUT_CHARS = 12000


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n[... truncated ...]\n{text[-half:]}"


def render_task(messages: list[dict], system_prompt: str | None) -> str:
    parts = []
    if system_prompt:
        parts.append(f"[system instructions]\n{system_prompt}")
    for m in messages:
        parts.append(f"[{m.get('role', 'user')}]\n{m.get('content', '')}")
    return _clip("\n\n".join(parts), _MAX_TASK_CHARS)


def build_judge_prompt(task: str, response_a: str, response_b: str) -> str:
    return (
        f"Task given to both assistants:\n<task>\n{task}\n</task>\n\n"
        f"<response_a>\n{_clip(response_a, _MAX_OUTPUT_CHARS)}\n</response_a>\n\n"
        f"<response_b>\n{_clip(response_b, _MAX_OUTPUT_CHARS)}\n</response_b>"
    )


def parse_verdict(text: str) -> str | None:
    m = _VERDICT_RE.search(text)
    return m.group(1).upper() if m else None


def parse_reason(text: str) -> str | None:
    m = _REASON_RE.search(text)
    return m.group(1).strip() if m else None


@dataclass(slots=True)
class JudgedPair:
    prompt_hash: str
    verdict: str  # win | loss | tie | error (candidate-relative)
    reason: str | None
    candidate_shown_as_a: bool
    latency_ms: int | None


def validate_judge(judge_model: str, baseline_model: str, candidate_model: str) -> None:
    if judge_model in (baseline_model, candidate_model):
        raise ValueError(
            f"judge model {judge_model!r} must differ from both the baseline "
            f"({baseline_model}) and the candidate ({candidate_model}) — no self-evaluation"
        )


async def judge_pairs(
    judge_model: str,
    pairs: list[tuple[str, str, str, str | None]],  # (prompt_hash, task, baseline_out, candidate_out via next arg)
    *,
    concurrency: int = 4,
    rng: random.Random | None = None,
) -> list[JudgedPair]:
    """pairs entries are (prompt_hash, task_text, baseline_output, candidate_output)."""
    rng = rng or random.Random()
    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient() as client:

        async def one(ph: str, task: str, baseline: str, candidate: str) -> JudgedPair:
            candidate_is_a = rng.random() < 0.5
            a, b = (candidate, baseline) if candidate_is_a else (baseline, candidate)
            prompt = build_judge_prompt(task, a, b)
            async with sem:
                result = await complete(
                    client,
                    judge_model,
                    [{"role": "user", "content": prompt}],
                    system=JUDGE_SYSTEM,
                    max_tokens=300,
                )
            if result.error:
                return JudgedPair(ph, "error", result.error, candidate_is_a, None)
            letter = parse_verdict(result.text)
            if letter is None:
                return JudgedPair(
                    ph, "error", f"unparseable verdict: {result.text[:120]}",
                    candidate_is_a, result.latency_ms,
                )
            return JudgedPair(
                ph,
                INVERSION[(candidate_is_a, letter)],
                parse_reason(result.text),
                candidate_is_a,
                result.latency_ms,
            )

        return list(
            await asyncio.gather(
                *(one(ph, task, base, cand) for ph, task, base, cand in pairs)
            )
        )
