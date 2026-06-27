"""Tests for grounding Depends-On edges against Lean's real dependency graph.

The live extraction (``extract_lean_deps``) needs a built Lean project, so it is not exercised here;
everything else is pure and is tested against a saved dep-report, the same way the rest of the suite
runs without a Lean toolchain.
"""
from __future__ import annotations

from claimgraph.leandeps import (
    DepGrounding,
    asserted_edges,
    collapse_to_nodes,
    compare_edges,
    lean_to_node_map,
    parse_dep_report,
    render_probe,
)
from claimgraph.model import ClaimGraph, Edge


def test_parse_dep_report_reads_name_and_deps():
    raw = parse_dep_report(
        "IGL.foo :: IGL.bar IGL.baz\n"
        "IGL.bar :: \n"
        "[claimgraph dep-report] 2 declarations\n"  # stderr-style line, no ' :: ', ignored
    )
    assert raw == {"IGL.foo": ["IGL.bar", "IGL.baz"], "IGL.bar": []}


def test_collapse_passes_through_non_node_helpers():
    # foo --(uses)--> helper --(uses)--> bar, where `helper` is NOT a claim node.
    raw = {"L.foo": ["L.helper"], "L.helper": ["L.bar"], "L.bar": []}
    lean_to_node = {"L.foo": "foo", "L.bar": "bar"}  # helper is deliberately not mapped
    assert collapse_to_nodes(raw, lean_to_node) == {("foo", "bar")}


def test_collapse_ignores_self_and_unmapped_targets():
    raw = {"L.foo": ["L.foo", "L.mystery"], "L.mystery": []}
    assert collapse_to_nodes(raw, {"L.foo": "foo"}) == set()


def test_compare_splits_confirmed_missing_spurious():
    real = {("a", "b"), ("a", "c")}
    asserted = {("a", "b"), ("a", "d")}  # a->b real, a->d not, a->c real but unrecorded
    result = compare_edges(real, asserted, grounded_nodes={"a"})
    assert result.confirmed == {("a", "b")}
    assert result.spurious == {("a", "d")}   # asserted, no Lean path
    assert result.missing == {("a", "c")}    # real, never asserted


def test_compare_only_judges_grounded_sources():
    # `x` has no Lean reading, so its asserted edge cannot be called spurious (honest guard).
    result = compare_edges(real=set(), asserted={("x", "y")}, grounded_nodes=set())
    assert result.spurious == set()
    assert isinstance(result, DepGrounding)


def test_asserted_edges_only_logical_relations():
    g = ClaimGraph()
    g.edges = [
        Edge("a", "b", "Depends-On"),
        Edge("a", "c", "Assumes"),
        Edge("a", "d", "Uses"),       # coverage edge, NOT a logical dependency
        Edge("a", "e", "Refutes"),    # breaking, not a dependency
    ]
    assert asserted_edges(g) == {("a", "b"), ("a", "c")}


def test_lean_to_node_map_inverts_node_lean():
    g = ClaimGraph()
    g.node("thm:x").lean = ["NS.x", "NS.x_alt"]
    g.node("thm:y").lean = ["NS.y"]
    assert lean_to_node_map(g) == {"NS.x": "thm:x", "NS.x_alt": "thm:x", "NS.y": "thm:y"}


def test_render_probe_imports_roots_and_lists_prefixes():
    probe = render_probe(["Igl"], ["IGL"])
    assert "import Igl" in probe
    assert "[`IGL]" in probe
    assert "getUsedConstants" in probe


def test_planted_wrong_edge_is_flagged_spurious():
    # The plan's demo as a unit test: an author asserts foo Depends-On bar, but Lean shows no path.
    raw = {"L.foo": [], "L.bar": []}
    lean_to_node = {"L.foo": "foo", "L.bar": "bar"}
    real = collapse_to_nodes(raw, lean_to_node)            # empty: foo uses nothing
    asserted = {("foo", "bar")}                            # the wrong, hand-authored edge
    result = compare_edges(real, asserted, grounded_nodes={"foo"})
    assert result.spurious == {("foo", "bar")}
