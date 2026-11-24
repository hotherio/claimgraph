"""Turn a stream of CKC commits (+ the claims.toml registry) into a ClaimGraph.

Commit parsing and the CKC vocabulary are reused from ``ckc_lint`` (the single source of truth),
so this module only adds the graph-specific logic: identity reconciliation, status assignment, and
edge construction.
"""
from __future__ import annotations

import datetime
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from ckc_lint.data import breaking_tokens, relation_tokens, trusted_base_tokens
from ckc_lint.parse import Commit, parse

from .model import BROKEN, DEPENDENCY_RELATIONS, ClaimGraph, Edge, namespace_of

KERNEL_STATUS = "math.machine-checked"

# Reference prefixes that are cosmetic and stripped to reach the canonical id.
SCIENCE_PREFIXES = {"conjecture", "claim", "result", "def", "definition", "hypothesis", "finding"}
FORMAL_PREFIXES = {"lean", "rocq", "coq", "isabelle", "agda"}

# Relations whose target inherits this commit's status.
PROMOTE_RELATIONS = ("Proves", "Closes")
BREAK_RELATIONS = ("Disproves", "Refutes", "Retracts", "Invalidates")


def canonical(ref: str) -> str:
    """Collapse a footer reference to its stable id.

    ``conjecture:master-formula`` / ``claim:master-formula`` -> ``master-formula`` (registry slug);
    ``lean:IGL.foo`` -> ``IGL.foo``; a bare Lean FQN or slug passes through unchanged.
    """
    ref = ref.strip()
    if ":" in ref:
        prefix, rest = ref.split(":", 1)
        if prefix.strip().lower() in SCIENCE_PREFIXES | FORMAL_PREFIXES:
            return rest.strip()
    return ref


def _values(commit: Commit, token: str) -> list[str]:
    """All canonical ids referenced by a (possibly comma-listed, repeatable) footer token.

    Relation tokens match case-insensitively, but an uppercase trusted-base marker (``ASSUMES:``,
    ``AXIOM:``, ...) is prose about the commit's own trusted base, never a relation: ``ASSUMES:``
    must not be read as ``Assumes:``.
    """
    markers = trusted_base_tokens()
    out: list[str] = []
    for f in commit.footers:
        if f.token in markers:
            continue
        if f.token.lower() == token.lower():
            out.extend(canonical(p) for p in f.value.replace("\n", ",").split(",") if p.strip())
    return out


def _subjects(commit: Commit, is_break_event: bool) -> list[str]:
    """The claim(s) the commit is about: Lean/Formal-Statement ids, else a Claim-ID, else the scope.

    The scope normally names the asserted claim (``conjecture(master-formula)``,
    ``proof(appel-haken)``), even when the commit also ``Closes`` or ``Depends-On`` other claims. It
    is skipped only for a breaking event (``refute(...)!`` with ``Disproves:``/``Retracts:``), where
    the scope is the event topic and the status belongs to the refuted target, not to a new claim.
    """
    subs = _values(commit, "Lean") + _values(commit, "Formal-Statement")
    if not subs:
        subs = _values(commit, "Claim-ID")
    if not subs and commit.scope and not is_break_event:
        subs = [canonical(commit.scope)]
    return subs


# Kinds (a registry `kind`, or the type of the commit that first asserted the node) that place a
# claim in the science domain; anything else defaults to mathematics.
SCIENCE_KINDS = frozenset(
    {"hypothesis", "finding", "experiment", "result", "replicate", "null", "data", "protocol",
     "method", "analysis", "repro-fix", "observation"}
)
# The broken status of each domain for a refutation-like relation.
BROKEN_BY_DOMAIN = {"math": "math.disproved", "sci": "sci.falsified"}


def _domain(node, commit_status: str | None) -> str:
    """The domain (``math`` or ``sci``) of a claim: from its current status, else its kind, else
    the namespace of the commit that refers to it, else ``math``."""
    ns = namespace_of(node.status)
    if ns in BROKEN_BY_DOMAIN:
        return ns
    if node.kind:
        return "sci" if node.kind.lower() in SCIENCE_KINDS else "math"
    ns = namespace_of(commit_status)
    return ns if ns in BROKEN_BY_DOMAIN else "math"


