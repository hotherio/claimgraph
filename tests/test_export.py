"""Tests for the standalone HTML exporter."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from claimgraph import export_html
from claimgraph.build import build_graph, load_registry, read_fixture, read_fixture_dated
from claimgraph.emit import to_dict
from claimgraph.timeline import build_timeline

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "examples" / "four-color"
VIEWER = ROOT / "src" / "claimgraph" / "viewer"
DOCS = ROOT / "docs" / "assets"


def _payload():
    reg = load_registry(str(FIX / "claims.toml"))
    graph = build_graph(read_fixture(str(FIX / "four-color.commits")), reg)
    frames = build_timeline(read_fixture_dated(str(FIX / "four-color.commits")), reg)
    return to_dict(graph, timeline=frames), len(frames)


# --- the bundled viewer must not drift from the canonical docs/assets copies -------------------

@pytest.mark.parametrize("name,docs_rel", [
    ("claimgraph.css", "claimgraph.css"),
    ("claimgraph.js", "claimgraph.js"),
    ("cytoscape.min.js", "vendor/cytoscape.min.js"),
    ("logo.png", "logo.png"),
])
def test_viewer_assets_match_docs(name, docs_rel):
    assert (VIEWER / name).read_bytes() == (DOCS / docs_rel).read_bytes(), (
        f"{name} drifted from docs/assets/{docs_rel}; run scripts/sync-viewer.sh"
    )


# --- page shape: a single self-contained file -------------------------------------------------

def test_page_is_self_contained_with_timeline():
    payload, nframes = _payload()
    h = export_html.render(payload, shape="page", title="Four Colour Theorem")
    # no external asset references (page shape pulls nothing over the network)
    assert 'src="assets/' not in h and 'href="assets/' not in h
    assert "<script src=" not in h and "<link rel=\"stylesheet\"" not in h
    # the data rides in an inline island, and the viewer + cytoscape are inlined
    assert 'id="cg-data"' in h and "cytoscape" in h.lower()
    # the board + transport are present
    for marker in ('id="cy"', 'id="transport"', 'id="tl-range"', 'id="status-legend"'):
        assert marker in h
    # the island parses and carries the timeline
    island = re.search(r'<script type="application/json" id="cg-data">(.*?)</script>', h, re.S).group(1)
    data = json.loads(island.replace("<\\/", "</"))
    assert len(data["nodes"]) == len(payload["nodes"])
    assert len(data["meta"]["timeline"]) == nframes


def test_script_close_in_data_cannot_break_out():
    payload = {"meta": {}, "nodes": [{"id": "x", "statement": "danger </script><b>pwn"}], "edges": []}
    h = export_html.render(payload, shape="page", title="t")
    island = re.search(r'<script type="application/json" id="cg-data">(.*?)</script>', h, re.S).group(1)
    assert "</script>" not in island               # escaped to <\/script>
    assert "</" not in island
    assert json.loads(island.replace("<\\/", "</"))["nodes"][0]["statement"].endswith("pwn")


def test_no_timeline_flag_omits_frames():
    payload, _ = _payload()
    payload_no_tl = {**payload, "meta": {k: v for k, v in payload["meta"].items() if k != "timeline"}}
    h = export_html.render(payload_no_tl, shape="page", title="t")
    island = re.search(r'<script type="application/json" id="cg-data">(.*?)</script>', h, re.S).group(1)
    assert "timeline" not in json.loads(island.replace("<\\/", "</"))["meta"]


def test_fragment_is_an_isolated_iframe():
    payload, _ = _payload()
    h = export_html.render(payload, shape="fragment").lstrip()
    assert h.startswith("<iframe") and "srcdoc=" in h
    assert "<!DOCTYPE html>" not in h  # the document lives escaped inside srcdoc, not at top level


def test_branded_has_chrome():
    payload, _ = _payload()
    h = export_html.render(payload, shape="branded")
    assert 'class="nav"' in h and "data:image/png;base64," in h and "<footer" in h


def test_unknown_shape_raises():
    with pytest.raises(ValueError):
        export_html.render({"meta": {}, "nodes": [], "edges": []}, shape="bogus")
