import pytest

from vouch.judge import (
    INVERSION,
    build_judge_prompt,
    parse_reason,
    parse_verdict,
    validate_judge,
)


class TestInversionTable:
    """PRD §4: order-inversion mapping in one explicit table, unit-tested."""

    def test_candidate_shown_as_a(self):
        assert INVERSION[(True, "A")] == "win"
        assert INVERSION[(True, "B")] == "loss"
        assert INVERSION[(True, "TIE")] == "tie"

    def test_candidate_shown_as_b(self):
        assert INVERSION[(False, "A")] == "loss"
        assert INVERSION[(False, "B")] == "win"
        assert INVERSION[(False, "TIE")] == "tie"

    def test_table_is_total(self):
        assert set(INVERSION) == {
            (o, v) for o in (True, False) for v in ("A", "B", "TIE")
        }


class TestVerdictParsing:
    def test_plain(self):
        assert parse_verdict("VERDICT: TIE\nREASON: equivalent") == "TIE"

    def test_markdown_wrapped(self):
        assert parse_verdict("**VERDICT:** B\n**REASON:** omitted the date") == "B"

    def test_trailing_text_and_case(self):
        assert parse_verdict("some preamble\nverdict: a\nand more words after") == "A"

    def test_unparseable_returns_none(self):
        assert parse_verdict("I think both are fine.") is None

    def test_reason_extracted(self):
        assert parse_reason("VERDICT: B\nREASON: response A omitted `source_url`") == (
            "response A omitted `source_url`"
        )


def test_judge_may_not_be_baseline_or_candidate():
    validate_judge("claude-sonnet-4-6", "claude-opus-4-8", "claude-haiku-4-5")
    with pytest.raises(ValueError):
        validate_judge("claude-opus-4-8", "claude-opus-4-8", "claude-haiku-4-5")
    with pytest.raises(ValueError):
        validate_judge("claude-haiku-4-5", "claude-opus-4-8", "claude-haiku-4-5")


def test_judge_pairs_inversion_end_to_end(monkeypatch):
    """Whatever the random A/B order, a candidate the judge prefers must come
    back 'win' and one it rejects must come back 'loss'."""
    import asyncio
    import random
    import re

    import vouch.judge as judge_mod
    from vouch.providers import Completion

    async def fake_complete(client, model, messages, system=None, max_tokens=300):
        prompt = messages[0]["content"]
        a = re.search(r"<response_a>\n(.*?)\n</response_a>", prompt, re.S).group(1)
        pick = "A" if "GOOD" in a else "B"
        return Completion(text=f"VERDICT: {pick}\nREASON: test", latency_ms=1)

    monkeypatch.setattr(judge_mod, "complete", fake_complete)

    pairs = [(f"ph{i}", "task", "BAD baseline", "GOOD candidate") for i in range(20)]
    results = asyncio.run(
        judge_mod.judge_pairs("judge-model", pairs, rng=random.Random(7))
    )
    orders = {r.candidate_shown_as_a for r in results}
    assert orders == {True, False}  # both presentation orders exercised
    assert all(r.verdict == "win" for r in results)

    pairs = [(f"ph{i}", "task", "GOOD baseline", "BAD candidate") for i in range(20)]
    results = asyncio.run(
        judge_mod.judge_pairs("judge-model", pairs, rng=random.Random(7))
    )
    assert all(r.verdict == "loss" for r in results)


def test_judge_error_never_counts_as_loss(monkeypatch):
    import asyncio

    import vouch.judge as judge_mod
    from vouch.providers import Completion

    async def fake_complete(client, model, messages, system=None, max_tokens=300):
        return Completion(text="", error="HTTP 529: overloaded")

    monkeypatch.setattr(judge_mod, "complete", fake_complete)
    results = asyncio.run(
        judge_mod.judge_pairs("judge-model", [("ph0", "task", "a", "b")])
    )
    assert results[0].verdict == "error"


def test_judge_prompt_truncates_huge_outputs():
    prompt = build_judge_prompt("task", "x" * 100_000, "y")
    assert len(prompt) < 30_000
    assert "[... truncated ...]" in prompt
