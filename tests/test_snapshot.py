from vouch.cluster import Cluster
from vouch.models import LogRecord
from vouch.snapshot import build_snapshot_items, select_incumbent


def _rec(model, ts=None, response="ok", user="do it", messages=None):
    return LogRecord(
        model=model,
        first_user_message=user,
        response_text=response,
        timestamp=ts,
        messages=messages,
    )


def test_incumbent_is_recent_dominant_not_alltime_dominant():
    # Old traffic ran opus; the last month ran haiku. Baseline should be haiku.
    records = (
        [_rec("claude-opus-4-8", f"2026-01-{d:02d}T00:00:00Z") for d in range(1, 29)]
        + [_rec("claude-haiku-4-5", f"2026-07-{d:02d}T00:00:00Z") for d in range(1, 11)]
    )
    assert select_incumbent(records) == "claude-haiku-4-5"


def test_incumbent_falls_back_to_overall_dominance_without_timestamps():
    records = [_rec("a"), _rec("a"), _rec("b")]
    assert select_incumbent(records) == "a"


def test_snapshot_items_only_incumbent_with_outputs():
    records = [
        _rec("claude-opus-4-8", response="real output", user=f"prompt {i}")
        for i in range(5)
    ] + [
        _rec("claude-haiku-4-5", response="other model"),
        _rec("claude-opus-4-8", response="   "),  # empty output → ineligible
    ]
    cluster = Cluster(fingerprint="fp", name="t", template="t", records=records)
    incumbent, items = build_snapshot_items(cluster, k=25)
    assert incumbent == "claude-opus-4-8"
    assert len(items) == 5
    assert all(it.baseline_output == "real output" for it in items)


def test_snapshot_dedupes_identical_prompts():
    records = [_rec("m", response="out", user="same prompt") for _ in range(10)]
    cluster = Cluster(fingerprint="fp", name="t", template="t", records=records)
    _, items = build_snapshot_items(cluster, k=25)
    assert len(items) == 1
