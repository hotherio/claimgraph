"""Tests for the cross-history reconciliation engine and the discrepancy taxonomy."""
from __future__ import annotations

from pathlib import Path

from claimgraph import blueprint as bp
from claimgraph.build import build_graph, read_fixture
from claimgraph.reconcile import audit, compute_agreement, reconcile

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
GAP = EXAMPLES / "blueprint-gap"
IGL = EXAMPLES / "blueprint-igl"
PAPER = EXAMPLES / "paper-igl"


def _gap_graph():
    nodes = bp.read_blueprint(str(GAP / "content.tex"))
    kernel = bp.parse_axiom_report((GAP / "axioms.txt").read_text())
    g = bp.blueprint_graph(nodes, kernel)
    return compute_agreement(g, with_commits=False)


def test_gap_kernel_refutes_a_false_leanok():
    g = _gap_graph()
    # \leanok but the kernel says sorryAx -> the lie is caught
    assert g.nodes["lem:helper"].agreement == "kernel-refutes-claim"
    assert g.nodes["lem:helper"].kernel == bp.OPEN


def test_gap_effective_gap_is_the_transitive_hole():
    g = _gap_graph()
    bridge = g.nodes["thm:bridge"]
    # its own proof is kernel-clean and it is claimed proved...
    assert bridge.kernel == bp.MC and bridge.claimed == bp.MC
    # ...but it \uses an unformalized step, so its effective status is weaker -> the headline gap
    assert bridge.agreement == "effective-gap"
    assert bridge.effective_status != bp.MC
    assert bridge.weakest_dep == "thm:informal-step"


def test_gap_audit_flags_exactly_the_gaps():
    g = _gap_graph()
    flagged = {n.id for n in audit(g)}
    assert flagged == {"lem:helper", "thm:main", "thm:bridge"}


def test_reconcile_unifies_label_fqn_and_commit():
    """The blueprint label, its Lean FQN, and the commit node must collapse to one claim."""
    bp_nodes = bp.read_blueprint(str(IGL / "content.tex"))
    kernel = bp.parse_axiom_report((IGL / "axioms.txt").read_text())
    bp_graph = bp.blueprint_graph(bp_nodes, kernel)
    commits = build_graph(read_fixture(str(PAPER / "paper-igl.commits")))
    g = compute_agreement(reconcile(bp_graph, commits), with_commits=True)

    mf = g.nodes["thm:master-formula"]
    assert "IGL.fubini_factorization" in mf.aliases  # label unified with the Lean FQN
    assert mf.claimed == bp.MC and mf.asserted == bp.MC and mf.kernel == bp.MC
    assert mf.agreement == "consistent"


def test_reconcile_honest_axiom_is_consistent():
    """prop:expsum: no \\leanok, commit axiomatised, kernel axiom -> all agree, not a gap."""
    bp_nodes = bp.read_blueprint(str(IGL / "content.tex"))
    kernel = bp.parse_axiom_report((IGL / "axioms.txt").read_text())
    g = compute_agreement(bp.blueprint_graph(bp_nodes, kernel), with_commits=False)
    assert g.nodes["prop:expsum"].kernel == bp.AXIOMATISED
    assert g.nodes["prop:expsum"].agreement == "consistent"
