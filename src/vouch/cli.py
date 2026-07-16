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

_VERDICT_ICONS = {"tie": "✅", "win": "⚠️ ", "loss": "❌", "error": "🟡"}


def _load_records(claude_code: bool, logs: Optional[Path]):
    if claude_code == (logs is not None):
        typer.echo("Pick exactly one source: --claude-code or --logs FILE", err=True)
        raise typer.Exit(2)
    records = load_claude_code() if claude_code else load_openai_jsonl(logs)
    if not records:
        typer.echo("No LLM calls found in the given source.", err=True)
        raise typer.Exit(1)
    return records


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
    records = _load_records(claude_code, logs)
    typer.echo(render_manifest(cluster_records(records), k=k))


@app.command()
def snapshot(
    cluster: Optional[str] = typer.Option(
        None, "--cluster", help="Cluster number (from `vouch analyze`) or name."
    ),
    claude_code: bool = typer.Option(False, "--claude-code"),
    logs: Optional[Path] = typer.Option(None, "--logs", exists=True),
    k: int = typer.Option(25, "-k", help="Representative prompts per snapshot."),
    list_: bool = typer.Option(False, "--list", help="List stored snapshots and exit."),
) -> None:
    """Freeze a cluster's baseline from logs. Zero API calls."""
    from .snapshot import snapshot_cluster
    from .store import Ledger

    ledger = Ledger()
    if list_:
        rows = ledger.list_snapshots()
        if not rows:
            typer.echo("No snapshots yet — run `vouch snapshot --cluster N` first.")
            return
        for i, r in enumerate(rows, 1):
            typer.echo(
                f"{i:>3}  {r['name']:<28} {r['items']:>4} items  "
                f"incumbent {r['incumbent']}  ({r['created_at']})"
            )
        return

    if cluster is None:
        typer.echo("Missing --cluster (number from `vouch analyze`, or name).", err=True)
        raise typer.Exit(2)
    records = _load_records(claude_code, logs)
    clusters = cluster_records(records)
    target = None
    if cluster.isdigit() and 1 <= int(cluster) <= len(clusters):
        target = clusters[int(cluster) - 1]
    else:
        target = next((c for c in clusters if c.name == cluster), None)
    if target is None:
        typer.echo(f"No cluster {cluster!r} — run `vouch analyze` to see them.", err=True)
        raise typer.Exit(1)

    source = "claude-code" if claude_code else str(logs)
    try:
        snapshot_cluster(ledger, target, source=source, k=k)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    snap = ledger.load_snapshot(target.name)
    typer.echo(
        f"Snapshotted {target.name!r}: {len(snap.items)} baseline prompts, "
        f"incumbent {snap.incumbent}."
    )
    if source == "claude-code":
        typer.echo(
            "note: Claude Code logs omit the harness system prompt, so replays are\n"
            "approximate — `vouch diff` will replay the baseline too for a fair judge."
        )


