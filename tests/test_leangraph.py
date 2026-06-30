"""Tests for the blueprint-less, kernel-grounded `lean-graph` engine (offline, from saved reports)."""
from __future__ import annotations

import json
from pathlib import Path

from claimgraph.blueprint import parse_axiom_report
from claimgraph.leandeps import parse_dep_report
from claimgraph.leangraph import build_lean_graph

EX = Path(__file__).resolve().parent.parent / "examples" / "blueprint-igl"
KERNEL = {"clean": "math.machine-checked", "axiom": "math.axiomatised", "sorryAx": "math.open"}


def _reports():
    deps = parse_dep_report((EX / "leandeps.txt").read_text())
    kern = parse_axiom_report((EX / "axioms.txt").read_text())
    return deps, kern


def test_every_decl_is_a_node():
    deps, kern = _reports()
    g = build_lean_graph(deps, kern)
    assert g.nodes and set(g.nodes) == set(deps)


def test_edges_are_the_real_lean_deps():
    deps, kern = _reports()
    g = build_lean_graph(deps, kern)
    real = {(s, t) for s, ts in deps.items() for t in ts if t in deps and t != s}
    got = {(e.source, e.target) for e in g.edges if e.relation == "Depends-On"}
    assert got == real
    assert all(e.relation == "Depends-On" for e in g.edges)


def test_kernel_reading_maps_per_node():
    deps, kern = _reports()
    g = build_lean_graph(deps, kern)
    graded = [(n, st) for n, st in kern.items() if n in g.nodes]
    assert graded, "expected some graded decls in the graph"
    for name, st in graded:
        assert g.nodes[name].kernel == KERNEL[st]
        assert g.nodes[name].status == KERNEL[st]


def test_deps_only_graph_has_no_kernel():
    """Without kernel readings the graph still builds (deps only); nodes carry no kernel."""
    deps, _ = _reports()
    g = build_lean_graph(deps, None)
    assert g.nodes and all(n.kernel is None for n in g.nodes.values())


def test_offline_cli(tmp_path):
    from typer.testing import CliRunner

    from claimgraph.cli import app

    out = tmp_path / "g.json"
    res = CliRunner().invoke(
        app,
        ["lean-graph", "--lean-deps", str(EX / "leandeps.txt"),
         "--axioms", str(EX / "axioms.txt"), "-o", str(out)],
    )
    assert res.exit_code == 0, res.output
    d = json.loads(out.read_text())
    assert d["nodes"] and any(n.get("kernel") for n in d["nodes"])
    assert d["meta"]["sources"] == ["lean", "kernel"]


# --- module-system support (issue #28): root resolution + moduleData enumeration -----------------

def test_root_modules_skips_scratch_scripts(tmp_path):
    # a top-level `X.lean` is a library root only if a sibling `X/` module dir exists; a scratch
    # script (e.g. `Final.lean` with no `Final/` dir) must be skipped, else `import Final` breaks the
    # probe with `unknown module prefix`.
    from claimgraph.leandeps import _root_modules

    (tmp_path / "Foundation").mkdir()
    (tmp_path / "Foundation.lean").write_text("-- aggregator\n")
    (tmp_path / "Final.lean").write_text("import Foundation\n")
    assert _root_modules(tmp_path) == ["Foundation"]


def test_root_modules_fallback_when_no_sibling_dir(tmp_path):
    # if no stem has a sibling dir, fall back to every stem (never return empty).
    from claimgraph.leandeps import _root_modules

    (tmp_path / "A.lean").write_text("")
    (tmp_path / "B.lean").write_text("")
    assert _root_modules(tmp_path) == ["A", "B"]


def test_probe_enumerates_via_moduledata():
    # the extractor metaprogram must read `env.header.moduleData` (module-system safe), not
    # `env.constants`, and must not use the `arr[i]!` getElem! notation.
    from claimgraph.leandeps import render_probe

    probe = render_probe(["Foundation"], ["Foundation"])
    assert "env.header.moduleData" in probe and "mods.zip modData" in probe
    # the old, module-system-unsafe constructs must be gone from the actual code (the explanatory
    # comment may still name `env.constants`, so match the call, not the bare word).
    assert "env.constants.toList" not in probe and "getModuleIdxFor?" not in probe
    assert "import Foundation" in probe and "`Foundation" in probe
