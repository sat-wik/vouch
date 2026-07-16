"""Ingest adapter for Claude Code transcripts (~/.claude/projects/**/*.jsonl).

Claude Code does not log system prompts — the harness controls them per role.
Calls are therefore given a task_hint derived from the harness role of the
thread that produced them (main agentic loop / sidechain agent type / slash
command / compact continuation), which is the by-construction task identity.
Validated in Phase 0 (phase0/RESULT.md).
"""

from __future__ import annotations

import glob
import json
import os
import re
from typing import Any

from ..models import LogRecord

_COMMAND_RE = re.compile(r"<command-name>(/?[\w:-]+)</command-name>")


def _load_lines(path: str) -> list[dict[str, Any]]:
    recs = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                recs.append(obj)
    return recs


def _text_of(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _classify_agent(root_text: str) -> str:
    t = root_text.strip()
    if t == "Warmup":
        return "agent:warmup"
    head = t[:200].lower()
    if head.startswith("explore"):
        return "agent:explore"
    if "implementation plan" in head or head.startswith("design"):
        return "agent:plan"
    return "agent:general"


def _session_root(rec: dict, by_uuid: dict[str, dict]) -> dict:
    seen: set[str] = set()
    cur = rec
    while cur.get("parentUuid") and cur["parentUuid"] in by_uuid:
        if cur.get("uuid") in seen:
            break
        seen.add(cur["uuid"])
        cur = by_uuid[cur["parentUuid"]]
    return cur


def _turn_initiator_text(rec: dict, by_uuid: dict[str, dict]) -> str:
    """Nearest ancestor user record with real text (tool_results yield '')."""
    seen: set[str] = set()
    cur = rec
    while cur.get("parentUuid") and cur["parentUuid"] in by_uuid:
        if cur.get("uuid") in seen:
            break
        seen.add(cur["uuid"])
        cur = by_uuid[cur["parentUuid"]]
        if cur.get("type") == "user":
            text = _text_of(cur.get("message", {})).strip()
            if text:
                return text
    return ""


def _task_hint(rec: dict, by_uuid: dict[str, dict]) -> tuple[str, str]:
    """Returns (hint, sample_text) — sample is the text the call was keyed on."""
    root = _session_root(rec, by_uuid)
    root_text = _text_of(root.get("message", {})) if root.get("type") == "user" else ""
    if rec.get("isSidechain"):
        return _classify_agent(root_text), root_text
    turn_text = _turn_initiator_text(rec, by_uuid)
    cmd = _COMMAND_RE.search(turn_text)
    if cmd:
        return f"command:{cmd.group(1).lstrip('/')}", turn_text
    if root_text.startswith("This session is being continued"):
        return "main:compact-continuation", root_text
    return "main:agentic-loop", root_text


def reconstruct_messages(path: str, uuid: str) -> list[dict[str, str]]:
    """Rebuild the text conversation leading up to one assistant call.

    Walks the parentUuid chain root→call and renders each ancestor as a text
    message. Tool blocks are dropped, so this is an *approximation* of the real
    request — and the harness system prompt is absent entirely. Good enough to
    put two candidate configs on equal footing (replay both), not good enough
    to compare a replay against the production baseline directly.
    """
    recs = _load_lines(path)
    by_uuid = {r["uuid"]: r for r in recs if "uuid" in r}
    target = by_uuid.get(uuid)
    if target is None:
        return []
    chain: list[dict] = []
    seen: set[str] = set()
    cur = target
    while cur.get("parentUuid") and cur["parentUuid"] in by_uuid:
        if cur.get("uuid") in seen:
            break
        seen.add(cur["uuid"])
        cur = by_uuid[cur["parentUuid"]]
        chain.append(cur)
    messages: list[dict[str, str]] = []
    for rec in reversed(chain):
        if rec.get("type") not in ("user", "assistant"):
            continue
        text = _text_of(rec.get("message", {})).strip()
        if text:
            messages.append({"role": rec["type"], "content": text})
    return messages


def load_claude_code(base: str | None = None) -> list[LogRecord]:
    base = base or os.path.expanduser("~/.claude/projects")
    files = sorted(glob.glob(f"{base}/**/*.jsonl", recursive=True))
    records: list[LogRecord] = []
    for path in files:
        project = os.path.basename(os.path.dirname(path))
        recs = _load_lines(path)
        by_uuid = {r["uuid"]: r for r in recs if "uuid" in r}
        for r in recs:
            if r.get("type") != "assistant":
                continue
            message = r.get("message", {})
            model = message.get("model", "?")
            if model == "<synthetic>":
                continue
            hint, sample = _task_hint(r, by_uuid)
            usage = message.get("usage") or {}
            input_tokens = None
            if "input_tokens" in usage:
                # Replay pays for the full prompt; count cached tokens too.
                input_tokens = (
                    usage.get("input_tokens", 0)
                    + usage.get("cache_read_input_tokens", 0)
                    + usage.get("cache_creation_input_tokens", 0)
                )
            records.append(
                LogRecord(
                    model=model,
                    first_user_message=sample,
                    response_text=_text_of(message),
                    timestamp=r.get("timestamp"),
                    input_tokens=input_tokens,
                    output_tokens=usage.get("output_tokens"),
                    task_hint=hint,
                    source="claude-code",
                    meta={
                        "project": project,
                        "session": r.get("sessionId"),
                        "path": path,
                        "uuid": r.get("uuid"),
                    },
                )
            )
    return records