def _broken_status(node, relation: str, commit_status: str | None) -> str | None:
    """The status a breaking relation gives its target.

    A broken status the commit states itself (``Status: math.disproved`` on a ``refute!``,
    ``sci.not-replicated`` on a failed ``replicate``) is kept when it belongs to the target's
    domain. Otherwise the target takes its domain's broken status. ``Retracts`` withdraws a claim
    without showing it false, and CKC has no retracted status, so it only changes the target's
    status when the commit states a broken one.
    """
    domain = _domain(node, commit_status)
    if commit_status in BROKEN and namespace_of(commit_status) == domain:
        return commit_status
    if relation == "Retracts":
        return None
    return BROKEN_BY_DOMAIN[domain]


def _is_breaking(commit: Commit) -> bool:
    toks = {t.lower() for t in breaking_tokens()}
    return commit.bang or any(f.token.lower() in toks for f in commit.footers)


@dataclass
class CommitEffect:
    """What applying one commit did to the graph: the node ids it touched, the focal claim, and the
    kind of event. Used by the timeline replay; :func:`build_graph` ignores the return value."""

    touched: set[str] = field(default_factory=set)
    focus: str | None = None
    event: str | None = None  # asserted | promoted | superseded | refuted | None


def _apply_commit(g: ClaimGraph, commit: Commit) -> CommitEffect:
    """Apply a single commit to ``g`` (status assignment + edges) and report its effect.

    This is the per-commit body of :func:`build_graph`, factored out so the timeline replay can
    apply commits one at a time and snapshot the graph between them without duplicating the logic.
    A non-conventional commit (``header_ok`` false) is a no-op, exactly as before.
    """
    if not commit.header_ok:
        return CommitEffect()
    status = commit.footer("Status")
    promote_targets = [t for tok in PROMOTE_RELATIONS for t in _values(commit, tok)]
    break_targets = [t for tok in BREAK_RELATIONS for t in _values(commit, tok)]
    subjects = _subjects(commit, bool(break_targets))
    touched: set[str] = set()

    # The subject nodes: record statement/kind/status.
    for sid in subjects:
        node = g.node(sid)
        if node.statement is None and commit.description:
            node.statement = commit.description
        if node.kind is None:
            node.kind = commit.type
        if status:
            node.status = status
        touched.add(sid)

    # A discharged claim inherits the status. A broken claim takes the broken status of its own
    # domain (spec, Breakage: "math.disproved, sci.falsified, or retracted, as appropriate"), not
    # the commit's: a science commit's `Status: sci.measured` is the status of the experiment it
    # records, not of the claim it refutes.
    if status:
        for tid in promote_targets:
            g.node(tid).status = status
    for tok in BREAK_RELATIONS:
        for tid in _values(commit, tok):
            node = g.node(tid)
            broken = _broken_status(node, tok, status)
            if broken is not None:
                node.status = broken

    # Edges from every relation footer. Source is the subject; a pure event (e.g. a refute with
    # no Lean subject) gets a synthetic source node so the event is still visible in the graph.
    source = subjects[0] if subjects else f"{commit.type}:{commit.scope or '_'}"
    if not subjects and commit.scope:
        ev = g.node(source)
        if ev.statement is None:
            ev.statement = commit.description
            ev.kind = commit.type
    touched.add(source)

    # A clean kernel proof does not rest on the informal argument it replaces: the claims this
    # commit makes machine-checked (its subjects and what it Closes/Proves) drop the dependency
    # edges of earlier records and keep only those this commit lists. Other updates accumulate.
    # The dependencies it lists attach to its subjects, as for any commit; a closed claim rests on
    # the kernel proof, whose own axioms are already clean (otherwise it is not machine-checked).
    if status == KERNEL_STATUS:
        replaced = set(subjects) | set(promote_targets)
        g.edges = [
            e for e in g.edges
            if not (e.source in replaced and e.relation in DEPENDENCY_RELATIONS)
        ]

    breaking = _is_breaking(commit)
    for tok in relation_tokens():
        for target in _values(commit, tok):
            g.edges.append(Edge(source=source, target=target, relation=tok, breaking=breaking))
            touched.add(target)

    # Classify the event for the replay highlight (most salient first).
    if break_targets:
        event, focus = "refuted", break_targets[0]
    elif _values(commit, "Supersedes"):
        event, focus = "superseded", (subjects[0] if subjects else source)
    elif promote_targets:
        event, focus = "promoted", (subjects[0] if subjects else promote_targets[0])
    elif subjects and status:
        event, focus = "asserted", subjects[0]
    else:
        event, focus = None, (subjects[0] if subjects else None)
    return CommitEffect(touched=touched, focus=focus, event=event)


