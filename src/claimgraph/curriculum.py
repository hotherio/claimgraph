"""Dependency-DAG curriculum primitives over a ClaimGraph (L3).

Pure graph algorithms on the ``Depends-On`` / ``Assumes`` DAG: a leaves-first topological schedule
(prove foundations before the claims that rest on them), each node's unlocking-power (how many
downstream claims it unblocks), and the impact-scoped re-proof set on a change (reuse ``affected``).
No prover, no kernel calls -- everything is derived from the edges and the existing status labels,
exactly like the rest of ``graph.py``.

Edge convention (from ``graph.py``): ``source Depends-On target`` means *source rests on target*, so
``target`` is a prerequisite of ``source``. A curriculum "leaf" is a node with no in-graph prerequisite
(it rests only on external / Mathlib declarations, which are treated as given-clean and dropped from
the DAG). All primitives restrict to in-graph nodes, so an external dependency never blocks scheduling.
"""
from __future__ import annotations

import heapq

from .graph import _dependency_adjacency, affected
from .model import ClaimGraph


def _dag(graph: ClaimGraph) -> tuple[set[str], dict[str, set[str]], dict[str, set[str]]]:
    """``(node_ids, deps, rev)`` restricted to in-graph nodes.

    ``deps[x]`` = x's in-graph prerequisites; ``rev[x]`` = x's in-graph dependents. External targets
    (e.g. Mathlib) are dropped, so a decl resting only on external deps is a leaf.
    """
    node_ids = set(graph.nodes)
    adj = _dependency_adjacency(graph)
    deps = {nid: (adj.get(nid, set()) & node_ids) for nid in node_ids}
    rev: dict[str, set[str]] = {nid: set() for nid in node_ids}
    for x, ds in deps.items():
        for d in ds:
            rev[d].add(x)
    return node_ids, deps, rev


def dependencies(graph: ClaimGraph, nid: str) -> set[str]:
    """The in-graph claims ``nid`` directly Depends-On / Assumes (its prerequisites)."""
    _, deps, _ = _dag(graph)
    return deps.get(nid, set())


def dependents(graph: ClaimGraph, nid: str) -> set[str]:
    """The in-graph claims that directly Depend-On / Assume ``nid`` (rest on it)."""
    _, _, rev = _dag(graph)
    return rev.get(nid, set())


def detect_cycles(graph: ClaimGraph) -> list[str]:
    """Node ids left unresolved by Kahn's algorithm: they lie on a dependency cycle.

    Empty for a DAG (Lean graphs are acyclic; a non-empty result flags a malformed / reconciled graph).
    """
    node_ids, deps, rev = _dag(graph)
    indeg = {nid: len(deps[nid]) for nid in node_ids}
    ready = [nid for nid, d in indeg.items() if d == 0]
    resolved = 0
    while ready:
        x = ready.pop()
        resolved += 1
        for p in rev[x]:
            indeg[p] -= 1
            if indeg[p] == 0:
                ready.append(p)
    return sorted(nid for nid, d in indeg.items() if d > 0)


