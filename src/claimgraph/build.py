"""Turn a stream of CKC commits (+ the claims.toml registry) into a ClaimGraph.

Commit parsing and the CKC vocabulary are reused from ``ckc_lint`` (the single source of truth),
so this module only adds the graph-specific logic: identity reconciliation, status assignment, and
edge construction.
"""
from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

from ckc_lint.data import breaking_tokens, relation_tokens
from ckc_lint.parse import Commit, parse

from .model import ClaimGraph, Edge

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
    """All canonical ids referenced by a (possibly comma-listed, repeatable) footer token."""
    out: list[str] = []
    for f in commit.footers:
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


def _is_breaking(commit: Commit) -> bool:
    toks = {t.lower() for t in breaking_tokens()}
    return commit.bang or any(f.token.lower() in toks for f in commit.footers)


def build_graph(commits: list[Commit], registry: dict | None = None) -> ClaimGraph:
    """Build the graph from commits in chronological (oldest-first) order."""
    g = ClaimGraph()

    # Seed registry claims so they carry their human statement and kind even before a commit.
    for slug, entry in (registry or {}).items():
        node = g.node(slug)
        node.kind = entry.get("kind")
        node.statement = entry.get("statement")

    for commit in commits:
        if not commit.header_ok:
            continue
        status = commit.footer("Status")
        promote_targets = [t for tok in PROMOTE_RELATIONS for t in _values(commit, tok)]
        break_targets = [t for tok in BREAK_RELATIONS for t in _values(commit, tok)]
        subjects = _subjects(commit, bool(break_targets))

        # The subject nodes: record statement/kind/status.
        for sid in subjects:
            node = g.node(sid)
            if node.statement is None and commit.description:
                node.statement = commit.description
            if node.kind is None:
                node.kind = commit.type
            if status:
                node.status = status

        # A discharged claim inherits the status; a broken claim takes the breaking status.
        if status:
            for tid in promote_targets + break_targets:
                g.node(tid).status = status

        # Edges from every relation footer. Source is the subject; a pure event (e.g. a refute with
        # no Lean subject) gets a synthetic source node so the event is still visible in the graph.
        source = subjects[0] if subjects else f"{commit.type}:{commit.scope or '_'}"
        if not subjects and commit.scope:
            ev = g.node(source)
            if ev.statement is None:
                ev.statement = commit.description
                ev.kind = commit.type

        breaking = _is_breaking(commit)
        for tok in relation_tokens():
            for target in _values(commit, tok):
                g.edges.append(
                    Edge(source=source, target=target, relation=tok, breaking=breaking)
                )

    return g


# --- commit sources -------------------------------------------------------------------------------

_FIXTURE_SEP = "\n---\n"


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


def load_registry(path: str | Path | None) -> dict:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    with p.open("rb") as fh:
        data = tomllib.load(fh)
    return data.get("claims", {})
