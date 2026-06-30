"""Build a kernel-grounded ClaimGraph from a built Lean repo, with no blueprint and no CKC history.

One node per project declaration; ``Depends-On`` edges from the real Lean dependency graph
(:mod:`leandeps`); a kernel reading per node from ``#print axioms`` (via ``axiom-report``). This is the
blueprint-less engine the SorryDB contamination pass shells out to: it turns any *built* Lean project
into ``{decl, Depends-On, kernel}``, so a declaration that is ``sorryAx`` while carrying no literal
``sorry`` in its own source is surfaced directly.

The composition (:func:`build_lean_graph`) is pure and unit-tested from saved reports; only
:func:`lean_graph_from_project` touches a live project.
"""
from __future__ import annotations

from pathlib import Path

from .blueprint import _KERNEL_STATUS, run_axiom_report
from .graph import compute
from .leandeps import _root_modules, extract_lean_deps
from .model import ClaimGraph, Edge


def build_lean_graph(
    deps: dict[str, list[str]],
    kernel: dict[str, str] | None = None,
) -> ClaimGraph:
    """Compose a kernel-grounded ClaimGraph from a raw dep report and optional kernel readings.

    Every declaration is a node; its direct project dependencies become ``Depends-On`` edges; the
    kernel reading (``clean`` / ``sorryAx`` / ``axiom`` -> machine-checked / open / axiomatised)
    becomes the node status. Pure: no Lean invocation.
    """
    g = ClaimGraph()
    for fqn in deps:
        n = g.node(fqn)
        n.lean = [fqn]
        n.kind = "declaration"
        if kernel and fqn in kernel:
            n.kernel = _KERNEL_STATUS.get(kernel[fqn])
            n.status = n.kernel
    seen: set[tuple[str, str]] = set()
    for fqn, ds in deps.items():
        for d in ds:
            if d in deps and d != fqn and (fqn, d) not in seen:
                seen.add((fqn, d))
                g.edges.append(Edge(source=fqn, target=d, relation="Depends-On"))
    return compute(g)


def lean_graph_from_project(
    project: str | Path,
    namespaces: list[str] | None = None,
    axiom_report: str | None = None,
) -> ClaimGraph | None:
    """Live path: probe a *built* project for its declarations / deps and kernel readings, then compose.

    Namespace prefixes default to the top-level ``*.lean`` module stems (the project's roots). Returns
    ``None`` if the project cannot be probed (not built, no ``lake``, wrong namespace).
    """
    project = Path(project)
    prefixes = namespaces or _root_modules(project)
    if not prefixes:
        return None
    # one probe discovers every decl under the prefixes (the names just set the namespace).
    deps = extract_lean_deps(project, [f"{p}._" for p in prefixes])
    if deps is None:
        return None
    kernel = run_axiom_report(project, names=sorted(deps), bin_path=axiom_report)
    return build_lean_graph(deps, kernel)
