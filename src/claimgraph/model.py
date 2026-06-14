"""ClaimGraph data model and the status ladders used for effective status.

Nodes are claims, edges are the relation footers. The status ladders are derived from the CKC
vocabulary (``ckc_lint.data.vocab``) so this stays the single source of truth: the per-namespace
``status`` arrays in ``vocab.json`` are ordered weakest-to-strongest, with the terminal "broken"
states at the end. We strip the broken states out of the ladder and treat them specially, because a
refuted/falsified claim is not "the strongest"; it is an event that drives breakage.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ckc_lint.data import vocab

# Terminal states: a claim shown false / not reproduced. These drive breakage, not the ladder min.
BROKEN: frozenset[str] = frozenset({"math.disproved", "sci.not-replicated", "sci.falsified"})

# Edge relations that mean "A's truth rests on B": the closure we minimise over.
DEPENDENCY_RELATIONS: frozenset[str] = frozenset({"Depends-On", "Assumes"})

# Relations that, on a breaking commit, knock B down and put B's dependents in question.
BREAKING_RELATIONS: frozenset[str] = frozenset(
    {"Refutes", "Disproves", "Retracts", "Invalidates"}
)


def _ladder_ranks() -> dict[str, int]:
    """status -> rank (0 weakest .. N strongest), broken states excluded."""
    ranks: dict[str, int] = {}
    for namespace, states in vocab()["status"].items():
        ladder = [s for s in states if s not in BROKEN]
        for rank, status in enumerate(ladder):
            ranks[status] = rank
    return ranks


LADDER_RANK: dict[str, int] = _ladder_ranks()


def status_key(status: str | None) -> tuple[int, int]:
    """A total order for the effective-status minimum. Lower is weaker.

    broken (0) < unset (1) < ladder rank (2, rank). This lets a broken or unknown dependency
    dominate the minimum the way the spec intends: the weakest dependency sets the effective status.
    """
    if status in BROKEN:
        return (0, 0)
    if status is None:
        return (1, 0)
    return (2, LADDER_RANK.get(status, 0))


def namespace_of(status: str | None) -> str | None:
    if status is None:
        return None
    return status.split(".", 1)[0] if "." in status else None


@dataclass
class Node:
    """A claim: theorem, lemma, definition, conjecture, or empirical finding."""

    id: str
    kind: str | None = None  # conjecture | finding | definition | theorem | ...
    statement: str | None = None
    status: str | None = None  # the working status effective_status is computed from
    # computed views (not stored in the source of truth):
    effective_status: str | None = None
    in_question: bool = False
    weakest_dep: str | None = None  # the node that set the effective status, if weaker than self
    commits: list[str] = field(default_factory=list)  # commit hashes that asserted this node

    # cross-history reconciliation (blueprint x commits x kernel); all optional.
    lean: list[str] = field(default_factory=list)  # Lean FQN(s) for this claim
    aliases: list[str] = field(default_factory=list)  # other ids this node was merged from
    claimed: str | None = None  # blueprint reading (\leanok / \mathlibok)
    asserted: str | None = None  # commit-history reading (latest commit Status:)
    kernel: str | None = None  # kernel reading (#print axioms, via axiom-report)
    agreement: str | None = None  # reconciliation category (see reconcile.py)

    @property
    def broken(self) -> bool:
        return self.status in BROKEN


@dataclass
class Edge:
    source: str  # the claim the asserting commit is about
    target: str  # the footer value
    relation: str  # one of the CKC relation tokens
    breaking: bool = False
    commit: str | None = None


@dataclass
class ClaimGraph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)

    def node(self, node_id: str) -> Node:
        """Get a node, creating a bare one if this id was only seen as an edge target."""
        n = self.nodes.get(node_id)
        if n is None:
            n = Node(id=node_id)
            self.nodes[node_id] = n
        return n
