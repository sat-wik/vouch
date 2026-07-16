"""The ledger: SQLite at ~/.vouch/ledger.db (PRD §4).

Snapshots are the frozen baselines; verdicts are append-only. A
(cluster, baseline config, candidate config, judge, prompt) tuple already
judged is never re-judged — the cache hit is free.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    fingerprint TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    incumbent TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshot_items (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    prompt_hash TEXT NOT NULL,
    messages_json TEXT NOT NULL,
    system_prompt TEXT,
    baseline_output TEXT NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER
);
CREATE TABLE IF NOT EXISTS verdicts (
    cluster_fingerprint TEXT NOT NULL,
    baseline_config_hash TEXT NOT NULL,
    candidate_config_hash TEXT NOT NULL,
    judge_model TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    verdict TEXT NOT NULL,
    detail TEXT,
    latency_ms INTEGER,
    cost_delta REAL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS verdicts_pair
    ON verdicts (cluster_fingerprint, baseline_config_hash,
                 candidate_config_hash, judge_model, prompt_hash);
"""


def default_db_path() -> str:
    return os.path.join(os.path.expanduser("~/.vouch"), "ledger.db")


def config_hash(model: str, system_override: str | None = None) -> str:
    """Identity of a (model, prompt) configuration. system_override=None means
    'whatever production used' — the incumbent configuration."""
    payload = json.dumps({"model": model, "system": system_override}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def prompt_hash(messages: list[dict[str, Any]]) -> str:
    payload = json.dumps(messages, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(slots=True)
class SnapshotItem:
    prompt_hash: str
    messages: list[dict[str, Any]]
    system_prompt: str | None
    baseline_output: str
    input_tokens: int | None
    output_tokens: int | None


@dataclass(slots=True)
class Snapshot:
    id: int
    fingerprint: str
    name: str
    incumbent: str
    source: str
    created_at: str
    items: list[SnapshotItem]


class Ledger:
    def __init__(self, path: str | None = None):
        path = path or default_db_path()
        if path != ":memory:":
            os.makedirs(os.path.dirname(path), exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # -- snapshots ---------------------------------------------------------

    def save_snapshot(
        self, fingerprint: str, name: str, incumbent: str, source: str,
        items: list[SnapshotItem],
    ) -> int:
        with self.conn:
            self.conn.execute(
                "DELETE FROM snapshot_items WHERE snapshot_id IN "
                "(SELECT id FROM snapshots WHERE fingerprint = ?)",
                (fingerprint,),
            )
            self.conn.execute(
                "DELETE FROM snapshots WHERE fingerprint = ?", (fingerprint,)
            )
            cur = self.conn.execute(
                "INSERT INTO snapshots (fingerprint, name, incumbent, source, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (fingerprint, name, incumbent, source, _now()),
            )
            sid = cur.lastrowid
            self.conn.executemany(
                "INSERT INTO snapshot_items VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        sid,
                        it.prompt_hash,
                        json.dumps(it.messages, ensure_ascii=False),
                        it.system_prompt,
                        it.baseline_output,
                        it.input_tokens,
                        it.output_tokens,
                    )
                    for it in items
                ],
            )
        return sid

    def list_snapshots(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT s.*, COUNT(i.prompt_hash) AS items FROM snapshots s "
            "LEFT JOIN snapshot_items i ON i.snapshot_id = s.id "
            "GROUP BY s.id ORDER BY s.id"
        ).fetchall()

    def load_snapshot(self, ref: str) -> Snapshot | None:
        """Resolve by ordinal (as listed by `vouch snapshot --list`), name, or fingerprint."""
        rows = self.list_snapshots()
        row = None
        if ref.isdigit() and 1 <= int(ref) <= len(rows):
            row = rows[int(ref) - 1]
        else:
            for r in rows:
                if r["name"] == ref or r["fingerprint"] == ref:
                    row = r
                    break
        if row is None:
            return None
        items = [
            SnapshotItem(
                prompt_hash=i["prompt_hash"],
                messages=json.loads(i["messages_json"]),
                system_prompt=i["system_prompt"],
                baseline_output=i["baseline_output"],
                input_tokens=i["input_tokens"],
                output_tokens=i["output_tokens"],
            )
            for i in self.conn.execute(
                "SELECT * FROM snapshot_items WHERE snapshot_id = ?", (row["id"],)
            )
        ]
        return Snapshot(
            id=row["id"],
            fingerprint=row["fingerprint"],
            name=row["name"],
            incumbent=row["incumbent"],
            source=row["source"],
            created_at=row["created_at"],
            items=items,
        )

    # -- verdicts ----------------------------------------------------------

    def cached_verdicts(
        self, fingerprint: str, base_hash: str, cand_hash: str, judge_model: str
    ) -> dict[str, str]:
        """prompt_hash -> verdict for pairs already judged (cache hits are free)."""
        rows = self.conn.execute(
            "SELECT prompt_hash, verdict FROM verdicts WHERE cluster_fingerprint = ? "
            "AND baseline_config_hash = ? AND candidate_config_hash = ? AND judge_model = ?",
            (fingerprint, base_hash, cand_hash, judge_model),
        ).fetchall()
        return {r["prompt_hash"]: r["verdict"] for r in rows}

    def record_verdict(
        self, fingerprint: str, base_hash: str, cand_hash: str, judge_model: str,
        prompt_hash: str, verdict: str, detail: str | None = None,
        latency_ms: int | None = None, cost_delta: float | None = None,
    ) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO verdicts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    fingerprint, base_hash, cand_hash, judge_model, prompt_hash,
                    verdict, detail, latency_ms, cost_delta, _now(),
                ),
            )

    def verdict_history(self, fingerprint: str | None = None) -> list[sqlite3.Row]:
        if fingerprint:
            return self.conn.execute(
                "SELECT * FROM verdicts WHERE cluster_fingerprint = ? ORDER BY created_at",
                (fingerprint,),
            ).fetchall()
        return self.conn.execute("SELECT * FROM verdicts ORDER BY created_at").fetchall()
