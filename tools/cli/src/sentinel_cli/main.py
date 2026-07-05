"""
sentinel CLI — analyze Langfuse (and future source) traces for agent failures.

Usage:
    sentinel analyze --source langfuse --public-key PK --secret-key SK [--project-id ID]
    sentinel watch   --source langfuse --public-key PK --secret-key SK [--project-id ID]
    sentinel analyze ... --format json

Exit codes:
    0  No insights found
    1  One or more insights found (CI-safe)
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

import click
from rich.console import Console
from rich.table import Table

from sentinel_connectors.langfuse import LangfuseConnector
from sentinel_pipeline.graph.builder import build_graph
from sentinel_pipeline.models.insight import Insight, Severity, Tier
from sentinel_pipeline.detectors.runner import run_detectors

console = Console()

_CONNECTORS = {
    "langfuse": LangfuseConnector(),
}

_SEVERITY_COLORS = {
    Severity.INFO: "cyan",
    Severity.WARNING: "yellow",
    Severity.HIGH: "red",
    Severity.CRITICAL: "bold red",
}


@click.group()
def cli() -> None:
    """SentinelAI — detect failures in your agent traces."""


@cli.command()
@click.option("--source", required=True, type=click.Choice(["langfuse"]))
@click.option("--public-key", required=True, envvar="LANGFUSE_PUBLIC_KEY")
@click.option("--secret-key", required=True, envvar="LANGFUSE_SECRET_KEY")
@click.option("--base-url", default=None, envvar="LANGFUSE_BASE_URL")
@click.option("--project-id", default=None)
@click.option("--since-hours", default=24, show_default=True, help="Hours of traces to analyze")
@click.option("--format", "output_format", default="table", type=click.Choice(["table", "json"]))
def analyze(
    source: str,
    public_key: str,
    secret_key: str,
    base_url: str | None,
    project_id: str | None,
    since_hours: int,
    output_format: str,
) -> None:
    """Pull traces and run all detectors. Exit 1 if any insights are found."""
    config = _build_config(source, public_key, secret_key, base_url, project_id)
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    insights = _run_analysis(source, config, since)
    _output(insights, output_format)
    sys.exit(1 if insights else 0)


@cli.command()
@click.option("--source", required=True, type=click.Choice(["langfuse"]))
@click.option("--public-key", required=True, envvar="LANGFUSE_PUBLIC_KEY")
@click.option("--secret-key", required=True, envvar="LANGFUSE_SECRET_KEY")
@click.option("--base-url", default=None, envvar="LANGFUSE_BASE_URL")
@click.option("--project-id", default=None)
@click.option("--interval", default=60, show_default=True, help="Poll interval (seconds)")
@click.option("--format", "output_format", default="table", type=click.Choice(["table", "json"]))
def watch(
    source: str,
    public_key: str,
    secret_key: str,
    base_url: str | None,
    project_id: str | None,
    interval: int,
    output_format: str,
) -> None:
    """Continuously poll for new traces and print insights as they arrive."""
    import time

    config = _build_config(source, public_key, secret_key, base_url, project_id)
    since = datetime.now(timezone.utc) - timedelta(hours=1)

    console.print(f"[bold]Watching {source} traces every {interval}s.[/] Press Ctrl+C to stop.")
    try:
        while True:
            insights = _run_analysis(source, config, since)
            if insights:
                _output(insights, output_format)
            since = datetime.now(timezone.utc)  # only fetch new traces next iteration
            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/]")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_config(
    source: str,
    public_key: str,
    secret_key: str,
    base_url: str | None,
    project_id: str | None,
) -> dict:
    cfg: dict = {"public_key": public_key, "secret_key": secret_key}
    if base_url:
        cfg["base_url"] = base_url
    if project_id:
        cfg["project_id"] = project_id
    return cfg


def _run_analysis(source: str, config: dict, since: datetime) -> list[Insight]:
    connector = _CONNECTORS[source]
    all_insights: list[Insight] = []

    # Group spans by trace_id then process each trace
    traces: dict[str, list] = {}
    for batch in connector.pull(config, since=since, workspace_id="local"):
        for span in batch:
            traces.setdefault(span.trace_id, []).append(span)

    for trace_id, spans in traces.items():
        graph = build_graph(spans)
        insights = run_detectors(graph, workspace_tier=Tier.FREE)
        all_insights.extend(insights)

    return all_insights


def _output(insights: list[Insight], fmt: str) -> None:
    if fmt == "json":
        print(json.dumps([i.model_dump(mode="json") for i in insights], indent=2))
        return

    table = Table(title=f"{len(insights)} insight(s) found", show_lines=True)
    table.add_column("Severity", style="bold", no_wrap=True)
    table.add_column("Detector", style="dim")
    table.add_column("Trace ID", style="dim", no_wrap=True)
    table.add_column("Title", max_width=40)
    table.add_column("Recommendation", max_width=60)

    for insight in insights:
        color = _SEVERITY_COLORS.get(insight.severity, "white")
        table.add_row(
            f"[{color}]{insight.severity.value.upper()}[/{color}]",
            insight.detector_id,
            insight.trace_id[:16] + "…",
            insight.title,
            insight.recommendation,
        )

    console.print(table)
