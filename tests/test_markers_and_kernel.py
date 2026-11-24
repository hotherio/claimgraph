"""Trusted-base markers are not relations, and a kernel proof replaces informal dependencies.

1. ``ASSUMES:`` (an uppercase trusted-base marker carrying prose) was matched case-insensitively
   as the ``Assumes:`` relation, creating a node named after the prose and an edge to it.
2. A claim first recorded with a written proof keeps the ``Depends-On:`` edges of that record even
   after a clean kernel proof closes it, so its effective status stays capped at the informal
   dependencies. A ``math.machine-checked`` commit now replaces the dependency edges of the claims
   it makes machine-checked (its subjects and the targets it Closes/Proves) with the ones it lists.
"""
from __future__ import annotations

from ckc_lint.parse import parse

from claimgraph.build import build_graph
from claimgraph.graph import compute


def graph(*messages: str):
    g = build_graph([parse(m) for m in messages])
    compute(g)
    return g


def test_uppercase_assumes_marker_is_not_a_relation():
    g = graph(
        """conjecture(class-bound): six central landings per segment suffice

Status: math.conjectured
ASSUMES: the flow model is exact for segment classes
""",
    )
    assert set(g.nodes) == {"class-bound"}
    assert g.edges == []


def test_lowercase_assumes_relation_still_works():
    g = graph(
        """proof(lemma-b): b follows from a

Status: math.proved-informal
Assumes: claim:lemma-a
""",
    )
    assert any(e.relation == "Assumes" and e.target == "lemma-a" for e in g.edges)


INFORMAL_LEMMA = """proof(segment-bound): every segment flies 2 d_x per city

Status: math.proved-informal
"""

WRITTEN_THEOREM = """proof(thm): the converse under the triangle inequality

Status: math.proved-informal
Depends-On: claim:segment-bound
"""

KERNEL_PROOF = """formalize(lean): the converse under the triangle inequality

Lean: Zeno.exists_admissible_ATri
Status: math.machine-checked
Axioms: 'Zeno.exists_admissible_ATri' depends on axioms: [propext, Classical.choice, Quot.sound]
Closes: claim:thm
"""


def test_kernel_proof_replaces_the_informal_dependencies_of_the_claim_it_closes():
    g = graph(INFORMAL_LEMMA, WRITTEN_THEOREM, KERNEL_PROOF)
    assert g.nodes["thm"].status == "math.machine-checked"
    assert g.nodes["thm"].effective_status == "math.machine-checked"
    assert not any(e.source == "thm" and e.relation == "Depends-On" for e in g.edges)


def test_kernel_proof_lists_its_dependencies_on_its_subject():
    """Dependencies listed on a kernel commit attach to its subject (the Lean declaration), as for
    any commit; the closed claim rests on the clean kernel proof."""
    kernel_with_dep = KERNEL_PROOF.replace(
        "Closes: claim:thm", "Closes: claim:thm\nDepends-On: claim:segment-bound"
    )
    g = graph(INFORMAL_LEMMA, WRITTEN_THEOREM, kernel_with_dep)
    lean = "Zeno.exists_admissible_ATri"
    assert any(e.source == lean and e.target == "segment-bound" for e in g.edges)
    assert not any(e.source == "thm" and e.relation == "Depends-On" for e in g.edges)
    assert g.nodes["thm"].effective_status == "math.machine-checked"


def test_informal_update_keeps_earlier_dependencies():
    g = graph(
        INFORMAL_LEMMA,
        WRITTEN_THEOREM,
        """review(thm): wording of the statement tightened

Status: math.proved-informal
Claim-ID: thm
""",
    )
    assert any(e.source == "thm" and e.target == "segment-bound" for e in g.edges)


def test_refuting_a_replaced_dependency_no_longer_puts_the_claim_in_question():
    g = graph(
        INFORMAL_LEMMA,
        WRITTEN_THEOREM,
        KERNEL_PROOF,
        """refute(segment-bound)!: a counterexample to the written lemma

Status: math.disproved
Disproves: claim:segment-bound
BREAKING-CHANGE: claim:segment-bound is withdrawn
""",
    )
    assert g.nodes["thm"].in_question is False