def _fidelity(value) -> dict | None:
    """Light validation of a claims.toml fidelity record: keep it a plain dict (anything else is
    dropped), with TOML-native date values coerced to ISO strings so the record stays JSON-safe."""
    if not isinstance(value, dict):
        return None
    return {
        k: (v.isoformat() if isinstance(v, (datetime.date, datetime.datetime)) else v)
        for k, v in value.items()
    }


def seed_registry(g: ClaimGraph, registry: dict | None) -> None:
    """Seed registry claims so they carry their human statement and kind even before a commit.

    The entry's ``lean`` field (one FQN, or a comma-separated list) is kept as node aliases so
    reconciliation can unify the registry slug with the blueprint node carrying the same
    ``\\lean{}`` name -- without it a registry-only record (statement, fidelity) floats as a
    separate ``paper-only`` node and never reaches the reconciled claim.
    """
    for slug, entry in (registry or {}).items():
        node = g.node(slug)
        node.kind = entry.get("kind")
        node.statement = entry.get("statement")
        node.fidelity = _fidelity(entry.get("fidelity"))
        lean = entry.get("lean")
        if isinstance(lean, str) and lean.strip():
            node.lean = sorted({s.strip() for s in lean.split(",") if s.strip()})


def build_graph(commits: list[Commit], registry: dict | None = None) -> ClaimGraph:
    """Build the graph from commits in chronological (oldest-first) order."""
    g = ClaimGraph()
    seed_registry(g, registry)
    for commit in commits:
        _apply_commit(g, commit)
    return g


# --- commit sources -------------------------------------------------------------------------------

_FIXTURE_SEP = "\n---\n"
# Unit/record separators for parsing dated git logs: \x1f between fields, \x1e between commits.
_GIT_FIELD = "\x1f"
_GIT_REC = "\x1e"


@dataclass
class DatedCommit:
    """A parsed commit plus the git metadata the timeline replay needs as an axis. ``hash`` and
    ``date`` are ``None`` for fixtures (which carry no git metadata; the axis is commit ordinal)."""

    commit: Commit
    hash: str | None = None
    date: str | None = None  # ISO-8601 author date (%aI), if read from a real repo


def read_fixture(path: str | Path) -> list[Commit]:
    """Parse a fixture file: commit messages separated by a line containing only ``---``."""
    text = Path(path).read_text(encoding="utf-8").strip()
    chunks = [c.strip() for c in text.split(_FIXTURE_SEP) if c.strip()]
    return [parse(c) for c in chunks]


def read_git(repo: str | Path = ".") -> list[Commit]:
    """Read commits from a git repo, oldest first, via ``git log``."""
    out = subprocess.run(
        ["git", "-C", str(repo), "log", "--reverse", "--format=%B%x1e"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [parse(c.strip()) for c in out.split("\x1e") if c.strip()]


def read_fixture_dated(path: str | Path) -> list[DatedCommit]:
    """Like :func:`read_fixture`, wrapped as :class:`DatedCommit` (no hash/date for fixtures)."""
    return [DatedCommit(commit=c) for c in read_fixture(path)]


def read_git_dated(repo: str | Path = ".") -> list[DatedCommit]:
    """Read commits oldest-first with their hash (%H) and author date (%aI) for the timeline axis."""
    fmt = f"%H{_GIT_FIELD}%aI{_GIT_FIELD}%B{_GIT_REC}"
    out = subprocess.run(
        ["git", "-C", str(repo), "log", "--reverse", f"--format={fmt}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    dated: list[DatedCommit] = []
    for rec in out.split(_GIT_REC):
        rec = rec.strip("\n")
        if not rec.strip():
            continue
        sha, date, message = (rec.split(_GIT_FIELD, 2) + ["", ""])[:3]
        dated.append(DatedCommit(commit=parse(message.strip()), hash=sha.strip(), date=date.strip()))
    return dated


def load_registry(path: str | Path | None) -> dict:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    with p.open("rb") as fh:
        data = tomllib.load(fh)
    return data.get("claims", {})