@app.command()
def diff(
    cluster: str = typer.Option(..., "--cluster", help="Snapshot number, name, or fingerprint."),
    model: Optional[str] = typer.Option(None, "--model", help="Candidate model."),
    prompt_file: Optional[Path] = typer.Option(
        None, "--prompt-file", help="Candidate system prompt (replaces production prompt).", exists=True
    ),
    judge: str = typer.Option(
        "claude-sonnet-4-6", "--judge", help="Judge model (must differ from baseline and candidate)."
    ),
    replay_baseline: Optional[bool] = typer.Option(
        None,
        "--replay-baseline/--no-replay-baseline",
        help="Also regenerate baseline outputs via API (default: on for claude-code snapshots).",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the cost confirmation."),
) -> None:
    """Replay a candidate config against a snapshot and blind-judge the outputs."""
    from .diff import plan_diff, run_diff
    from .store import Ledger

    if model is None and prompt_file is None:
        typer.echo("Give a candidate: --model and/or --prompt-file.", err=True)
        raise typer.Exit(2)

    ledger = Ledger()
    snap = ledger.load_snapshot(cluster)
    if snap is None:
        typer.echo(
            f"No snapshot {cluster!r} — run `vouch snapshot --cluster ...` first "
            "(`vouch snapshot --list` shows what exists).",
            err=True,
        )
        raise typer.Exit(1)

    if replay_baseline is None:
        replay_baseline = snap.source == "claude-code"

    try:
        plan = plan_diff(
            ledger,
            snap,
            candidate_model=model,
            system_override=prompt_file.read_text() if prompt_file else None,
            judge_model=judge,
            replay_baseline=replay_baseline,
        )
    except (ValueError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)

    typer.echo(
        f"{snap.name}: {len(plan.pending)} prompts to replay+judge "
        f"({len(plan.cached)} cached, free) · baseline {snap.incumbent} → "
        f"candidate {plan.candidate_model} · judge {judge}"
        + (" · baseline replayed too" if replay_baseline else "")
    )
    if not plan.pending:
        typer.echo("Everything is cached — no API calls needed.")
    else:
        cost = f"~${plan.est_cost:,.2f}" if plan.est_cost is not None else "unknown (unpriced model)"
        typer.echo(f"Estimated cost: {cost}")
        if not yes and not typer.confirm("Proceed?"):
            raise typer.Exit(0)

    result = run_diff(plan, ledger)
    counts = result.counts
    typer.echo(
        f"\n✅ {counts.get('tie', 0)} tie   ⚠️  {counts.get('win', 0)} win   "
        f"❌ {counts.get('loss', 0)} loss   🟡 {counts.get('error', 0)} error"
    )
    problems = [(h, v, r) for h, v, r in result.rows if v.startswith(("loss", "error"))]
    if problems:
        typer.echo("\nRegressions / errors:")
        for h, v, reason in problems:
            typer.echo(f"  {_VERDICT_ICONS.get(v.split()[0], '')} {h}  {reason or ''}")
    typer.echo("\nVerdicts recorded in ~/.vouch/ledger.db (`vouch ledger`).")


@app.command()
def ledger(
    cluster: Optional[str] = typer.Option(None, "--cluster", help="Snapshot number, name, or fingerprint."),
) -> None:
    """Show verdict history from the ledger."""
    from .store import Ledger

    led = Ledger()
    fingerprint = None
    if cluster:
        snap = led.load_snapshot(cluster)
        if snap is None:
            typer.echo(f"No snapshot {cluster!r}.", err=True)
            raise typer.Exit(1)
        fingerprint = snap.fingerprint
    rows = led.verdict_history(fingerprint)
    if not rows:
        typer.echo("No verdicts yet — run `vouch diff` first.")
        return
    for r in rows:
        icon = _VERDICT_ICONS.get(r["verdict"], "  ")
        delta = f"  Δ${r['cost_delta']:+.4f}" if r["cost_delta"] is not None else ""
        typer.echo(
            f"{r['created_at']}  {icon} {r['verdict']:<5}  "
            f"{r['cluster_fingerprint'][:12]}  {r['baseline_config_hash']}→"
            f"{r['candidate_config_hash']}  judge={r['judge_model']}{delta}"
            + (f"  {r['detail']}" if r["detail"] and r["verdict"] != "tie" else "")
        )


@app.command()
def capture(
    port: int = typer.Option(4141, "--port"),
    out: Optional[Path] = typer.Option(None, "--out", help="Capture file (default ~/.vouch/captured.jsonl)."),
) -> None:
    """Run the Tollgate capture proxy (observes traffic; never redirects)."""
    from . import capture as tollgate

    typer.echo(f"Tollgate listening on http://127.0.0.1:{port}")
    typer.echo(f"Capturing to {out or tollgate.default_capture_path()}")
    try:
        tollgate.run(port=port, capture_path=str(out) if out else None)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
