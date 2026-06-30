"""claimgraph: build and visualize the CKC ClaimGraph from git history."""
from __future__ import annotations

from .build import build_graph, load_registry, read_fixture, read_git
from .graph import affected, compute, status_report
from .model import ClaimGraph, Edge, Node

__version__ = "0.1.0"

__all__ = [
    "ClaimGraph",
    "Edge",
    "Node",
    "build_graph",
    "load_registry",
    "read_fixture",
    "read_git",
    "compute",
    "affected",
    "status_report",
    "build_view",
    "__version__",
]


def build_view(
    repo: str = ".",
    *,
    fixture: str | None = None,
    claims: str | None = None,
) -> ClaimGraph:
    """High-level helper: read commits + registry, build, and compute the derived views.

    Named ``build_view`` (not ``build``) so it never shadows the ``claimgraph.build``
    submodule. Prefer this over calling ``build_graph()`` directly: the latter leaves the
    derived fields (``effective_status``/``weakest_dep``/``in_question``) unset until
    ``compute()`` runs, which this helper does for you.
    """
    commits = read_fixture(fixture) if fixture else read_git(repo)
    registry = load_registry(claims)
    return compute(build_graph(commits, registry))
