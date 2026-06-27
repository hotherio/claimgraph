"""claimgraph command-line interface."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from . import blueprint as bp
from . import build as build_view
from .build import canonical, load_registry, read_git
from .emit import to_dict, to_json
from .graph import affected as compute_affected
from .graph import status_report
from .reconcile import audit as audit_graph
from .reconcile import compute_agreement, reconcile

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
    timeline: bool = typer.Option(
        False, "--timeline", "-t",
        help="Also emit a per-commit replay timeline in meta.timeline (for the viewer's time slider).",
    ),
) -> None:
    """Reconstruct the ClaimGraph and emit claimgraph.json."""
    graph = _load(repo, fixture, claims)
    frames = None
    if timeline:
        from .build import read_fixture_dated, read_git_dated
        from .timeline import build_timeline
        dated = read_fixture_dated(fixture) if fixture else read_git_dated(repo)
        frames = build_timeline(dated, load_registry(claims))
    payload = to_json(graph, timeline=frames)
    if out:
        out.write_text(payload + "\n", encoding="utf-8")
        extra = f", {len(frames)} frames" if frames else ""
        typer.echo(f"wrote {out}  ({len(graph.nodes)} nodes, {len(graph.edges)} edges{extra})")
    else:
        typer.echo(payload)


@app.command()
def export(
    repo: str = RepoArg,
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Write the standalone HTML here."),
    fixture: Optional[str] = FixtureOpt,
    claims: Optional[str] = ClaimsOpt,
    shape: str = typer.Option(
        "page", "--shape",
        help="page (self-contained file), fragment (paste-in <iframe>), or branded (page + CKC chrome).",
    ),
    title: Optional[str] = typer.Option(None, "--title", help="Title shown in the viewer."),
    no_timeline: bool = typer.Option(
        False, "--no-timeline", help="Omit the commit-replay timeline (graph + final state only).",
    ),
) -> None:
    """Export a self-contained HTML viewer (ClaimGraph + commit-history timeline) from a CKC repo."""
    from . import export_html
    if shape not in export_html.SHAPES:
        typer.secho(f"unknown --shape {shape!r} (one of {', '.join(export_html.SHAPES)})",
                    fg=typer.colors.RED)
        raise typer.Exit(code=2)
    graph = _load(repo, fixture, claims)
    frames = None
    if not no_timeline:
        from .build import read_fixture_dated, read_git_dated
        from .timeline import build_timeline
        dated = read_fixture_dated(fixture) if fixture else read_git_dated(repo)
        frames = build_timeline(dated, load_registry(claims))
    payload = to_dict(graph, timeline=frames)
    name = title or ("ClaimGraph" if fixture else Path(repo).resolve().name)
    html_str = export_html.render(payload, shape=shape, title=name)
    if out:
        out.write_text(html_str, encoding="utf-8")
        extra = f", {len(frames)} frames" if frames else ""
        typer.echo(f"wrote {out}  ({len(graph.nodes)} nodes{extra}, shape={shape})")
    else:
        typer.echo(html_str)


@app.command()
def status(
    repo: str = RepoArg,
    fixture: Optional[str] = FixtureOpt,
    claims: Optional[str] = ClaimsOpt,
) -> None:
    """Group claims by effective status."""
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
    typer.secho(f"affected by {target} ({len(dependents)}):", bold=True)
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


# --- Lean Blueprint integration -------------------------------------------------------------------

ProjectOpt = typer.Option(None, "--project", "-p", help="Lean project dir (to ground via #print axioms).")
AxiomReportOpt = typer.Option(None, "--axiom-report", help="Path to the axiom-report binary.")
AxiomsFileOpt = typer.Option(None, "--axioms", help="A saved axiom-report output to ground against.")


def _ground(tex: str, project: Optional[str], axiom_report: Optional[str], axioms_file: Optional[str]):
    nodes = bp.read_blueprint(tex)
    if axioms_file:
        kernel = bp.parse_axiom_report(Path(axioms_file).read_text(encoding="utf-8"))
    else:
        tex_arg = tex if str(tex).endswith(".tex") else None
        names = None if tex_arg else [f for n in nodes for f in n.lean]
        kernel = bp.run_axiom_report(project, tex_arg, names, axiom_report)
    return bp.blueprint_graph(nodes, kernel), kernel


_GAP_COLOR = {
    "kernel-refutes-claim": typer.colors.RED,     # a real validity gap
    "blueprint-incomplete": typer.colors.YELLOW,  # a coverage warning, not a validity gap
}


def _print_agreement(graph) -> int:
    groups: dict[str, list] = {}
    for n in graph.nodes.values():
        groups.setdefault(n.agreement or "?", []).append(n)
    gaps = 0
    for cat in sorted(groups):
        nodes = sorted(groups[cat], key=lambda n: n.id)
        typer.secho(f"{cat}  ({len(nodes)})", bold=True, fg=_GAP_COLOR.get(cat))
        for n in nodes:
            via = (f"  uses unformalized {n.uses_gap}"
                   if (cat == "blueprint-incomplete" and n.uses_gap) else "")
            typer.echo(f"    {n.id}  [claimed={n.claimed} asserted={n.asserted} kernel={n.kernel}"
                       f" → effective={n.effective_status}]{via}")
        if cat == "kernel-refutes-claim":  # only validity gaps are honesty failures
            gaps += len(nodes)
    return gaps


@app.command()
def blueprint(
    tex: str = typer.Argument(..., help="Blueprint content.tex (or LeanArchitect blueprintJson)."),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Write claimgraph.json here."),
    project: Optional[str] = ProjectOpt,
    axiom_report: Optional[str] = AxiomReportOpt,
    axioms_file: Optional[str] = AxiomsFileOpt,
) -> None:
    """Import a Lean Blueprint as a ClaimGraph, grounding \\leanok against #print axioms."""
    graph, kernel = _ground(tex, project, axiom_report, axioms_file)
    compute_agreement(graph, with_commits=False)
    if kernel is None:
        typer.secho("note: kernel grounding unavailable (no axiom-report); using \\leanok claims.",
                    fg=typer.colors.YELLOW, err=True)
    payload = to_json(graph, sources=["blueprint"] + (["kernel"] if kernel else []))
    if out:
        out.write_text(payload + "\n", encoding="utf-8")
        typer.echo(f"wrote {out}  ({len(graph.nodes)} nodes, {len(graph.edges)} edges)")
    else:
        typer.echo(payload)


