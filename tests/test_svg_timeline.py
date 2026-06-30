"""Tests for the compact SVG timeline exporter."""
from __future__ import annotations

import json
import re
from pathlib import Path

from claimgraph import svg_timeline
from claimgraph.build import build_graph, load_registry, read_fixture, read_fixture_dated
from claimgraph.graph import compute, compute_coverage
from claimgraph.model import Edge, Node
from claimgraph.timeline import build_timeline

ROOT = Path(__file__).resolve().parent.parent
HW, HH = 96, 23


def _render(name: str) -> str:
    base = ROOT / "examples" / name
    commits = next(base.glob("*.commits"))
    reg = load_registry(str(base / "claims.toml")) if (base / "claims.toml").exists() else None
    graph = compute_coverage(compute(build_graph(read_fixture(str(commits)), reg)))
    frames = build_timeline(read_fixture_dated(str(commits)), reg)
    return svg_timeline.render(graph, frames, title=name)


def _data(html: str) -> dict:
    return json.loads(re.search(r"var DATA=(\{.*?\});\nvar SVGNS", html, re.S).group(1))


def test_self_contained_and_well_formed():
    html = _render("four-color")
    assert html.startswith("<!DOCTYPE html>") and "</html>" in html
    # no external assets: the figure must embed everything (no Cytoscape, no CDN).
    assert 'src="http' not in html and 'href="http' not in html and "cytoscape" not in html.lower()
    assert '<svg class="cg-svg"' in html and 'id="slider"' in html


def test_layout_in_bounds_and_no_overlap():
    html = _render("four-color")
    data = _data(html)
    w, h = (int(x) for x in re.search(r'viewBox="0 0 ([\d ]+)"', html).group(1).split())
    pts = list(data["nodes"].values())
    for nd in pts:
        assert HW <= nd["x"] <= w - HW and HH <= nd["y"] <= h - HH
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            a, b = pts[i], pts[j]
            assert abs(a["x"] - b["x"]) >= 2 * HW - 4 or abs(a["y"] - b["y"]) >= 2 * HH - 4


def test_edges_reference_real_nodes():
    data = _data(_render("four-color"))
    ids = set(data["nodes"])
    for e in data["edges"]:
        assert e["s"] in ids and e["t"] in ids


def test_refutation_shows_in_final_state():
    # four-color: Kempe's proof is refuted, so its final style is `ref`.
    data = _data(_render("four-color"))
    assert data["steps"][-1]["set"]["kempe"] == "ref"


def test_weak_pfr_contamination_and_blast_radius():
    # the seven WeakPFR decls regress to open; the downstream corollary is the blast radius.
    final = _data(_render("weak-pfr"))["steps"][-1]["set"]
    strand = ["app-ent-pfr", "torsion-dist-shrinking", "torsion-free-doubling", "pfr-projection",
              "weak-pfr-asymm", "weak-pfr-symm", "weak-pfr-int"]
    assert all(final[n] == "open" for n in strand)
    assert final["pfr-int-strong"] == "blast"
    assert final["entropy-basic"] == "checked"  # foundations stay clean


# --- edge cases (regressions for issues found in adversarial review) ----------------------------

class _G:
    """A minimal graph stub: only what render() reads from a ClaimGraph (nodes, edges)."""

    def __init__(self, ids, edges):
        self.nodes = {i: Node(id=i) for i in ids}
        self.edges = edges


def _frames(ids, k):
    state = {i: {"status": "math.machine-checked", "effective_status": "math.machine-checked",
                 "in_question": False} for i in ids}
    return [{"date": "2026-01-01", "subject": f"commit {j}", "type": "formalize", "event": "asserted",
             "state": state} for j in range(k)]


def test_deep_chain_does_not_recurse():
    # a long Depends-On chain must not overflow the stack: the layout is iterative, not recursive.
    ids = [f"n{i}" for i in range(1500)]
    edges = [Edge(source=f"n{i + 1}", target=f"n{i}", relation="Depends-On") for i in range(1499)]
    assert "<svg" in svg_timeline.render(_G(ids, edges), _frames(ids, 4))


def test_downsample_bounds_frame_count():
    assert len(svg_timeline._downsample(list(range(119)), 60)) <= 61
    assert len(svg_timeline._downsample(list(range(1000)), 60)) <= 61


def test_empty_frames_is_guarded():
    # zero commits must render a valid figure (empty graph + empty log), not JS that throws on load.
    html = svg_timeline.render(_G(["a", "b"], []), [])
    assert "<svg" in html and 'id="log"' in html


def test_commit_log_uses_safe_text():
    # the commit log builds rows with textContent (DOM-safe), never innerHTML string concatenation.
    html = svg_timeline.render(_G(["a"], []), _frames(["a"], 2))
    assert "textContent=sp.s" in html and "innerHTML" not in html
