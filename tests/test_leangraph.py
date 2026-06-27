"""Tests for the blueprint-less, kernel-grounded `lean-graph` engine (offline, from saved reports)."""
from __future__ import annotations

import json
from pathlib import Path

from claimgraph.blueprint import parse_axiom_report
from claimgraph.leandeps import parse_dep_report
from claimgraph.leangraph import build_lean_graph

EX = Path(__file__).resolve().parent.parent / "examples" / "blueprint-igl"
KERNEL = {"clean": "math.machine-checked", "axiom": "math.axiomatised", "sorryAx": "math.open"}


def _reports():
    deps = parse_dep_report((EX / "leandeps.txt").read_text())
    kern = parse_axiom_report((EX / "axioms.txt").read_text())
    return deps, kern


def test_every_decl_is_a_node():
    deps, kern = _reports()
    g = build_lean_graph(deps, kern)
    assert g.nodes and set(g.nodes) == set(deps)


def test_edges_are_the_real_lean_deps():
    deps, kern = _reports()
    g = build_lean_graph(deps, kern)
    real = {(s, t) for s, ts in deps.items() for t in ts if t in deps and t != s}
    got = {(e.source, e.target) for e in g.edges if e.relation == "Depends-On"}
    assert got == real
    assert all(e.relation == "Depends-On" for e in g.edges)


def test_kernel_reading_maps_per_node():
    deps, kern = _reports()
    g = build_lean_graph(deps, kern)
    graded = [(n, st) for n, st in kern.items() if n in g.nodes]
    assert graded, "expected some graded decls in the graph"
    for name, st in graded:
        assert g.nodes[name].kernel == KERNEL[st]
        assert g.nodes[name].status == KERNEL[st]


def test_deps_only_graph_has_no_kernel():
    """Without kernel readings the graph still builds (deps only); nodes carry no kernel."""
    deps, _ = _reports()
    g = build_lean_graph(deps, None)
    assert g.nodes and all(n.kernel is None for n in g.nodes.values())


def test_offline_cli(tmp_path):
    from typer.testing import CliRunner

    from claimgraph.cli import app

    out = tmp_path / "g.json"
    res = CliRunner().invoke(
        app,
        ["lean-graph", "--lean-deps", str(EX / "leandeps.txt"),
         "--axioms", str(EX / "axioms.txt"), "-o", str(out)],
    )
    assert res.exit_code == 0, res.output
    d = json.loads(out.read_text())
    assert d["nodes"] and any(n.get("kernel") for n in d["nodes"])
    assert d["meta"]["sources"] == ["lean", "kernel"]
