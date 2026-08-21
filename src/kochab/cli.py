from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import typer

from kochab.core.llm import OpenAICompat
from kochab.daemon import run_daemon as run_daemon_loop
from kochab.discovery import discover_host
from kochab.export import export_pack
from kochab.locking import HostLock
from kochab.onboarding import onboard_host
from kochab.round import execute_round
from kochab.session import open_session

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="kochab: tune a host harness from eval and traces.",
)


def _make_llm(
    *,
    model: str | None,
    base_url: str | None = None,
) -> OpenAICompat:
    resolved_model = model or os.environ.get("OPENAI_MODEL")
    if not resolved_model:
        raise typer.BadParameter("pass --model or set OPENAI_MODEL")
    return OpenAICompat(
        model=resolved_model,
        api_key=os.environ.get("OPENAI_API_KEY"),
        base_url=base_url or os.environ.get("OPENAI_BASE_URL"),
    )


def _on_event(kind: str, payload: object) -> None:
    if kind != "tool" or not isinstance(payload, dict):
        return
    name = payload.get("name") or "?"
    preview = str(payload.get("content") or "").replace("\n", " ")[:160]
    typer.echo(f"  {name}: {preview}")


@app.command("run")
def run_round(
    host: Path = typer.Argument(..., exists=True, file_okay=False, help="Host directory with kochab-host.yaml"),
    model: Optional[str] = typer.Option(None, help="OpenAI-compatible model id"),
    max_steps: int = typer.Option(40),
    base_url: Optional[str] = typer.Option(None),
) -> None:
    """One autonomous evolution round on the work copy."""
    session = open_session(host, require_frozen=True)
    llm = _make_llm(
        model=model,
        base_url=base_url,
    )
    with HostLock(session.state.dir):
        result = execute_round(session, llm, max_steps=max_steps, on_event=_on_event)
    typer.echo(result.reason)
    if result.outcome:
        typer.echo(result.outcome)
    typer.echo(f"state: {session.state.dir}")
    if not result.outcome:
        raise typer.Exit(1)


@app.command()
def discover(
    host: Path = typer.Argument(..., exists=True, file_okay=False),
    out: Optional[Path] = typer.Option(None, help="Binding draft path"),
    model: Optional[str] = typer.Option(None),
    base_url: Optional[str] = typer.Option(None),
    max_steps: int = typer.Option(30),
) -> None:
    """Use a read-only agent to draft the three host contracts."""
    result = discover_host(
        host,
        _make_llm(
            model=model,
            base_url=base_url,
        ),
        out=out,
        max_steps=max_steps,
        on_event=_on_event,
    )
    typer.echo(result.reason)
    if not result.outcome:
        raise typer.Exit(1)


@app.command()
def export(
    host: Path = typer.Argument(..., exists=True, file_okay=False),
    out: Path = typer.Option(..., help="Directory for the evolution package"),
) -> None:
    """Write an evolution package from the last accepted version."""
    typer.echo(str(export_pack(host, out, require_frozen=True)))


@app.command()
def gate(
    host: Path = typer.Argument(..., exists=True, file_okay=False),
) -> None:
    """Run the frozen holdout gate. Not exposed to the evolution model."""
    session = open_session(host, require_frozen=True)
    report = session.gate.check(session.host.surface.head())
    typer.echo(report)
    raise typer.Exit(0 if report["passed"] else 1)


@app.command()
def onboard(
    host: Path = typer.Argument(..., exists=True, file_okay=False),
    freeze: bool = typer.Option(False, "--freeze", help="Seal the validated binding for evolution"),
    reset_state: bool = typer.Option(
        False,
        "--reset-state",
        help="Back up .kochab and initialize a fresh work copy",
    ),
) -> None:
    """Exercise all three ports and optionally freeze the host binding."""
    report = onboard_host(host, freeze=freeze, reset_state=reset_state)
    typer.echo(report.model_dump_json(indent=2))


@app.command()
def daemon(
    host: Path = typer.Argument(..., exists=True, file_okay=False),
    model: Optional[str] = typer.Option(None),
    base_url: Optional[str] = typer.Option(None),
    once: bool = typer.Option(False, help="Process the current trace backlog and exit"),
    poll_seconds: float = typer.Option(5.0),
    max_steps: int = typer.Option(40),
    otlp_host: str = typer.Option("127.0.0.1", help="OTLP/HTTP listen address; empty disables receiver"),
    otlp_port: int = typer.Option(4318),
) -> None:
    """Watch OTLP traces and start evolution rounds for new failure evidence."""
    results = run_daemon_loop(
        host,
        lambda: _make_llm(
            model=model,
            base_url=base_url,
        ),
        once=once,
        poll_seconds=poll_seconds,
        max_steps=max_steps,
        on_event=_on_event,
        otlp_host=otlp_host or None,
        otlp_port=otlp_port,
    )
    typer.echo(f"rounds: {len(results)}")
