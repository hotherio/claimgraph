"""claimgraph command-line interface."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from . import build as build_view
from .build import canonical
from .emit import to_json
from .graph import affected as compute_affected
from .graph import status_report

app = typer.Typer(
    add_completion=False,
    help="Build and visualize the Conventional Knowledge Commits (CKC) ClaimGraph.",
    no_args_is_help=True,
)

# Shared options.
RepoArg = typer.Argument(".", help="Path to the git repository to read commits from.")
FixtureOpt = typer.Option(
    None, "--from-fixture", "-f", help="Read commits from a fixture file instead of git."
)
ClaimsOpt = typer.Option(
    None, "--claims", "-c", help="Path to claims.toml for statements and kinds."
)


def _load(repo: str, fixture: Optional[str], claims: Optional[str]):
    return build_view(repo, fixture=fixture, claims=claims)


@app.command()
def build(
    repo: str = RepoArg,
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Write claimgraph.json here."),
    fixture: Optional[str] = FixtureOpt,
    claims: Optional[str] = ClaimsOpt,
) -> None:
    """Reconstruct the ClaimGraph and emit claimgraph.json."""
    graph = _load(repo, fixture, claims)
    payload = to_json(graph)
    if out:
        out.write_text(payload + "\n", encoding="utf-8")
        typer.echo(f"wrote {out}  ({len(graph.nodes)} nodes, {len(graph.edges)} edges)")
    else:
        typer.echo(payload)


@app.command()
def status(
    repo: str = RepoArg,
    fixture: Optional[str] = FixtureOpt,
    claims: Optional[str] = ClaimsOpt,
) -> None:
    """Group claims by effective status — the honest project dashboard."""
    graph = _load(repo, fixture, claims)
    report = status_report(graph)
    for key in sorted(report):
        nodes = report[key]
        typer.secho(f"{key}  ({len(nodes)})", bold=True)
        for n in nodes:
            flags = " [in question]" if n.in_question else ""
            via = f"  ← {n.weakest_dep}" if n.weakest_dep else ""
            typer.echo(f"    {n.id}{via}{flags}")


@app.command()
def affected(
    claim: str = typer.Argument(..., help="The claim id (or footer ref) to test."),
    repo: str = RepoArg,
    fixture: Optional[str] = FixtureOpt,
    claims: Optional[str] = ClaimsOpt,
) -> None:
    """List the claims a refutation of CLAIM would put in question (its dependents)."""
    graph = _load(repo, fixture, claims)
    target = canonical(claim)
    dependents = compute_affected(graph, target)
    if not dependents:
        typer.echo(f"{target}: nothing depends on it.")
        raise typer.Exit()
    typer.secho(f"{target} — affected claims ({len(dependents)}):", bold=True)
    for dep in dependents:
        typer.echo(f"    {dep}")


@app.command()
def effective(
    claim: str = typer.Argument(..., help="The claim id (or footer ref) to inspect."),
    repo: str = RepoArg,
    fixture: Optional[str] = FixtureOpt,
    claims: Optional[str] = ClaimsOpt,
) -> None:
    """Show a claim's asserted vs effective status and the weakest dependency that set it."""
    graph = _load(repo, fixture, claims)
    target = canonical(claim)
    node = graph.nodes.get(target)
    if node is None:
        typer.secho(f"unknown claim: {target}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    typer.secho(target, bold=True)
    typer.echo(f"    asserted:  {node.status}")
    typer.echo(f"    effective: {node.effective_status}")
    if node.weakest_dep:
        typer.echo(f"    weakest dependency: {node.weakest_dep}")
    if node.in_question:
        typer.secho("    in question (a dependency is broken)", fg=typer.colors.YELLOW)


if __name__ == "__main__":
    app()
