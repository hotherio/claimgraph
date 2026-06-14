"""Cross-history reconciliation: unify a blueprint, the commit history, and the kernel.

A formal claim is referenced three ways: a blueprint ``\\label``, one or more Lean FQNs, and (in the
commit history) a registry slug. We union-find those aliases onto one claim, attach its three status
*readings* (blueprint ``\\leanok`` = claimed, commit ``Status:`` = asserted, ``#print axioms`` =
kernel), compute the transitive effective status, and classify where the readings disagree.
"""
from __future__ import annotations

from .blueprint import MC
from .graph import compute
from .model import ClaimGraph, Edge, Node

# The discrepancy taxonomy. Order matters only for documentation; classify() returns one.
CATEGORIES = (
    "consistent",            # the readings agree and the claim is effectively machine-checked
    "kernel-refutes-claim",  # a human source claims proved, but #print axioms says sorryAx / axiom
    "effective-gap",         # node itself clean & claimed proved, but a DEPENDENCY breaks it
    "undocumented",          # kernel-clean & blueprint-proved, but no commit ever recorded it
    "stale-blueprint",       # commit machine-checked & kernel clean, but not \\leanok
    "paper-only",            # no Lean, no kernel: a paper-level statement
    "ungrounded",            # kernel unavailable: claimed vs asserted only
)

GAP_CATEGORIES = frozenset({"kernel-refutes-claim", "effective-gap"})


def _union_find(ids: set[str]):
    parent = {i: i for i in ids}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    return find, union


def reconcile(blueprint: ClaimGraph, commits: ClaimGraph) -> ClaimGraph:
    """Unify a blueprint graph with a commit-derived graph into one reconciled ClaimGraph."""
    bp_labels = set(blueprint.nodes)
    fqns = {f for n in blueprint.nodes.values() for f in n.lean}

    ids: set[str] = set(blueprint.nodes) | set(commits.nodes) | fqns
    for e in list(blueprint.edges) + list(commits.edges):
        ids.add(e.source)
        ids.add(e.target)
    find, union = _union_find(ids)

    # Aliases: a blueprint node links its label to each of its Lean FQNs.
    for n in blueprint.nodes.values():
        for fqn in n.lean:
            union(n.id, fqn)

    # Canonical display id per component: prefer a blueprint label, then a Lean FQN, then the id.
    members: dict[str, list[str]] = {}
    for i in ids:
        members.setdefault(find(i), []).append(i)
    canonical: dict[str, str] = {}
    for root, ms in members.items():
        label = next((m for m in sorted(ms) if m in bp_labels), None)
        fqn = next((m for m in sorted(ms) if m in fqns), None)
        canonical[root] = label or fqn or sorted(ms)[0]

    def cid(x: str) -> str:
        return canonical.get(find(x), x)

    g = ClaimGraph()
    # blueprint readings (claimed, kernel, lean, working status)
    for n in blueprint.nodes.values():
        m = g.node(cid(n.id))
        m.kind = m.kind or n.kind
        m.statement = m.statement or n.statement
        m.lean = sorted(set(m.lean) | set(n.lean))
        m.claimed = n.claimed
        m.kernel = n.kernel
        m.status = n.status
    # commit reading (asserted)
    for n in commits.nodes.values():
        m = g.node(cid(n.id))
        m.kind = m.kind or n.kind
        m.statement = m.statement or n.statement
        m.asserted = n.status
        m.commits = n.commits
    # working status precedence: kernel reality > recorded history > blueprint claim
    for m in g.nodes.values():
        m.status = m.kernel or m.asserted or m.status
    # record the merged aliases
    for root, ms in members.items():
        c = canonical[root]
        if c in g.nodes:
            g.nodes[c].aliases = sorted(x for x in ms if x != c)

    # edges from both sources, remapped onto canonical ids and deduped
    seen: set[tuple[str, str, str]] = set()
    for e in list(blueprint.edges) + list(commits.edges):
        s, t = cid(e.source), cid(e.target)
        key = (s, t, e.relation)
        if s != t and key not in seen:
            seen.add(key)
            g.edges.append(Edge(source=s, target=t, relation=e.relation, breaking=e.breaking))
    return g


def classify(n: Node, with_commits: bool) -> str:
    """Assign one discrepancy category to a reconciled node."""
    claimed_mc = n.claimed == MC
    asserted_mc = n.asserted == MC
    has_lean = bool(n.lean)

    if n.kernel is None:
        if with_commits and claimed_mc and n.asserted and not asserted_mc:
            return "stale-blueprint"
        if claimed_mc or asserted_mc:
            return "ungrounded"
        return "paper-only" if not has_lean else "ungrounded"

    kernel_mc = n.kernel == MC
    if (claimed_mc or asserted_mc) and not kernel_mc:
        return "kernel-refutes-claim"
    if kernel_mc and claimed_mc and n.effective_status != MC:
        return "effective-gap"
    if with_commits and kernel_mc and claimed_mc and n.asserted is None:
        return "undocumented"
    if with_commits and kernel_mc and asserted_mc and n.claimed is None:
        return "stale-blueprint"
    return "consistent"


def compute_agreement(graph: ClaimGraph, with_commits: bool) -> ClaimGraph:
    """Compute effective status, then classify every node into the discrepancy taxonomy."""
    compute(graph)
    for n in graph.nodes.values():
        n.agreement = classify(n, with_commits)
    return graph


def audit(graph: ClaimGraph) -> list[Node]:
    """Nodes whose readings disagree in a way that matters: claimed-but-not-really-proved."""
    return sorted(
        (n for n in graph.nodes.values() if n.agreement in GAP_CATEGORIES),
        key=lambda n: n.id,
    )
