"""Prompt normalization: static masking + cross-call template-slot detection (PRD §4)."""

from __future__ import annotations

import re
from collections import Counter

SLOT = "<var>"

_STATIC_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
        ),
        "<uuid>",
    ),
    (
        re.compile(
            r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?\b"
        ),
        "<ts>",
    ),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}\b"), "<date>"),
    (re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm|AM|PM)?\b"), "<time>"),
    (re.compile(r"\b[0-9a-fA-F]{16,}\b"), "<hex>"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "<email>"),
    (re.compile(r"\b\d{5,}\b"), "<num>"),
]


def mask_static(text: str) -> str:
    """Mask values recognizable without cross-call context: timestamps, UUIDs, etc."""
    for pattern, repl in _STATIC_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def detect_templates(texts: list[str], threshold: float = 0.3) -> list[str]:
    """Turn each text into a template by masking cross-call variable tokens.

    Texts are whitespace-tokenized and grouped by token count (same shape).
    Within a group, a position whose values vary across more than `threshold`
    of the calls is a template slot and is replaced with SLOT. Returns one
    template per input, in order. Whitespace is normalized to single spaces —
    templates are cluster identities, not display text.
    """
    tokenized = [t.split() for t in texts]
    by_shape: dict[int, list[int]] = {}
    for i, toks in enumerate(tokenized):
        by_shape.setdefault(len(toks), []).append(i)

    templates = [" ".join(toks) for toks in tokenized]
    for shape, idxs in by_shape.items():
        if len(idxs) < 2 or shape == 0:
            continue
        group = [tokenized[i] for i in idxs]
        slot_positions = set()
        for pos in range(shape):
            values = [toks[pos] for toks in group]
            # A position is a slot when more than `threshold` of the calls
            # deviate from its most common value (PRD §4: "tokens that vary
            # across >N% of calls"). Cardinality alone is not the signal — a
            # slot with 4 possible values across 1000 calls is still a slot.
            modal_count = max(Counter(values).values())
            if len(values) - modal_count > threshold * len(values):
                slot_positions.add(pos)
        for i in idxs:
            toks = list(tokenized[i])
            for pos in slot_positions:
                toks[pos] = SLOT
            templates[i] = " ".join(toks)
    return templates
