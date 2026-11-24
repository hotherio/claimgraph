"""A breaking relation sets the target's status from the target's own domain.

Regression: a science commit's ``Status:`` (e.g. ``sci.measured``, the status of the experiment it
records) was copied onto every ``Refutes:``/``Disproves:`` target, so a refuted math claim showed as
``sci.measured`` instead of ``math.disproved``. The spec (claimgraph.md, Breakage): the target's
status "becomes math.disproved, sci.falsified, or retracted, as appropriate".
"""
from __future__ import annotations

from ckc_lint.parse import parse

from claimgraph.build import build_graph


def graph(*messages: str):
    return build_graph([parse(m) for m in messages])


CONJECTURE = """conjecture(greedy-optimal): the greedy returns the exact front

Status: math.conjectured
"""

HYPOTHESIS = """experiment(rank): rank helps the error

Status: sci.hypothesis
Claim-ID: rank-helps
"""


def test_science_commit_refuting_a_math_claim_disproves_it():
    g = graph(
        CONJECTURE,
        """experiment(e10): the greedy misses front points on 18% of instances

Status: sci.measured
Closes: claim:exp-e10
Refutes: claim:greedy-optimal
""",
    )
    assert g.nodes["greedy-optimal"].status == "math.disproved"
    assert g.nodes["exp-e10"].status == "sci.measured"


def test_science_commit_refuting_a_science_claim_falsifies_it():
    g = graph(
        HYPOTHESIS,
        """experiment(rank-test): no effect of rank on the error

Status: sci.measured
Closes: claim:exp-rank
Refutes: claim:rank-helps
""",
    )
    assert g.nodes["rank-helps"].status == "sci.falsified"


def test_refute_without_status_still_breaks_the_target():
    g = graph(
        CONJECTURE,
        """refute(greedy)!: a counterexample with two cities

Disproves: conjecture:greedy-optimal
BREAKING-CHANGE: conjecture:greedy-optimal is withdrawn
""",
    )
    assert g.nodes["greedy-optimal"].status == "math.disproved"


def test_explicit_broken_status_is_kept():
    """A broken status stated by the commit itself (the spec's replicate example) is kept."""
    g = graph(
        HYPOTHESIS,
        """replicate(rank): an independent run fails to reproduce the effect

Status: sci.not-replicated
Refutes: claim:rank-helps
""",
    )
    assert g.nodes["rank-helps"].status == "sci.not-replicated"


def test_target_of_unknown_domain_follows_the_commit_namespace():
    g = graph(
        """experiment(x): measured against an unregistered claim

Status: sci.measured
Closes: claim:exp-x
Refutes: claim:never-asserted
""",
    )
    assert g.nodes["never-asserted"].status == "sci.falsified"


def test_registry_kind_sets_the_domain():
    from claimgraph.build import seed_registry

    g = build_graph([], None)
    seed_registry(g, {"paper-claim": {"kind": "conjecture", "statement": "s"}})
    from claimgraph.build import _apply_commit

    _apply_commit(
        g,
        parse(
            """experiment(e5): waiting changes the front

Status: sci.measured
Closes: claim:exp-e5
Refutes: claim:paper-claim
"""
        ),
    )
    assert g.nodes["paper-claim"].status == "math.disproved"
