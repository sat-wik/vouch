from vouch.store import Ledger, SnapshotItem, config_hash, prompt_hash


def _items(n=3):
    return [
        SnapshotItem(
            prompt_hash=f"ph{i}",
            messages=[{"role": "user", "content": f"prompt {i}"}],
            system_prompt="do the thing",
            baseline_output=f"output {i}",
            input_tokens=100,
            output_tokens=20,
        )
        for i in range(n)
    ]


def test_snapshot_roundtrip_and_replace():
    led = Ledger(":memory:")
    led.save_snapshot("fp1", "my_task", "claude-opus-4-8", "logs.jsonl", _items(3))
    snap = led.load_snapshot("my_task")
    assert snap is not None
    assert snap.incumbent == "claude-opus-4-8"
    assert len(snap.items) == 3
    assert snap.items[0].messages == [{"role": "user", "content": "prompt 0"}]

    # Re-snapshotting the same cluster replaces, not duplicates.
    led.save_snapshot("fp1", "my_task", "claude-opus-4-8", "logs.jsonl", _items(2))
    assert len(led.load_snapshot("my_task").items) == 2
    assert len(led.list_snapshots()) == 1


def test_snapshot_resolves_by_ordinal_name_fingerprint():
    led = Ledger(":memory:")
    led.save_snapshot("fp_a", "task_a", "m", "s", _items(1))
    led.save_snapshot("fp_b", "task_b", "m", "s", _items(1))
    assert led.load_snapshot("1").name == "task_a"
    assert led.load_snapshot("task_b").fingerprint == "fp_b"
    assert led.load_snapshot("fp_b").name == "task_b"
    assert led.load_snapshot("nope") is None


def test_verdict_cache_hit():
    led = Ledger(":memory:")
    led.record_verdict("fp1", "base", "cand", "judge-m", "ph0", "tie")
    led.record_verdict("fp1", "base", "cand", "judge-m", "ph1", "loss", detail="omitted field")
    cached = led.cached_verdicts("fp1", "base", "cand", "judge-m")
    assert cached == {"ph0": "tie", "ph1": "loss"}
    # Different judge or config pair = no cache hit.
    assert led.cached_verdicts("fp1", "base", "cand", "other-judge") == {}
    assert led.cached_verdicts("fp1", "base", "other", "judge-m") == {}


def test_config_hash_distinguishes_prompt_overrides():
    a = config_hash("claude-opus-4-8", None)
    b = config_hash("claude-opus-4-8", "new system prompt")
    c = config_hash("claude-haiku-4-5", None)
    assert len({a, b, c}) == 3


def test_prompt_hash_stable():
    msgs = [{"role": "user", "content": "hi"}]
    assert prompt_hash(msgs) == prompt_hash([{"role": "user", "content": "hi"}])
