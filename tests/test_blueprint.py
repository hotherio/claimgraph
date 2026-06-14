"""Tests for the Lean Blueprint importer and kernel grounding."""
from __future__ import annotations

from pathlib import Path

from claimgraph import blueprint as bp

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
IGL_TEX = EXAMPLES / "blueprint-igl" / "content.tex"
GAP = EXAMPLES / "blueprint-gap"


def test_parse_extracts_label_lean_uses():
    nodes = {n.label: n for n in bp.read_blueprint(str(IGL_TEX))}
    mf = nodes["thm:master-formula"]
    assert mf.lean == ["IGL.fubini_factorization"]
    assert mf.leanok is True
    assert "def:separable-source" in mf.uses
    assert "thm:fubini-dfold" in mf.uses


def test_leanok_in_prose_is_not_a_flag():
    """paper-igl's prop:expsum body says '(not \\leanok)'; that must not count as formalized."""
    nodes = {n.label: n for n in bp.read_blueprint(str(IGL_TEX))}
    assert nodes["prop:expsum"].lean == ["IGL.expSumRank_logBound"]
    assert nodes["prop:expsum"].leanok is False
    # a paper-only node carries no \lean at all
    assert nodes["def:ansatz"].lean == []
    assert nodes["def:ansatz"].leanok is False


def test_axiom_report_table_parsing():
    table = (
        "DECLARATION  STATUS  NON-STANDARD AXIOMS\n"
        "----------   ------  ----\n"
        "Demo.base    clean\n"
        "Demo.helper  sorryAx  sorryAx\n"
        "IGL.exp      axiom    IGL.greensKernel\n"
    )
    kernel = bp.parse_axiom_report(table)
    assert kernel == {"Demo.base": "clean", "Demo.helper": "sorryAx", "IGL.exp": "axiom"}


def test_kernel_status_mapping():
    mk = lambda fqn: bp.BlueprintNode(label="x", lean=[fqn])
    kernel = {"a": "clean", "b": "axiom", "c": "sorryAx"}
    assert bp.kernel_status_for(mk("a"), kernel) == bp.MC
    assert bp.kernel_status_for(mk("b"), kernel) == bp.AXIOMATISED
    assert bp.kernel_status_for(mk("c"), kernel) == bp.OPEN
    assert bp.kernel_status_for(mk("missing"), kernel) is None
