from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from .cluster import cluster_records
from .ingest import load_claude_code, load_openai_jsonl
from .manifest import render_manifest

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="A regression suite for your LLM calls that writes itself from production traffic.",
)


@app.command()
def analyze(
    claude_code: bool = typer.Option(
        False, "--claude-code", help="Read Claude Code transcripts (~/.claude/projects)."
    ),
    logs: Optional[Path] = typer.Option(
        None, "--logs", help="OpenAI-format request/response JSONL file.", exists=True
    ),
    k: int = typer.Option(25, "-k", help="Snapshot sample size used for cost estimates."),
) -> None:
    """Cluster your LLM calls into tasks and print the manifest. Zero network calls."""
    if claude_code == (logs is not None):
        typer.echo("Pick exactly one source: --claude-code or --logs FILE", err=True)
        raise typer.Exit(2)

    records = load_claude_code() if claude_code else load_openai_jsonl(logs)
    if not records:
        typer.echo("No LLM calls found in the given source.", err=True)
        raise typer.Exit(1)

    typer.echo(render_manifest(cluster_records(records), k=k))


def _phase2_stub(name: str) -> None:
    typer.echo(f"`vouch {name}` is not built yet — it lands in Phase 2 (see vouch-prd.md §9).", err=True)
    raise typer.Exit(1)


@app.command()
def snapshot() -> None:
    """Freeze baselines from logs. (Phase 2)"""
    _phase2_stub("snapshot")


@app.command()
def diff() -> None:
    """Replay + judge a candidate config against a baseline. (Phase 2)"""
    _phase2_stub("diff")


@app.command()
def capture() -> None:
    """Run the Tollgate capture proxy. (Phase 2)"""
    _phase2_stub("capture")


@app.command()
def ledger() -> None:
    """Show verdict history. (Phase 2)"""
    _phase2_stub("ledger")


if __name__ == "__main__":
    app()
