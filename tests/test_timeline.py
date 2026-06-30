"""Tests for the time/replay dimension: per-commit frames that reconstruct the graph's history."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from claimgraph import build_view
from claimgraph.build import load_registry, read_fixture_dated
from claimgraph.emit import to_dict
from claimgraph.timeline import build_timeline

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
SCHEMA = Path(__file__).resolve().parent.parent / "schema" / "claimgraph.schema.json"


def _timeline(name: str, commits: str) -> list[dict]:
    d = EXAMPLES / name
    return build_timeline(read_fixture_dated(str(d / commits)), load_registry(str(d / "claims.toml")))


@pytest.fixture(scope="module")
def fct_frames():
    return _timeline("four-color", "four-color.commits")


def test_one_frame_per_knowledge_commit(fct_frames):
    """Every conventional commit yields a frame; the fixture is all knowledge commits, so 14."""
    dated = read_fixture_dated(str(EXAMPLES / "four-color" / "four-color.commits"))
    assert len(fct_frames) == sum(1 for d in dated if d.commit.header_ok) == 14
    assert [f["i"] for f in fct_frames] == list(range(len(fct_frames)))


def test_refute_frame_marks_the_node_disproved(fct_frames):
    """The refute(kempe)! commit is a 'refuted' event that turns kempe disproved at that frame."""
    rk = next(f for f in fct_frames if "refute(kempe)" in f["subject"])
    assert rk["event"] == "refuted"
    assert rk["focus"] == "kempe"
    assert rk["state"]["kempe"]["status"] == "math.disproved"
    # Two refutations ride through the history that the final all-green snapshot erases.
    assert sum(1 for f in fct_frames if f["event"] == "refuted") == 2


def test_nodes_appear_progressively(fct_frames):
    """Presence is monotone and grows: the replay 'builds' the graph commit by commit."""
    sizes = [len(f["present"]) for f in fct_frames]
    assert sizes[0] == 1 and sizes == sorted(sizes) and sizes[-1] > sizes[0]
    seen: set[str] = set()
    for f in fct_frames:
        present = set(f["present"])
        assert seen <= present  # never loses a node
        seen = present


def test_final_frame_equals_the_static_build(fct_frames):
    """Timeline end == the non-timeline snapshot: same effective status for every node."""
    g = build_view(
        fixture=str(EXAMPLES / "four-color" / "four-color.commits"),
        claims=str(EXAMPLES / "four-color" / "claims.toml"),
    )
    final = fct_frames[-1]["state"]
    for nid, snap in final.items():
        assert snap["effective_status"] == g.nodes[nid].effective_status
    assert final["four-color"]["status"] == "math.machine-checked"


def test_fixtures_have_no_hash_or_date(fct_frames):
    """A fixture carries no git metadata: the axis is commit ordinal, hash/date are null."""
    assert all(f["hash"] is None and f["date"] is None for f in fct_frames)


def test_in_question_propagates_over_time():
    """On IGL, a dependent flips in-question only once its dependency is actually refuted."""
    frames = _timeline("igl", "igl.commits")
    tgt = "IGL.compensatedFactorization"
    flagged = [f["i"] for f in frames if f["state"].get(tgt, {}).get("in_question")]
    refute = next(f for f in frames if f["event"] == "refuted")
    assert flagged, "the dependent should be in question after its dependency is refuted"
    assert min(flagged) >= refute["i"]
    # Before the refutation the same node exists but is not in question.
    pre = [f for f in frames if f["i"] < refute["i"] and tgt in f["state"]]
    assert pre and not any(f["state"][tgt]["in_question"] for f in pre)


def test_timeline_is_opt_in_and_additive():
    """Without a timeline the output is unchanged; with one it rides in meta.timeline only."""
    g = build_view(
        fixture=str(EXAMPLES / "four-color" / "four-color.commits"),
        claims=str(EXAMPLES / "four-color" / "claims.toml"),
    )
    plain = to_dict(g)
    assert "timeline" not in plain["meta"]
    frames = _timeline("four-color", "four-color.commits")
    withtl = to_dict(g, timeline=frames)
    assert withtl["meta"]["timeline"] == frames
    # nodes/edges are identical: existing consumers see no change.
    assert withtl["nodes"] == plain["nodes"] and withtl["edges"] == plain["edges"]


def test_timeline_output_validates_against_schema():
    jsonschema = pytest.importorskip("jsonschema")
    g = build_view(
        fixture=str(EXAMPLES / "four-color" / "four-color.commits"),
        claims=str(EXAMPLES / "four-color" / "claims.toml"),
    )
    frames = _timeline("four-color", "four-color.commits")
    jsonschema.validate(to_dict(g, timeline=frames), json.loads(SCHEMA.read_text()))
