"""Model pricing for replay-cost estimates.

USD per million tokens (input, output). Anthropic prices from the official
model table (cached 2026-06); unknown models get no estimate rather than a
wrong one. Replay cost is an estimate printed before any paid action — it
does not need to be exact, it needs to not surprise anyone.
"""

from __future__ import annotations

from .models import LogRecord

PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-fable-5": (10.00, 50.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-opus-4-5": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}


def price_for(model: str) -> tuple[float, float] | None:
    if model in PRICES_PER_MTOK:
        return PRICES_PER_MTOK[model]
    # Date-suffixed IDs (claude-haiku-4-5-20251001) share the alias price.
    for known, price in PRICES_PER_MTOK.items():
        if model.startswith(known):
            return price
    return None


def sample_stratified(records: list[LogRecord], k: int) -> list[LogRecord]:
    """K records stratified by input-token length (PRD §4: snapshot sampling)."""
    if len(records) <= k:
        return list(records)
    ordered = sorted(records, key=lambda r: r.est_input_tokens())
    step = len(ordered) / k
    return [ordered[int(i * step)] for i in range(k)]


def est_replay_cost(records: list[LogRecord], model: str, k: int = 25) -> float | None:
    """Estimated cost of replaying K representative prompts through `model`."""
    price = price_for(model)
    if price is None or not records:
        return None
    in_price, out_price = price
    sample = sample_stratified(records, k)
    in_tokens = sum(r.est_input_tokens() for r in sample)
    out_tokens = sum(r.est_output_tokens() for r in sample)
    return (in_tokens * in_price + out_tokens * out_price) / 1_000_000
