"""CLI smoke tests: exercise the Typer commands end-to-end on a fixture.

These guard the wiring between the CLI and the library — the kind of break a
library-only suite misses (e.g. `_load` resolving the wrong `build` symbol, or a
command emitting a graph whose `effective_status` was never computed).
"""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from claimgraph.cli import app

runner = CliRunner()
FIX = Path(__file__).resolve().parent.parent / "examples" / "four-color"
COMMITS = str(FIX / "four-color.commits")
CLAIMS = str(FIX / "claims.toml")


def test_build_emits_graph_with_effective_status(tmp_path):
    out = tmp_path / "graph.json"
    result = runner.invoke(app, ["build", "-f", COMMITS, "-c", CLAIMS, "-o", str(out)])

    assert result.exit_code == 0, result.output
    data = json.loads(out.read_text())
    assert data["nodes"], "expected a non-empty graph"
    # the derived view must be computed, not left null (the bug a build_graph-without-compute would cause)
    assert any(n.get("effective_status") is not None for n in data["nodes"]), (
        "no node has an effective_status — compute() did not run"
    )


def test_status_command_runs(tmp_path):
    result = runner.invoke(app, ["status", "-f", COMMITS, "-c", CLAIMS])
    assert result.exit_code == 0, result.output


def test_export_emits_self_contained_html(tmp_path):
    out = tmp_path / "viewer.html"
    result = runner.invoke(app, ["export", "-f", COMMITS, "-c", CLAIMS, "-o", str(out)])
    assert result.exit_code == 0, result.output
    html = out.read_text()
    assert 'id="cg-data"' in html and "<!DOCTYPE html>" in html
