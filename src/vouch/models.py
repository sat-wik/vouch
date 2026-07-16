from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Rough chars-per-token used when the log carries no usage numbers.
# tiktoken is deliberately not a dependency yet (PRD lists it as fallback only).
_CHARS_PER_TOKEN = 4

# Assumed output length (tokens) when a record has neither usage nor response text.
DEFAULT_OUTPUT_TOKENS = 300


@dataclass(slots=True)
class LogRecord:
    """One LLM API call, normalized across ingest adapters."""

    model: str
    system_prompt: str | None = None
    first_user_message: str = ""
    response_text: str = ""
    timestamp: str | None = None
    input_tokens: int | None = None  # from provider usage when the log has it
    output_tokens: int | None = None
    task_hint: str | None = None  # harness-assigned task identity (Claude Code)
    source: str = ""
    # Full text conversation [{role, content}] when the log carries it; used by
    # replay. Adapters that can't afford to keep it inline (Claude Code) leave
    # this None and expose a lazy reconstruction path via meta.
    messages: list[dict[str, Any]] | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def est_input_tokens(self) -> int:
        if self.input_tokens is not None:
            return self.input_tokens
        chars = len(self.system_prompt or "") + len(self.first_user_message)
        return max(1, chars // _CHARS_PER_TOKEN)

    def est_output_tokens(self) -> int:
        if self.output_tokens is not None:
            return self.output_tokens
        if self.response_text:
            return max(1, len(self.response_text) // _CHARS_PER_TOKEN)
        return DEFAULT_OUTPUT_TOKENS
