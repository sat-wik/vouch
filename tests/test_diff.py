import pytest

from vouch.diff import plan_diff
from vouch.store import Ledger, SnapshotItem, config_hash


def _snapshot(led: Ledger, n=3, incumbent="claude-opus-4-8"):
    items = [
        SnapshotItem(
            prompt_hash=f"ph{i}",
            messages=[{"role": "user", "content": f"prompt {i}"}],
            system_prompt="sys",
            baseline_output="out",
            input_tokens=1000,
            output_tokens=100,
        )
        for i in range(n)
    ]
    led.save_snapshot("fp1", "task", incumbent, "logs", items)
    return led.load_snapshot("task")


@pytest.fixture(autouse=True)
def fake_keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")


def test_plan_skips_cached_pairs():
    led = Ledger(":memory:")
    snap = _snapshot(led)
    base = config_hash("claude-opus-4-8", None)
    cand = config_hash("claude-haiku-4-5", None)
    led.record_verdict("fp1", base, cand, "claude-sonnet-4-6", "ph0", "tie")

    plan = plan_diff(led, snap, "claude-haiku-4-5", None, "claude-sonnet-4-6", False)
    assert plan.cached == {"ph0": "tie"}
    assert len(plan.pending) == 2
    assert plan.est_cost is not None and plan.est_cost > 0


def test_plan_rejects_identical_candidate():
    led = Ledger(":memory:")
    snap = _snapshot(led)
    with pytest.raises(ValueError):
        plan_diff(led, snap, "claude-opus-4-8", None, "claude-sonnet-4-6", False)


def test_plan_rejects_self_judging():
    led = Ledger(":memory:")
    snap = _snapshot(led)
    with pytest.raises(ValueError):
        plan_diff(led, snap, "claude-haiku-4-5", None, "claude-haiku-4-5", False)


def test_replay_baseline_roughly_doubles_replay_cost():
    led = Ledger(":memory:")
    snap = _snapshot(led)
    without = plan_diff(led, snap, "claude-haiku-4-5", None, "claude-sonnet-4-6", False)
    with_rb = plan_diff(led, snap, "claude-haiku-4-5", None, "claude-sonnet-4-6", True)
    assert with_rb.est_cost > without.est_cost


def test_missing_key_fails_before_quoting(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    led = Ledger(":memory:")
    snap = _snapshot(led)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        plan_diff(led, snap, "gpt-4o", None, "claude-sonnet-4-6", False)
