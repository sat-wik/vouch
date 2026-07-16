#!/usr/bin/env python3
"""Vouch Phase 0 validation probe — THROWAWAY CODE.

Question (PRD §9, Phase 0 gate): do >=70% of my own Claude Code API calls
fall into <=15 coherent clusters a human would name the same way?

Deviation from the PRD's "system-prompt hash only": Claude Code transcripts
(~/.claude/projects/**/*.jsonl) do NOT log the system prompt. The harness
controls it, so calls are clustered by the closest by-construction proxy:
the role of the thread that produced the call —
  main agentic loop / sidechain agent type / slash command / compact.
Every `assistant` record = one API call.
"""

import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict


def load_records(path):
    recs = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return recs


def text_of(message):
    c = message.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(
            b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def classify_agent(first_text):
    t = first_text.strip()
    if t == "Warmup":
        return "agent:warmup"
    head = t[:200].lower()
    if head.startswith("explore"):
        return "agent:explore"
    if "implementation plan" in head or head.startswith("design"):
        return "agent:plan"
    return "agent:general"


def thread_root_key(rec, by_uuid):
    """Walk parentUuid links to the thread's initiating record."""
    seen = set()
    cur = rec
    while cur.get("parentUuid") and cur["parentUuid"] in by_uuid:
        if cur["uuid"] in seen:
            break
        seen.add(cur["uuid"])
        cur = by_uuid[cur["parentUuid"]]
    return cur


def turn_initiator_text(rec, by_uuid):
    """Nearest ancestor user record with real text (tool_results yield '')."""
    seen = set()
    cur = rec
    while cur.get("parentUuid") and cur["parentUuid"] in by_uuid:
        if cur["uuid"] in seen:
            break
        seen.add(cur["uuid"])
        cur = by_uuid[cur["parentUuid"]]
        if cur.get("type") == "user":
            t = text_of(cur.get("message", {})).strip()
            if t:
                return t
    return ""


def cluster_key(rec, by_uuid):
    """Returns (cluster_name, sample_text) — sample is the text the call was keyed on."""
    root = thread_root_key(rec, by_uuid)
    root_text = text_of(root.get("message", {})) if root.get("type") == "user" else ""
    if rec.get("isSidechain"):
        return classify_agent(root_text), root_text
    turn_text = turn_initiator_text(rec, by_uuid)
    cmd = re.search(r"<command-name>(/?[\w:-]+)</command-name>", turn_text)
    if cmd:
        return f"command:{cmd.group(1).lstrip('/')}", turn_text
    if root_text.startswith("This session is being continued"):
        return "main:compact-continuation", root_text
    return "main:agentic-loop", root_text


def main():
    base = os.path.expanduser("~/.claude/projects")
    files = sorted(glob.glob(f"{base}/**/*.jsonl", recursive=True))
    if not files:
        sys.exit(f"no transcripts under {base}")

    calls = []  # (cluster, project, model, session, root_text)
    timestamps = []
    for path in files:
        project = os.path.basename(os.path.dirname(path)).split("-")[-1]
        recs = load_records(path)
        by_uuid = {r["uuid"]: r for r in recs if "uuid" in r}
        for r in recs:
            if r.get("type") != "assistant":
                continue
            model = r.get("message", {}).get("model", "?")
            if model == "<synthetic>":
                continue
            key, sample = cluster_key(r, by_uuid)
            calls.append((key, project, model, r.get("sessionId"), sample))
            if r.get("timestamp"):
                timestamps.append(r["timestamp"])

    total = len(calls)
    clusters = defaultdict(list)
    for c in calls:
        clusters[c[0]].append(c)

    span = ""
    if timestamps:
        span = f", {min(timestamps)[:10]} → {max(timestamps)[:10]}"
    print(f"{len(clusters)} clusters from {total} API calls "
          f"({len(files)} transcripts{span})\n")

    hdr = f"{'#':>2}  {'cluster':<26} {'calls':>6}  {'share':>6}  {'model mix':<48} {'projects'}"
    print(hdr)
    print("-" * len(hdr))
    ranked = sorted(clusters.items(), key=lambda kv: -len(kv[1]))
    for i, (name, rows) in enumerate(ranked, 1):
        models = Counter(r[2] for r in rows)
        projects = Counter(r[1] for r in rows)
        proj_str = ", ".join(f"{p}({n})" for p, n in projects.most_common(3))
        model_str = ", ".join(f"{m}({n})" for m, n in models.most_common(3))
        print(f"{i:>2}  {name:<26} {len(rows):>6}  {len(rows)/total:>6.1%}  "
              f"{model_str:<48} {proj_str}")

    top15 = sum(len(rows) for _, rows in ranked[:15])
    print(f"\nGATE: top-{min(15, len(ranked))} clusters cover "
          f"{top15}/{total} calls = {top15/total:.1%} (need >=70%)")

    print("\n--- coherence check: sample thread-initiating prompts per cluster ---")
    for name, rows in ranked:
        print(f"\n[{name}]")
        seen = set()
        for r in rows:
            t = " ".join(r[4].split())[:120]
            if t and t not in seen:
                seen.add(t)
                print(f"  · {t}")
            if len(seen) >= 3:
                break


if __name__ == "__main__":
    main()
