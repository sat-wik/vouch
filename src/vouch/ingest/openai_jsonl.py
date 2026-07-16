"""Ingest adapter for OpenAI-format request/response JSONL logs.

Accepted line shapes:
  {"request": {"model": ..., "messages": [...]}, "response": {...}}
  {"model": ..., "messages": [...], "response": {...}}          (flat request)
Lines that don't carry a messages array are skipped.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import LogRecord


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") in ("text", "input_text")
        )
    return ""


def _first_message(messages: list[dict], roles: tuple[str, ...]) -> str:
    for m in messages:
        if isinstance(m, dict) and m.get("role") in roles:
            return _content_text(m.get("content"))
    return ""


def _response_text(resp: dict[str, Any]) -> str:
    choices = resp.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") or {}
        return _content_text(message.get("content"))
    return ""


def load_openai_jsonl(path: str | Path) -> list[LogRecord]:
    records: list[LogRecord] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue

            req = obj.get("request") if isinstance(obj.get("request"), dict) else obj
            messages = req.get("messages")
            if not isinstance(messages, list):
                continue
            resp = obj.get("response") if isinstance(obj.get("response"), dict) else {}
            usage = resp.get("usage") or {}

            system = _first_message(messages, ("system", "developer")) or None
            records.append(
                LogRecord(
                    model=req.get("model") or resp.get("model") or "?",
                    system_prompt=system,
                    first_user_message=_first_message(messages, ("user",)),
                    response_text=_response_text(resp),
                    timestamp=obj.get("timestamp"),
                    input_tokens=usage.get("prompt_tokens"),
                    output_tokens=usage.get("completion_tokens"),
                    source="openai-jsonl",
                )
            )
    return records
