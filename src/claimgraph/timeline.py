"""Replay a CKC history as a sequence of dated graph states (the time dimension).

The static ClaimGraph shows only the *final* state; this module replays the same commit history one
commit at a time, snapshotting each claim's status, effective status and in-question flag after every
commit. The result is a list of frames the viewer animates: nodes appear as commits introduce them,
statuses climb the ladder, and a refutation turns a node broken and puts its dependents in question --
the non-monotone history the final snapshot erases.

It reuses the real build logic (``build._apply_commit``) and the real derived-view computation
(``graph.compute``), so a frame is exactly what ``claimgraph build`` would have produced at that
commit. No status logic is duplicated here, and none is pushed into the viewer.
"""
from __future__ import annotations

from .build import DatedCommit, _apply_commit, seed_registry
from .graph import compute
from .model import ClaimGraph


def edge_id(source: str, relation: str, target: str) -> str:
    """The viewer's stable edge id; kept in sync with ``docs/assets/claimgraph.js``."""
    return f"{source}|{relation}|{target}"


def build_timeline(dated: list[DatedCommit], registry: dict | None = None) -> list[dict]:
    """Replay ``dated`` commits, returning one frame per knowledge commit (oldest first).

    Each frame records the commit (ordinal ``i``, ``hash``, ``date``, ``subject``, ``type``), the
    classified ``event`` / ``focus`` for the replay highlight, the ``present`` node ids and ``edges``
    as of that commit, and the per-node ``state`` (status / effective_status / in_question). A
    non-conventional commit gets no frame, exactly as :func:`build_graph` ignores it.
    """
    g = ClaimGraph()
    seed_registry(g, registry)
    present: set[str] = set()
    frames: list[dict] = []
    for dc in dated:
        commit = dc.commit
        if not commit.header_ok:
            continue
        effect = _apply_commit(g, commit)
        present |= effect.touched
        compute(g)  # derived views over the partial graph: exactly the state at this commit

        # Present edges: every edge built so far (``g.edges`` accumulates), deduped on the viewer id.
        seen: set[str] = set()
        edges: list[str] = []
        for e in g.edges:
            eid = edge_id(e.source, e.relation, e.target)
            if eid not in seen:
                seen.add(eid)
                edges.append(eid)

        state = {
            nid: {
                "status": g.nodes[nid].status,
                "effective_status": g.nodes[nid].effective_status,
                "in_question": g.nodes[nid].in_question,
            }
            for nid in present
            if nid in g.nodes
        }
        subject = commit.raw.split("\n", 1)[0].strip() if commit.raw else (commit.description or "")
        frames.append(
            {
                "i": len(frames),
                "hash": dc.hash,
                "date": dc.date,
                "subject": subject,
                "type": commit.type,
                "event": effect.event,
                "focus": effect.focus,
                "present": sorted(present),
                "edges": edges,
                "state": state,
            }
        )
    return frames
