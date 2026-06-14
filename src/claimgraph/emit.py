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


def to_dict(graph: ClaimGraph, sources: list[str] | None = None) -> dict:
    meta = {"generator": "claimgraph", "spec_version": vocab()["spec_version"]}
    if sources:
        meta["sources"] = sources
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


def to_json(graph: ClaimGraph, indent: int = 2, sources: list[str] | None = None) -> str:
    return json.dumps(to_dict(graph, sources=sources), indent=indent, ensure_ascii=False)
