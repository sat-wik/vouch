"""Snapshot: freeze a cluster's baseline from logs. Zero API calls (PRD §4)."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from .cluster import Cluster
from .ingest.claude_code import reconstruct_messages
from .models import LogRecord
from .pricing import sample_stratified
from .store import Ledger, SnapshotItem, prompt_hash

INCUMBENT_WINDOW_DAYS = 30


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def select_incumbent(records: list[LogRecord]) -> str:
    """The dominant model in the cluster's most recent 30 days of traffic.

    Clusters mix models over time (Phase 0 finding); the baseline should
    reflect what production runs *now*, not what it ran last quarter.
    Falls back to overall dominance when timestamps are missing.
    """
    stamped = [(r, _parse_ts(r.timestamp)) for r in records]
    dated = [(r, ts) for r, ts in stamped if ts is not None]
    if dated:
        latest = max(ts for _, ts in dated)
        cutoff = latest - timedelta(days=INCUMBENT_WINDOW_DAYS)
        recent = [r for r, ts in dated if ts >= cutoff]
        if recent:
            return Counter(r.model for r in recent).most_common(1)[0][0]
    return Counter(r.model for r in records).most_common(1)[0][0]


def _messages_for(rec: LogRecord) -> list[dict]:
    if rec.messages:
        return rec.messages
    if rec.source == "claude-code" and rec.meta.get("path") and rec.meta.get("uuid"):
        msgs = reconstruct_messages(rec.meta["path"], rec.meta["uuid"])
        if msgs:
            return msgs
    if rec.first_user_message:
        return [{"role": "user", "content": rec.first_user_message}]
    return []


def build_snapshot_items(cluster: Cluster, k: int = 25) -> tuple[str, list[SnapshotItem]]:
    """Returns (incumbent, items). Only incumbent calls with a non-empty
    response are eligible — the baseline is the incumbent's actual output."""
    incumbent = select_incumbent(cluster.records)
    eligible = [
        r for r in cluster.records if r.model == incumbent and r.response_text.strip()
    ]
    items: list[SnapshotItem] = []
    seen_hashes: set[str] = set()
    for rec in sample_stratified(eligible, k):
        messages = _messages_for(rec)
        if not messages:
            continue
        ph = prompt_hash(messages)
        if ph in seen_hashes:
            continue
        seen_hashes.add(ph)
        items.append(
            SnapshotItem(
                prompt_hash=ph,
                messages=messages,
                system_prompt=rec.system_prompt,
                baseline_output=rec.response_text,
                input_tokens=rec.input_tokens,
                output_tokens=rec.output_tokens,
            )
        )
    return incumbent, items


def snapshot_cluster(ledger: Ledger, cluster: Cluster, source: str, k: int = 25) -> int:
    incumbent, items = build_snapshot_items(cluster, k=k)
    if not items:
        raise ValueError(
            f"cluster {cluster.name!r} has no incumbent calls with recorded outputs"
        )
    return ledger.save_snapshot(
        fingerprint=cluster.fingerprint,
        name=cluster.name,
        incumbent=incumbent,
        source=source,
        items=items,
    )
