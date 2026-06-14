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
    # \leanok but the kernel says sorryAx -> the lie is caught (a real validity gap)
    assert g.nodes["lem:helper"].agreement == "kernel-refutes-claim"
    assert g.nodes["lem:helper"].kernel == bp.OPEN


def test_gap_bridge_is_coverage_not_a_validity_gap():
    """A kernel-clean theorem that \\uses an unformalized prose step is blueprint-incomplete
    (a coverage warning), NOT 'effectively proved-informal'. Its validity stays machine-checked --
    a \\uses to a Lean-less concept must not contradict #print axioms."""
    g = _gap_graph()
    bridge = g.nodes["thm:bridge"]
    assert bridge.kernel == bp.MC and bridge.claimed == bp.MC
    assert bridge.effective_status == bp.MC          # validity unaffected by an expository \uses
    assert bridge.agreement == "blueprint-incomplete"  # coverage gap, not a validity gap
    assert bridge.blueprint_complete is False
    assert bridge.uses_gap == "thm:informal-step"    # the unformalized concept it cites


def test_gap_audit_flags_only_validity_gaps_by_default():
    g = _gap_graph()
    # default audit = validity gaps only; the kernel-clean bridge is NOT a failure
    assert {n.id for n in audit(g)} == {"lem:helper", "thm:main"}
    # --strict also surfaces the coverage gap
    assert {n.id for n in audit(g, strict=True)} == {"lem:helper", "thm:main", "thm:bridge"}


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


def test_kernel_clean_theorem_using_prose_def_is_not_a_validity_gap():
    """The corrected headline: gauge / barrier-if are #print-axioms clean, so they are
    machine-checked on validity; they only \\uses prose definitions (def:ansatz / def:metric),
    so they are blueprint-incomplete (coverage), NOT 'effectively proved-informal'."""
    bp_nodes = bp.read_blueprint(str(IGL / "content.tex"))
    kernel = bp.parse_axiom_report((IGL / "axioms.txt").read_text())
    commits = build_graph(read_fixture(str(PAPER / "paper-igl.commits")))
    g = compute_agreement(reconcile(bp.blueprint_graph(bp_nodes, kernel), commits), with_commits=True)
    for label in ("thm:gauge", "thm:barrier-if"):
        n = g.nodes[label]
        assert n.kernel == bp.MC and n.effective_status == bp.MC  # validity: machine-checked
        assert n.agreement == "blueprint-incomplete"              # coverage: uses a prose concept
        assert n.blueprint_complete is False
    # the fully-formalized Master Formula stays consistent (its whole \uses closure is in Lean)
    assert g.nodes["thm:master-formula"].agreement == "consistent"
    assert g.nodes["thm:master-formula"].blueprint_complete is True
    # and no kernel-clean node is ever a validity gap
    assert not any(n.agreement == "kernel-refutes-claim" and n.kernel == bp.MC
                   for n in g.nodes.values())