def reconcile_cmd(
    tex: str = typer.Argument(..., help="Blueprint content.tex (or blueprintJson)."),
    repo: str = typer.Argument(".", help="Git repo with the CKC commit history."),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Write claimgraph.json here."),
    fixture: Optional[str] = FixtureOpt,
    claims: Optional[str] = ClaimsOpt,
    project: Optional[str] = ProjectOpt,
    axiom_report: Optional[str] = AxiomReportOpt,
    axioms_file: Optional[str] = AxiomsFileOpt,
) -> None:
    """Reconcile a blueprint, the commit history, and the kernel; report where they disagree."""
    from .build import build_graph, read_fixture
    bp_graph, kernel = _ground(tex, project, axiom_report, axioms_file)
    commits = read_fixture(fixture) if fixture else read_git(repo)
    commit_graph = build_graph(commits, load_registry(claims))
    graph = reconcile(bp_graph, commit_graph)
    compute_agreement(graph, with_commits=True)
    if out:
        srcs = ["blueprint", "commits"] + (["kernel"] if kernel else [])
        out.write_text(to_json(graph, sources=srcs) + "\n", encoding="utf-8")
        typer.echo(f"wrote {out}  ({len(graph.nodes)} nodes, {len(graph.edges)} edges)")
    _print_agreement(graph)


app.command(name="reconcile")(reconcile_cmd)


@app.command()
def audit(
    tex: str = typer.Argument(..., help="Blueprint content.tex (or blueprintJson)."),
    repo: Optional[str] = typer.Option(None, "--repo", help="Also reconcile against this repo's commits."),
    strict: bool = typer.Option(
        False, "--strict", help="Also fail on blueprint-incomplete (uses unformalized concepts)."
    ),
    fixture: Optional[str] = FixtureOpt,
    claims: Optional[str] = ClaimsOpt,
    project: Optional[str] = ProjectOpt,
    axiom_report: Optional[str] = AxiomReportOpt,
    axioms_file: Optional[str] = AxiomsFileOpt,
) -> None:
    """Honesty gate: fail if a claim is shown proved but the kernel refutes it (a validity gap).

    With --strict, also fail on coverage gaps (blueprint-incomplete: a machine-checked claim whose
    \\uses closure includes an unformalized concept).
    """
    bp_graph, _ = _ground(tex, project, axiom_report, axioms_file)
    if repo or fixture:
        from .build import build_graph, read_fixture
        commits = read_fixture(fixture) if fixture else read_git(repo)
        graph = reconcile(bp_graph, build_graph(commits, load_registry(claims)))
        compute_agreement(graph, with_commits=True)
    else:
        graph = compute_agreement(bp_graph, with_commits=False)
    gaps = audit_graph(graph, strict=strict)
    if not gaps:
        msg = "ok: no honesty gaps" + (" or coverage gaps" if strict else "") + "."
        typer.secho(msg, fg=typer.colors.GREEN)
        raise typer.Exit()
    typer.secho(f"{len(gaps)} gap(s):", bold=True, fg=typer.colors.RED)
    for n in gaps:
        if n.agreement == "kernel-refutes-claim":
            typer.echo(f"    {n.agreement}: {n.id}  (claimed proved, kernel says {n.kernel})")
        else:
            via = f"  ← {n.uses_gap}" if n.uses_gap else ""
            typer.echo(f"    {n.agreement}: {n.id}  (machine-checked, but uses an unformalized concept){via}")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
