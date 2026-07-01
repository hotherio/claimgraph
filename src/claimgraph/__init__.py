"""claimgraph: build and visualize the CKC ClaimGraph from git history."""
from __future__ import annotations

from .build import build_graph, load_registry, read_fixture, read_git
from .curriculum import (
    levels,
    reproof_order,
    reproof_set,
    schedule,
    topo_order,
    unlock_power,
)
from .emit import load
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
    "topo_order",
    "levels",
    "unlock_power",
    "schedule",
    "reproof_set",
    "reproof_order",
    "load",
    "__version__",
]


def build(
    repo: str = ".",
    *,
    fixture: str | None = None,
    claims: str | None = None,
) -> ClaimGraph:
    """High-level helper: read commits + registry, build, and compute the derived views."""
    commits = read_fixture(fixture) if fixture else read_git(repo)
    registry = load_registry(claims)
    return compute(build_graph(commits, registry))
