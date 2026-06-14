"""Serialize a computed ClaimGraph to the schema-conformant claimgraph.json shape."""
from __future__ import annotations

import json

from ckc_lint.data import vocab

from .model import ClaimGraph

SCHEMA_URL = (
    "https://raw.githubusercontent.com/hotherio/claimgraph/main/schema/claimgraph.schema.json"
)


def to_dict(graph: ClaimGraph) -> dict:
    return {
        "$schema": SCHEMA_URL,
        "meta": {
            "generator": "claimgraph",
            "spec_version": vocab()["spec_version"],
        },
        "nodes": [
            {
                "id": n.id,
                "kind": n.kind,
                "statement": n.statement,
                "status": n.status,
                "effective_status": n.effective_status,
                "in_question": n.in_question,
                "weakest_dep": n.weakest_dep,
            }
            for n in sorted(graph.nodes.values(), key=lambda n: n.id)
        ],
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


def to_json(graph: ClaimGraph, indent: int = 2) -> str:
    return json.dumps(to_dict(graph), indent=indent, ensure_ascii=False)
