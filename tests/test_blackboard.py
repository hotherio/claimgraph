"""Tests for the L4 injected-refutation blackboard (fixture-free: runnable with or without pytest)."""
from __future__ import annotations

from pathlib import Path

from claimgraph.blackboard import (
    Finding, build_pre_audit, findings_from_commits, post_findings, run_audit,
)
from claimgraph.build import load_registry, read_fixture
from claimgraph.graph import compute
from claimgraph.model import ClaimGraph, Edge

ROOT = Path(__file__).resolve().parent.parent
MC = "math.machine-checked"
WEAK_PFR = ROOT / "examples" / "weak-pfr"


def _chain(n: int) -> ClaimGraph:
    """n0 <- n1 <- ... (n{i} Depends-On n{i-1}); all machine-checked."""
    g = ClaimGraph()
    for i in range(n):
        g.node(f"n{i}").status = MC
    for i in range(1, n):
        g.edges.append(Edge(source=f"n{i}", target=f"n{i - 1}", relation="Depends-On"))
    return compute(g)


# ---- unit: the blackboard primitives on a synthetic chain --------------------------------------
def test_post_findings_reports_only_changed():
    g = _chain(3)
    changed = post_findings(g, [Finding("n0", "math.open"), Finding("n2", MC)])  # n2 unchanged
    assert changed == {"n0"}


def test_broken_finding_puts_dependents_in_question():
    # a real refutation (a BROKEN status) flags the whole downstream chain in_question
    g = _chain(4)
    report = run_audit(g, [Finding("n0", "math.disproved", "counterexample")])
    assert report["refuted"] == ["n0"]
    assert report["collateral"] == ["n1", "n2", "n3"]              # never refuted, all downstream
    assert all(g.nodes[c].in_question for c in ["n1", "n2", "n3"])  # broken dep raises in_question
    assert report["reproof_order"] == ["n0", "n1", "n2", "n3"]     # prerequisites first


def test_scoped_recompute_leaves_the_unaffected_untouched():
    # a sibling that does not rest on the refuted node keeps its status
    g = _chain(3)
    g.node("side").status = MC                                     # independent leaf, no edges
    compute(g)
    run_audit(g, [Finding("n0", "math.open")])
    assert g.nodes["side"].effective_status == MC                  # outside the blast radius


# ---- end-to-end: the WeakPFR silent-contamination event (the worked demo) -----------------------
def test_weak_pfr_audit_blast_radius():
    commits = read_fixture(WEAK_PFR / "weak-pfr.commits")
    registry = load_registry(WEAK_PFR / "claims.toml")
    graph = build_pre_audit(commits, registry)                    # optimistic: all machine-checked
    compute(graph)
    assert graph.nodes["pfr-int-strong"].effective_status == MC   # the corollary looks proven
    findings = findings_from_commits(commits)
    assert len(findings) == 7 and all(f.status == "math.open" for f in findings)

    report = run_audit(graph, findings)
    assert len(report["refuted"]) == 7
    # the corollary is never audited yet falls into the blast radius (silent collateral)
    assert report["collateral"] == ["pfr-int-strong"]
    corr = next(t for t in report["transitions"] if t["node"] == "pfr-int-strong")
    assert corr["directly_refuted"] is False
    assert corr["before_effective"] == MC and corr["after_effective"] == "math.open"
    # the re-proof curriculum covers all 8 and puts the corollary last (it rests on the rest)
    assert set(report["reproof_order"]) == set(report["blast_radius"])
    assert report["reproof_order"][-1] == "pfr-int-strong"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all blackboard tests passed")
