"""Fingerprint clustering and auto-naming (PRD §4)."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field

from .models import LogRecord
from .normalize import detect_templates, mask_static

_STOPWORDS = frozenset(
    "a an the and or of to in on for with is are be as that this you your "
    "will should must always never please".split()
)
_LEADING_BOILERPLATE = re.compile(
    r"^(you are|you're|act as|your (task|job|role) is( to)?|i want you to)\s+",
    re.IGNORECASE,
)


@dataclass(slots=True)
class Cluster:
    fingerprint: str
    name: str
    template: str
    records: list[LogRecord] = field(default_factory=list)

    @property
    def calls(self) -> int:
        return len(self.records)

    @property
    def incumbent(self) -> str:
        return Counter(r.model for r in self.records).most_common(1)[0][0]

    def model_mix(self) -> Counter[str]:
        return Counter(r.model for r in self.records)


def auto_name(template: str) -> str:
    """Human-readable name from the identity text's first clause."""
    clause = re.split(r"[.:;\n]", template.strip(), maxsplit=1)[0]
    clause = _LEADING_BOILERPLATE.sub("", clause)
    words = [
        w
        for w in re.findall(r"[a-zA-Z][a-zA-Z0-9'-]*", clause.lower())
        if w not in _STOPWORDS
    ]
    return "_".join(words[:4]) or "cluster"


def cluster_records(records: list[LogRecord]) -> list[Cluster]:
    """Group calls into task clusters, largest first.

    Records with a task_hint (harness-controlled logs, e.g. Claude Code) are
    clustered by the hint. Others are clustered by fingerprint of the
    normalized system prompt (or first user message when there is none).
    """
    hinted: dict[str, list[LogRecord]] = {}
    prompted: list[LogRecord] = []
    for rec in records:
        if rec.task_hint:
            hinted.setdefault(rec.task_hint, []).append(rec)
        else:
            prompted.append(rec)

    clusters: list[Cluster] = [
        Cluster(fingerprint=f"hint:{hint}", name=hint, template=hint, records=recs)
        for hint, recs in hinted.items()
    ]

    if prompted:
        identities = [
            mask_static(r.system_prompt or r.first_user_message) for r in prompted
        ]
        templates = detect_templates(identities)
        by_fp: dict[str, Cluster] = {}
        for rec, template in zip(prompted, templates):
            fp = hashlib.sha256(template.encode()).hexdigest()[:16]
            if fp not in by_fp:
                by_fp[fp] = Cluster(fingerprint=fp, name="", template=template)
            by_fp[fp].records.append(rec)
        clusters.extend(by_fp.values())

    # Assign names after clustering so duplicates can be disambiguated.
    seen: Counter[str] = Counter()
    for c in sorted(clusters, key=lambda c: -c.calls):
        if not c.name:
            c.name = auto_name(c.template)
        seen[c.name] += 1
        if seen[c.name] > 1:
            c.name = f"{c.name}_{seen[c.name]}"

    return sorted(clusters, key=lambda c: -c.calls)
