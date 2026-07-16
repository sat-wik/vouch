"""Async completion calls for replay and judging, using the user's own keys.

Routing: claude-* models → Anthropic Messages API, everything else → OpenAI
chat completions (PRD §12 defers other providers). Transient failures retry
once, then surface as errors — never as losses (PRD §4).
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_RETRYABLE = {408, 409, 429, 500, 502, 503, 529}


@dataclass(slots=True)
class Completion:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None
    error: str | None = None


def is_anthropic(model: str) -> bool:
    return model.startswith("claude")


def require_key(model: str) -> str:
    env = "ANTHROPIC_API_KEY" if is_anthropic(model) else "OPENAI_API_KEY"
    key = os.environ.get(env, "")
    if not key:
        raise RuntimeError(f"{env} is not set (needed to call {model})")
    return key


def _build_request(
    model: str, messages: list[dict], system: str | None, max_tokens: int, key: str
) -> tuple[str, dict, dict[str, Any]]:
    if is_anthropic(model):
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            body["system"] = system
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        return ANTHROPIC_URL, headers, body
    full = ([{"role": "system", "content": system}] if system else []) + messages
    body = {"model": model, "max_tokens": max_tokens, "messages": full}
    return OPENAI_URL, {"authorization": f"Bearer {key}"}, body


def _parse_response(model: str, data: dict[str, Any]) -> Completion:
    usage = data.get("usage") or {}
    if is_anthropic(model):
        text = "".join(
            b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
        )
        return Completion(
            text=text,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )
    choices = data.get("choices") or [{}]
    text = (choices[0].get("message") or {}).get("content") or ""
    return Completion(
        text=text,
        input_tokens=usage.get("prompt_tokens"),
        output_tokens=usage.get("completion_tokens"),
    )


async def complete(
    client: httpx.AsyncClient,
    model: str,
    messages: list[dict],
    system: str | None = None,
    max_tokens: int = 4096,
) -> Completion:
    url, headers, body = _build_request(
        model, messages, system, max_tokens, require_key(model)
    )
    last_error = "unknown error"
    for attempt in range(2):
        start = time.monotonic()
        try:
            resp = await client.post(url, headers=headers, json=body, timeout=300.0)
        except httpx.HTTPError as exc:
            last_error = f"transport: {exc}"
        else:
            latency = int((time.monotonic() - start) * 1000)
            if resp.status_code == 200:
                out = _parse_response(model, resp.json())
                out.latency_ms = latency
                return out
            last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            if resp.status_code not in _RETRYABLE:
                break
        if attempt == 0:
            await asyncio.sleep(2.0)
    return Completion(text="", error=last_error)


async def complete_many(
    model: str,
    requests: list[tuple[list[dict], str | None]],
    max_tokens: int = 4096,
    concurrency: int = 4,
) -> list[Completion]:
    """Run many (messages, system) requests through one model concurrently."""
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient() as client:

        async def one(messages: list[dict], system: str | None) -> Completion:
            async with sem:
                return await complete(client, model, messages, system, max_tokens)

        return list(
            await asyncio.gather(*(one(m, s) for m, s in requests))
        )
