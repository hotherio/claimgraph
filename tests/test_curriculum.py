"""Tests for the L3 dependency-DAG curriculum primitives (fixture-free: runnable with or without pytest)."""
from __future__ import annotations

from pathlib import Path

from claimgraph import curriculum as C
from claimgraph.emit import from_dict, to_dict
from claimgraph.graph import affected, compute
from claimgraph.leandeps import parse_dep_report
from claimgraph.leangraph import build_lean_graph
from claimgraph.model import ClaimGraph, Edge

ROOT = Path(__file__).resolve().parent.parent
MC = "math.machine-checked"


def _chain(n: int) -> ClaimGraph:
    """A linear DAG: n0 <- n1 <- ... (n{i} Depends-On n{i-1}); n0 is the only leaf."""
    g = ClaimGraph()
    for i in range(n):
        g.node(f"n{i}").status = MC
    for i in range(1, n):
        g.edges.append(Edge(source=f"n{i}", target=f"n{i - 1}", relation="Depends-On"))
    return compute(g)


def _igl() -> ClaimGraph:
    deps = parse_dep_report((ROOT / "examples" / "blueprint-igl" / "leandeps.txt").read_text())
    return build_lean_graph(deps)


def _is_topo(g: ClaimGraph, order: list[str]) -> bool:
    pos = {nid: i for i, nid in enumerate(order)}
    _, deps, _ = C._dag(g)
    return all(pos[d] < pos[x] for x in order for d in deps[x])


def test_topo_order_is_valid_and_complete():
    g = _igl()
    order = C.topo_order(g)
    assert set(order) == set(g.nodes) and len(order) == len(set(order))
    assert _is_topo(g, order)  # 0 inversions: every dependency precedes its dependents


def test_topo_is_deterministic():
    g = _igl()
    assert C.topo_order(g) == C.topo_order(g)


def test_cycle_is_detected_not_silently_parked():
    g = ClaimGraph()
    for x in ("a", "b", "c"):
        g.node(x)
    g.edges += [Edge("a", "b", "Depends-On"), Edge("b", "c", "Depends-On"), Edge("c", "a", "Depends-On")]
    assert set(C.detect_cycles(g)) == {"a", "b", "c"}
    raised = False
    try:
        C.topo_order(g)
    except ValueError:
        raised = True
    assert raised


def test_levels_are_longest_path_depth():
    g = _chain(5)
    lv = C.levels(g)
    assert [lv[f"n{i}"] for i in range(5)] == [0, 1, 2, 3, 4]


def test_unlock_power_equals_affected_size():
    g = _igl()
    up = C.unlock_power(g)
    assert all(up[nid] == len(affected(g, nid)) for nid in g.nodes)  # exact == reverse-dep closure
    proxy = C.unlock_power(g, exact=False)
    assert all(proxy[nid] <= up[nid] for nid in g.nodes)  # direct dependents <= transitive


def test_schedule_respects_prerequisites_and_covers_all():
    g = _igl()
    steps = C.schedule(g)
    order = [s["node_id"] for s in steps]
    assert set(order) == set(g.nodes) and _is_topo(g, order)
    assert all(s["level"] >= 0 and s["unlock"] >= 0 and s["frontier_size"] >= 0 for s in steps)


def test_schedule_tiebreak_prefers_high_unlock():
    g = ClaimGraph()
    for x in ("r", "a", "b", "a1", "a2"):
        g.node(x)
    g.edges += [
        Edge("a", "r", "Depends-On"), Edge("b", "r", "Depends-On"),
        Edge("a1", "a", "Depends-On"), Edge("a2", "a", "Depends-On"),
    ]
    compute(g)
    order = [s["node_id"] for s in C.schedule(g)]
    assert order[0] == "r"                          # the only leaf goes first
    assert order.index("a") < order.index("b")      # a (unlock 2) before b (unlock 0)


def test_reproof_order_is_affected_closure_bottom_up():
    g = _chain(5)
    assert C.reproof_set(g, {"n1"}) == {"n1", "n2", "n3", "n4"}
    assert C.reproof_order(g, {"n1"}) == ["n1", "n2", "n3", "n4"]


def test_ready_frontier_gates_on_prerequisites():
    g = _chain(3)
    assert C.ready_frontier(g, set()) == {"n0"}
    assert C.ready_frontier(g, {"n0"}) == {"n1"}
    assert C.ready_frontier(g, {"n0", "n1"}) == {"n2"}


def test_emit_round_trip():
    g = _igl()
    g2 = from_dict(to_dict(g))
    assert set(g2.nodes) == set(g.nodes)
    assert {(e.source, e.target, e.relation) for e in g2.edges} == \
           {(e.source, e.target, e.relation) for e in g.edges}
    assert C.topo_order(g2) == C.topo_order(g)  # stable across a round-trip


def test_induced_subgraph():
    g = _chain(5)
    sub = C.induced_subgraph(g, {"n0", "n1", "n2"})
    assert set(sub.nodes) == {"n0", "n1", "n2"}
    assert all(e.source in sub.nodes and e.target in sub.nodes for e in sub.edges)
