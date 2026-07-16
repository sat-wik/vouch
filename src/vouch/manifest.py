"""Cluster manifest rendering — the output of `vouch analyze` (PRD §6)."""

from __future__ import annotations

from .cluster import Cluster
from .models import LogRecord
from .pricing import est_replay_cost


def _span_days(records: list[LogRecord]) -> int | None:
    stamps = sorted(r.timestamp for r in records if r.timestamp)
    if len(stamps) < 2:
        return None
    try:
        from datetime import datetime

        first = datetime.fromisoformat(stamps[0].replace("Z", "+00:00"))
        last = datetime.fromisoformat(stamps[-1].replace("Z", "+00:00"))
        return max(1, (last - first).days)
    except ValueError:
        return None


def render_manifest(clusters: list[Cluster], k: int = 25) -> str:
    all_records = [r for c in clusters for r in c.records]
    total = len(all_records)
    days = _span_days(all_records)
    span = f", {days} days" if days else ""

    lines = [
        f"{len(clusters)} task cluster{'s' if len(clusters) != 1 else ''} found "
        f"({total:,} calls{span})",
        "",
    ]
    name_w = max(len("cluster"), *(len(c.name) for c in clusters)) if clusters else 7
    model_w = (
        max(len("incumbent"), *(len(c.incumbent) for c in clusters)) if clusters else 9
    )
    header = (
        f"{'#':>3}  {'cluster':<{name_w}}  {'calls':>7}  "
        f"{'incumbent':<{model_w}}  est. replay cost"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for i, c in enumerate(clusters, 1):
        cost = est_replay_cost(c.records, c.incumbent, k=k)
        if cost is None:
            cost_str = "—"
        elif cost < 0.01:
            cost_str = "<$0.01"
        else:
            cost_str = f"${cost:,.2f}"
        lines.append(
            f"{i:>3}  {c.name:<{name_w}}  {c.calls:>7,}  "
            f"{c.incumbent:<{model_w}}  {cost_str}"
        )

    if clusters:
        lines.append("")
        lines.append(
            "→ vouch snapshot --cluster 1 && "
            "vouch diff --model claude-haiku-4-5 --cluster 1"
        )
    return "\n".join(lines)
