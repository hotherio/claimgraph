"""Serialize a computed ClaimGraph to the schema-conformant claimgraph.json shape."""
from __future__ import annotations

import json

from ckc_lint.data import vocab

from .model import ClaimGraph

SCHEMA_URL = (
    "https://raw.githubusercontent.com/hotherio/claimgraph/main/schema/claimgraph.schema.json"
)


def _node_dict(n) -> dict:
    d = {
        "id": n.id,
        "kind": n.kind,
        "statement": n.statement,
        "status": n.status,
        "effective_status": n.effective_status,
        "in_question": n.in_question,
        "weakest_dep": n.weakest_dep,
    }
    # reconciliation fields: emitted only when set, so commit-only graphs keep their shape.
    if n.lean:
        d["lean"] = n.lean
    if n.aliases:
        d["aliases"] = n.aliases
    for fld in ("claimed", "asserted", "kernel", "agreement", "blueprint_complete", "uses_gap"):
        val = getattr(n, fld)
        if val is not None:
            d[fld] = val
    return d


def to_dict(
    graph: ClaimGraph,
    sources: list[str] | None = None,
    timeline: list[dict] | None = None,
) -> dict:
    meta = {"generator": "claimgraph", "spec_version": vocab()["spec_version"]}
    if sources:
        meta["sources"] = sources
    # The replay timeline rides in ``meta`` (additive: the schema allows extra meta keys, and
    # ``nodes``/``edges`` stay the final state, so existing consumers are byte-unchanged).
    if timeline:
        meta["timeline"] = timeline
    return {
        "$schema": SCHEMA_URL,
        "meta": meta,
        "nodes": [_node_dict(n) for n in sorted(graph.nodes.values(), key=lambda n: n.id)],
        "edges": [
            {
                "source": e.source,
                "target": e.target,
                "relation": e.relation,
                "breaking": e.breaking,
            }
            for e in graph.edges
        ],
    }


def to_json(
    graph: ClaimGraph,
    indent: int = 2,
    sources: list[str] | None = None,
    timeline: list[dict] | None = None,
) -> str:
    return json.dumps(
        to_dict(graph, sources=sources, timeline=timeline), indent=indent, ensure_ascii=False
    )


def from_dict(d: dict) -> ClaimGraph:
    """Reconstruct a ClaimGraph from a ``claimgraph.json`` dict (the inverse of :func:`to_dict`).

    Fills each node's source-of-truth and stored computed fields; recomputed views can be refreshed
    with ``graph.compute`` / ``compute_coverage`` afterwards if needed. This is the missing half of the
    round-trip: a saved graph re-loads without re-running the (slow) lake probe.
    """
    from .model import Edge

    g = ClaimGraph()
    for nd in d.get("nodes", []):
        n = g.node(nd["id"])
        for fld in ("kind", "statement", "status", "effective_status", "in_question", "weakest_dep",
                    "blueprint_complete", "uses_gap", "claimed", "asserted", "kernel", "agreement"):
            if fld in nd:
                setattr(n, fld, nd[fld])
        n.lean = list(nd.get("lean", []))
        n.aliases = list(nd.get("aliases", []))
    for ed in d.get("edges", []):
        g.edges.append(
            Edge(
                source=ed["source"],
                target=ed["target"],
                relation=ed["relation"],
                breaking=ed.get("breaking", False),
            )
        )
    return g


def load(path) -> ClaimGraph:
    """Load a ClaimGraph from a ``claimgraph.json`` file."""
    from pathlib import Path

    return from_dict(json.loads(Path(path).read_text()))
