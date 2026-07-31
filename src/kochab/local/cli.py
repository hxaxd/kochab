from __future__ import annotations

import json
from pathlib import Path

import typer

from kochab.local.export import export_pack
from kochab.local.state import State, diff as state_diff, init_state, rev

app = typer.Typer(
    no_args_is_help=True, add_completion=False,
    help="Version a local skill folder while your coding agent tunes it. Read the repository's SKILL.md.",
)


def _json(value) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, default=str, indent=2))


def _state(host: Path) -> State:
    state = State(host)
    state.check()
    return state


def _describe(state: State) -> dict:
    candidate = state.candidate()
    return {
        "host": str(state.host),
        "state": str(state.dir),
        "candidate": candidate,
        "accepted": rev(state, "refs/kochab/accepted"),
        "changed": candidate != rev(state, "refs/kochab/accepted^{tree}"),
    }


@app.command()
def init(host: Path = typer.Argument(..., exists=True, file_okay=False)):
    """Start or resume versioning; the skill folder itself is the candidate."""
    _json(_describe(init_state(host)))


@app.command()
def diff(host: Path = typer.Argument(..., exists=True, file_okay=False)):
    """Show the folder's changes relative to the accepted version."""
    typer.echo(state_diff(_state(host)) or "(no changes)")


@app.command()
def accept(host: Path = typer.Argument(..., exists=True, file_okay=False)):
    """Keep the current folder contents as the accepted version."""
    state = _state(host)
    accepted = state.accept()
    _json({"accepted": accepted, "candidate": rev(state, "refs/kochab/accepted^{tree}")})


@app.command()
def rollback(host: Path = typer.Argument(..., exists=True, file_okay=False)):
    """Discard this round's edits and restore the accepted version."""
    state = _state(host)
    state.rollback()
    _json({"rolled_back": True, "accepted": rev(state, "refs/kochab/accepted")})


@app.command()
def export(
    host: Path = typer.Argument(..., exists=True, file_okay=False),
    out: Path = typer.Option(..., "--out", help="New directory outside the skill folder."),
):
    """Export the accepted skill folder, cumulative patch and version manifest."""
    path = export_pack(_state(host), out)
    _json({"exported": str(path), "skill": str(path / "skill")})


def main() -> None:
    try:
        app()
    except (ValueError, OSError) as exc:
        typer.echo(json.dumps({"error": str(exc)}, ensure_ascii=False), err=True)
        raise SystemExit(1) from None
