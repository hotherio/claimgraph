"""L4: the ClaimGraph as an agent blackboard -- self-audit, refutation, and re-proof scheduling.

Many agents share one ClaimGraph. Builder agents post claims (``Depends-On`` edges and optimistic
statuses); a **self-audit / refuter agent** posts *findings* -- what the kernel actually reads (``#print
axioms`` out of module) -- and the graph turns each finding into its **blast radius**: the untouched
dependents whose *effective* status silently degrades because a prerequisite broke. A **scheduler** then
reads the regression set back as the re-proof curriculum. Nothing here is a new algorithm; it is the
coordination protocol assembled from the L3 primitives (``compute`` / ``affected`` / ``reproof_order``).
That is the point -- the graph is the shared medium through which one agent's refutation reaches the
claims another agent thought were done.

The worked demo (``main``) is the WeakPFR silent-contamination event measured in T4 / L2: twelve builder
commits assert the entropy-route WeakPFR strand machine-checked (a downstream corollary included); a
kernel audit finds seven of them silently rest on ``sorryAx`` after a module-system migration. Posting
those seven findings demotes the seven -- and, with no finding of its own, the corollary that rests on
them: the blast radius the reviewer never sees from the green build.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .build import _is_breaking, _values, build_graph, canonical, load_registry, read_fixture
from .curriculum import reproof_order, reproof_set
from .graph import compute
from .model import ClaimGraph


@dataclass
class Finding:
    """A refuter agent's kernel reading of one claim: the status it *actually* has, with a reason."""
    node: str
    status: str          # e.g. "math.open" for a silent sorryAx; a BROKEN status for a real refutation
    reason: str = ""


def post_findings(graph: ClaimGraph, findings: list[Finding]) -> set[str]:
    """A refuter posts findings to the shared graph: overwrite each named claim's working status with
    the kernel reading. Returns the ids whose status actually changed (the directly-refuted set)."""
    changed: set[str] = set()
    for f in findings:
        node = graph.node(f.node)
        if node.status != f.status:
            node.status = f.status
            changed.add(f.node)
    return changed


def run_audit(graph: ClaimGraph, findings: list[Finding]) -> dict[str, Any]:
    """The blackboard loop, mutating ``graph`` in place (it *is* the shared blackboard; deep-copy first
    if you need the pre-audit state). Snapshot effective statuses, let the refuter post its findings,
    recompute only the blast radius (the scoped recompute a re-proof loop wants), then report each
    claim's status transition and the prerequisites-first re-proof curriculum."""
    compute(graph)  # make sure pre-audit effective statuses are current
    before = {nid: (n.status, n.effective_status) for nid, n in graph.nodes.items()}
    changed = post_findings(graph, findings)
    scope = reproof_set(graph, changed)      # changed + everything transitively resting on them
    compute(graph, only=scope)               # scoped: recompute the blast radius, not the world
    transitions = []
    for nid in sorted(scope):
        n = graph.nodes[nid]
        _, b_eff = before.get(nid, (None, None))
        transitions.append({
            "node": nid,
            "directly_refuted": nid in changed,
            "before_effective": b_eff,
            "after_effective": n.effective_status,
            "weakest_dep": n.weakest_dep,
            "in_question": n.in_question,
        })
    return {
        "refuted": sorted(changed),                                   # posted by the refuter
        "collateral": sorted(nid for nid in scope if nid not in changed),  # blast radius, never refuted
        "blast_radius": sorted(scope),
        "reproof_order": reproof_order(graph, changed),               # the scheduler's re-proof curriculum
        "transitions": transitions,
    }


def findings_from_commits(commits: list[Any]) -> list[Finding]:
    """Read the refuter's findings out of the breaking commits in a history: each breaking commit names
    a claim (its scope) and the kernel status it regressed to (its ``Status:`` footer)."""
    findings: list[Finding] = []
    for c in commits:
        if not _is_breaking(c) or not c.scope:
            continue
        status = _values(c, "Status")
        if status:
            findings.append(Finding(node=canonical(c.scope), status=status[0], reason=c.description))
    return findings


def build_pre_audit(commits: list[Any], registry: dict[str, Any] | None) -> ClaimGraph:
    """The optimistic blackboard: the graph the builder agents left behind, before the audit -- built
    from the non-breaking commits only (every claim at its asserted, pre-regression status)."""
    return build_graph([c for c in commits if not _is_breaking(c)], registry)


def format_report(report: dict[str, Any]) -> str:
    lines = [
        f"refuter posted {len(report['refuted'])} findings: {', '.join(report['refuted'])}",
        f"blast radius: {len(report['blast_radius'])} claims "
        f"({len(report['collateral'])} collateral, never audited: {', '.join(report['collateral']) or 'none'})",
        "",
        f"{'claim':26s}{'before':>22s}{'after':>22s}  refuted?",
        "-" * 74,
    ]
    for t in report["transitions"]:
        lines.append(
            f"{t['node']:26s}{str(t['before_effective']):>22s}{str(t['after_effective']):>22s}"
            f"  {'yes' if t['directly_refuted'] else 'COLLATERAL'}"
        )
    lines += ["", "re-proof curriculum (prerequisites first): " + " -> ".join(report["reproof_order"])]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="L4 injected-refutation blackboard demo")
    ap.add_argument("commits", nargs="?", default="examples/weak-pfr/weak-pfr.commits")
    ap.add_argument("-c", "--claims", default="examples/weak-pfr/claims.toml")
    args = ap.parse_args(argv)
    commits = read_fixture(args.commits)
    registry = load_registry(args.claims) if Path(args.claims).exists() else None
    graph = build_pre_audit(commits, registry)          # optimistic: builders' green blackboard
    findings = findings_from_commits(commits)           # the refuter's kernel readings
    report = run_audit(graph, findings)
    print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
