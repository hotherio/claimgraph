"""Computed views over a ClaimGraph: effective status, in-question, blast radius.

Everything here is derived from the edges, never stored, exactly as the spec says. The dependency
closure is taken over ``Depends-On`` / ``Assumes`` edges only; the other relations are events.
"""
from __future__ import annotations

from .model import (
    BROKEN,
    COVERAGE_RELATIONS,
    DEPENDENCY_RELATIONS,
    ClaimGraph,
    Node,
    status_key,
)


def _adjacency(graph: ClaimGraph, relations: frozenset[str]) -> dict[str, set[str]]:
    """node id -> the set of nodes it points to over the given relations."""
    adj: dict[str, set[str]] = {nid: set() for nid in graph.nodes}
    for edge in graph.edges:
        if edge.relation in relations:
            adj.setdefault(edge.source, set()).add(edge.target)
            adj.setdefault(edge.target, set())  # ensure target is a known key
    return adj


def _dependency_adjacency(graph: ClaimGraph) -> dict[str, set[str]]:
    """node id -> the set of nodes it directly Depends-On / Assumes."""
    return _adjacency(graph, DEPENDENCY_RELATIONS)


def _closure(start: str, adj: dict[str, set[str]]) -> set[str]:
    """All nodes reachable from ``start`` over dependency edges, excluding ``start`` itself."""
    seen: set[str] = set()
    stack = list(adj.get(start, ()))
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(adj.get(cur, ()) - seen)
    seen.discard(start)
    return seen


def compute(graph: ClaimGraph) -> ClaimGraph:
    """Fill in ``effective_status``, ``weakest_dep`` and ``in_question`` for every node."""
    adj = _dependency_adjacency(graph)
    for nid, node in graph.nodes.items():
        closure = _closure(nid, adj)

        # effective status = the weakest status across {self} ∪ dependency closure. A *broken*
        # dependency does not drag the ladder down to "disproved"; it raises the in-question flag
        # instead (below). So broken deps are skipped here.
        weakest_id, weakest_status = nid, node.status
        for dep_id in closure:
            dep = graph.nodes.get(dep_id)
            dep_status = dep.status if dep else None
            if dep_status in BROKEN:
                continue
            if status_key(dep_status) < status_key(weakest_status):
                weakest_id, weakest_status = dep_id, dep_status
        node.effective_status = weakest_status
        node.weakest_dep = weakest_id if weakest_id != nid else None

        # in question: not itself broken, but some dependency is broken.
        node.in_question = not node.broken and any(
            (graph.nodes.get(d).status if graph.nodes.get(d) else None) in BROKEN
            for d in closure
        )
    return graph


def compute_coverage(graph: ClaimGraph) -> ClaimGraph:
    """Fill in ``blueprint_complete`` / ``uses_gap`` for every node.

    Coverage is *blueprint completeness* (is every concept a claim ``\\uses`` modelled in Lean), which
    is orthogonal to validity (the kernel / ``Depends-On`` closure). A node is "modelled" iff it has a
    Lean FQN; a prose-only used node (no ``\\lean``) makes its users coverage-incomplete. This never
    touches a node's validity ``effective_status`` -- a kernel-clean theorem stays machine-checked
    even when it ``\\uses`` an unformalized definition.
    """
    adj = _adjacency(graph, COVERAGE_RELATIONS)
    for nid, node in graph.nodes.items():
        if not node.lean:  # not a formalized claim; coverage does not apply
            node.blueprint_complete = None
            node.uses_gap = None
            continue
        unformalized = sorted(
            d for d in _closure(nid, adj) if d in graph.nodes and not graph.nodes[d].lean
        )
        node.blueprint_complete = not unformalized
        node.uses_gap = unformalized[0] if unformalized else None
    return graph


def affected(graph: ClaimGraph, target: str) -> list[str]:
    """Nodes that Depend-On ``target`` (transitively): the dependents a refutation puts in question."""
    adj = _dependency_adjacency(graph)
    # reverse the dependency edges, then forward-reach from target.
    reverse: dict[str, set[str]] = {nid: set() for nid in adj}
    for src, targets in adj.items():
        for tgt in targets:
            reverse.setdefault(tgt, set()).add(src)
    return sorted(_closure(target, reverse))


def status_report(graph: ClaimGraph) -> dict[str, list[Node]]:
    """Group nodes by effective status."""
    groups: dict[str, list[Node]] = {}
    for node in graph.nodes.values():
        key = node.effective_status or "unset"
        groups.setdefault(key, []).append(node)
    for nodes in groups.values():
        nodes.sort(key=lambda n: n.id)
    return groups