def topo_order(graph: ClaimGraph) -> list[str]:
    """Prerequisites-first topological order over ``Depends-On`` / ``Assumes``.

    Deterministic (ready nodes are drawn in id order). Raises ``ValueError`` on a dependency cycle.
    """
    node_ids, deps, rev = _dag(graph)
    indeg = {nid: len(deps[nid]) for nid in node_ids}
    ready = [nid for nid, d in indeg.items() if d == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        x = heapq.heappop(ready)
        order.append(x)
        for p in sorted(rev[x]):
            indeg[p] -= 1
            if indeg[p] == 0:
                heapq.heappush(ready, p)
    if len(order) != len(node_ids):
        raise ValueError(f"dependency cycle: {len(node_ids) - len(order)} nodes unresolved")
    return order


def levels(graph: ClaimGraph) -> dict[str, int]:
    """Longest-path depth per node (foundations = 0): the curriculum stage. Raises on a cycle."""
    _, deps, _ = _dag(graph)
    level: dict[str, int] = {}
    for x in topo_order(graph):
        level[x] = 0 if not deps[x] else 1 + max(level[d] for d in deps[x])
    return level


def unlock_power(graph: ClaimGraph, exact: bool = True) -> dict[str, int]:
    """Unlocking-power per node: the size of its reverse-dependency closure (downstream claims it
    unblocks). ``unlock_power(g)[x] == len(affected(g, x))``.

    ``exact`` uses a bitset DP in dependents-first order (O(V + E) big-int ops). ``exact=False`` returns
    the cheap direct-dependents count, a monotone proxy for very large graphs.
    """
    node_ids, _, rev = _dag(graph)
    if not exact:
        return {nid: len(rev[nid]) for nid in node_ids}
    order = topo_order(graph)  # prerequisites first
    idx = {nid: i for i, nid in enumerate(order)}
    desc: dict[str, int] = {}
    unlock: dict[str, int] = {}
    for x in reversed(order):  # dependents-first: every dependent of x is already done
        bits = 0
        for d in rev[x]:
            bits |= (1 << idx[d]) | desc[d]
        desc[x] = bits
        unlock[x] = bits.bit_count()
    return unlock


def ready_frontier(graph: ClaimGraph, done: set[str]) -> set[str]:
    """The claims whose entire in-graph prerequisite set is already ``done`` and are not done yet."""
    done = set(done)
    _, deps, _ = _dag(graph)
    return {nid for nid in graph.nodes if nid not in done and deps[nid] <= done}


def schedule(
    graph: ClaimGraph,
    done_seed: set[str] | None = None,
    tiebreak: str = "unlock",
) -> list[dict]:
    """A leaves-first curriculum schedule: expand the frontier as prerequisites complete.

    ``done_seed`` = claims already proven (excluded; their edges pre-satisfied). Empty = cold start from
    the genuine leaves. Among ready claims, ``tiebreak="unlock"`` proves the highest-unlocking-power one
    first (else id order). Returns one step dict per scheduled node:
    ``{order_index, node_id, effective_status, unlock, level, frontier_size}``. Raises on a cycle.
    """
    done = set(done_seed or ())
    node_ids, deps, rev = _dag(graph)
    unlock = unlock_power(graph) if tiebreak == "unlock" else {nid: 0 for nid in node_ids}
    level = levels(graph)
    indeg = {nid: len(deps[nid] - done) for nid in node_ids if nid not in done}
    heap = [(-unlock[nid], nid) for nid, d in indeg.items() if d == 0]
    heapq.heapify(heap)
    steps: list[dict] = []
    scheduled = set(done)
    while heap:
        frontier_size = len(heap)  # ready claims available before we pick one
        _, x = heapq.heappop(heap)
        node = graph.nodes.get(x)
        steps.append({
            "order_index": len(steps),
            "node_id": x,
            "effective_status": node.effective_status if node else None,
            "unlock": unlock[x],
            "level": level[x],
            "frontier_size": frontier_size,
        })
        scheduled.add(x)
        for p in rev[x]:
            if p in done or p not in indeg:
                continue
            indeg[p] -= 1
            if indeg[p] == 0:
                heapq.heappush(heap, (-unlock[p], p))
    remaining = node_ids - scheduled
    if remaining:
        raise ValueError(f"could not schedule {len(remaining)} nodes (dependency cycle)")
    return steps


def reproof_set(graph: ClaimGraph, changed: set[str]) -> set[str]:
    """The regression set of a change: the changed claims plus everything that transitively rests on
    them (reuse ``affected``). The complement is provably unaffected and can be skipped."""
    changed = set(changed)
    out = set(changed)
    for c in changed:
        out.update(affected(graph, c))
    return out & set(graph.nodes)


def reproof_order(graph: ClaimGraph, changed: set[str]) -> list[str]:
    """The regression set in prerequisites-first order: re-prove each claim after the deps inside the
    set it rests on."""
    scope = reproof_set(graph, changed)
    return [n for n in topo_order(graph) if n in scope]


def induced_subgraph(graph: ClaimGraph, ids: set[str]) -> ClaimGraph:
    """The subgraph on ``ids`` (node objects shared as views; edges with both ends in ``ids``)."""
    ids = set(ids)
    sub = ClaimGraph()
    for nid in ids:
        if nid in graph.nodes:
            sub.nodes[nid] = graph.nodes[nid]
    for e in graph.edges:
        if e.source in ids and e.target in ids:
            sub.edges.append(e)
    return sub
