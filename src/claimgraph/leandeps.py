"""Ground ``Depends-On`` edges against the proof assistant's real dependency graph.

The CKC ``Depends-On`` / ``Assumes`` footers are author-asserted: a human (or an agent) writes which
claims a result rests on. Lean already knows the truth. Every elaborated proof term records the
declarations it actually references, so the real logical dependency graph is machine-extractable.

This module extracts that graph from a built project (a small metaprogram run via ``lake env lean``,
the same bridge idea as ``axiom-report``), collapses it onto the blueprint's claim nodes, and
compares it to the asserted edges. Drift shows up in both directions:

* **spurious** -- an asserted ``Depends-On`` with no real Lean path (an over-claimed or expository
  edge that is not a logical dependency);
* **missing** -- a real Lean dependency between two claims that no commit ever recorded.

The live extraction (:func:`extract_lean_deps`) is isolated; everything else is pure and unit-tested
against a saved report, so a project need not be built to exercise the comparison.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .model import DEPENDENCY_RELATIONS

# The extractor metaprogram. ``{imports}`` and ``{prefixes}`` are filled in per project. It prints,
# for every project declaration, the project declarations its type or value directly references:
#   IGL.fubini_factorization :: IGL.iglParticular IGL.separableSource IGL.separableKernel
# "project declaration" = a constant whose defining module lies under a project namespace (so a
# root-namespace decl defined in a project module, e.g. PFR's `weak_PFR`, still counts).
_LEAN_TEMPLATE = """\
{imports}
open Lean Elab Command

run_cmd do
  let env ← getEnv
  let prefixes : List Name := [{prefixes}]
  let mods := env.header.moduleNames
  let modData := env.header.moduleData
  -- Enumerate declarations from each project module's stored constants (`env.header.moduleData`),
  -- zipped with module names, rather than iterating `env.constants` or indexing with `arr[i]!`.
  -- After importing a module-system project the `SMap` / getElem! surface API those need is not
  -- re-exported into the elaboration scope (after `import Foundation`, even `Array.get!` / `SMap.size`
  -- are unresolvable), so the old probe fails to elaborate. The constants themselves are still present
  -- (every project decl resolves via `env.find?`); only that surface API is missing. The `moduleData`
  -- + `Array` path used here stays available. A "project" declaration is one whose defining MODULE
  -- lies under a project namespace, so a root-namespace decl like PFR's `weak_PFR` (defined in module
  -- `PFR.WeakPFR`) still counts.
  let isProjMod (m : Name) : Bool := prefixes.any (fun p => p.isPrefixOf m)
  let mut projNames : NameSet := {{}}
  for (m, md) in mods.zip modData do
    if isProjMod m then
      for ci in md.constants do
        if !ci.name.isInternalDetail then projNames := projNames.insert ci.name
  let mut count := 0
  for (m, md) in mods.zip modData do
    if isProjMod m then
      for ci in md.constants do
        let n := ci.name
        if !n.isInternalDetail then
          let mut s : NameSet := {{}}
          for c in ci.type.getUsedConstants do
            if projNames.contains c && c != n then s := s.insert c
          if let some v := ci.value? then
            for c in v.getUsedConstants do
              if projNames.contains c && c != n then s := s.insert c
          count := count + 1
          IO.println (s!"{{n}} :: " ++ String.intercalate " " (s.toList.map (·.toString)))
  IO.eprintln s!"[claimgraph dep-report] {{count}} declarations"
"""


def _root_modules(project: Path) -> list[str]:
    """The project's importable library roots: a top-level ``X.lean`` that has a sibling ``X/`` module
    directory (Lake's convention for a library named ``X``).

    This skips top-level scratch scripts -- e.g. a ``Final.lean`` that just ``import``s the library and
    prints axioms -- which are not importable library modules and would break the probe with
    ``unknown module prefix``. Falls back to every top-level stem if none has a sibling directory.
    """
    stems = sorted(p.stem for p in project.glob("*.lean"))
    roots = [s for s in stems if (project / s).is_dir()]
    return roots or stems


def _namespace_prefixes(lean_names: list[str]) -> list[str]:
    """The top-level namespace component of each Lean FQN (e.g. ``IGL.foo`` -> ``IGL``)."""
    return sorted({name.split(".", 1)[0] for name in lean_names if name})


def render_probe(roots: list[str], prefixes: list[str]) -> str:
    """Render the extractor metaprogram for a project's root modules and namespaces."""
    imports = "\n".join(f"import {r}" for r in roots)
    prefix_lits = ", ".join("`" + p for p in prefixes)
    return _LEAN_TEMPLATE.format(imports=imports, prefixes=prefix_lits)


def parse_dep_report(text: str) -> dict[str, list[str]]:
    """Parse the ``NAME :: dep1 dep2 ...`` lines into ``{fqn: [direct project deps]}``."""
    out: dict[str, list[str]] = {}
    for line in text.splitlines():
        if " :: " not in line:
            continue
        name, deps = line.split(" :: ", 1)
        out[name.strip()] = [d for d in deps.split() if d]
    return out


def extract_lean_deps(
    project: str | Path,
    lean_names: list[str],
    lake_bin: str | None = None,
) -> dict[str, list[str]] | None:
    """Run the extractor against a built project; return ``{fqn: [direct deps]}`` or ``None``.

    Returns ``None`` if the project cannot be probed (no lake, no root module, a build error). The
    project must already build: this reads the elaborated environment, it does not compile.
    """
    project = Path(project)
    roots = _root_modules(project)
    prefixes = _namespace_prefixes(lean_names)
    if not roots or not prefixes:
        return None
    probe = render_probe(roots, prefixes)
    lake = lake_bin or os.environ.get("CKC_LAKE") or "lake"
    with tempfile.NamedTemporaryFile("w", suffix=".lean", delete=False) as fh:
        fh.write(probe)
        probe_path = fh.name
    try:
        proc = subprocess.run(
            [lake, "env", "lean", probe_path],
            cwd=project,
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    finally:
        os.unlink(probe_path)
    if proc.returncode != 0 and not proc.stdout.strip():
        return None
    if re.search(r"error:|unknown (identifier|constant)", proc.stdout + proc.stderr):
        # A name/build error: the raw graph would be wrong, so refuse rather than mislead.
        return None
    return parse_dep_report(proc.stdout)


def collapse_to_nodes(
    raw: dict[str, list[str]], lean_to_node: dict[str, str]
) -> set[tuple[str, str]]:
    """Collapse the raw Lean constant graph onto claim nodes.

    From each node's Lean declaration we walk the constant graph, passing *through* project
    declarations that are not themselves claim nodes (helper lemmas), and stop at the first node we
    reach. The result is the node-to-node logical dependency graph Lean actually witnesses.
    """
    node_leans = set(lean_to_node)
    edges: set[tuple[str, str]] = set()
    for start in node_leans:
        src = lean_to_node[start]
        seen: set[str] = set()
        stack = list(raw.get(start, []))
        while stack:
            c = stack.pop()
            if c in seen:
                continue
            seen.add(c)
            if c in node_leans and c != start:
                tgt = lean_to_node[c]
                if tgt != src:
                    edges.add((src, tgt))
            else:
                stack.extend(raw.get(c, []))
    return edges


@dataclass
class DepGrounding:
    """The result of grounding asserted edges against the Lean dependency graph."""

    confirmed: set[tuple[str, str]] = field(default_factory=set)  # asserted and real
    missing: set[tuple[str, str]] = field(default_factory=set)    # real, never asserted
    spurious: set[tuple[str, str]] = field(default_factory=set)   # asserted, no real Lean path
    grounded_nodes: set[str] = field(default_factory=set)         # nodes with a Lean reading


def compare_edges(
    real: set[tuple[str, str]],
    asserted: set[tuple[str, str]],
    grounded_nodes: set[str],
) -> DepGrounding:
    """Compare real (Lean-grounded) edges with asserted ones, restricted to grounded sources.

    Only edges whose *source* node is grounded (has a Lean reading) can be judged: if Lean never saw
    the source, we cannot say its asserted edges are spurious. This keeps the verdict honest.
    """
    judgeable = {(s, t) for (s, t) in asserted if s in grounded_nodes}
    return DepGrounding(
        confirmed=real & judgeable,
        missing=real - asserted,
        spurious=judgeable - real,
        grounded_nodes=grounded_nodes,
    )


def asserted_edges(graph) -> set[tuple[str, str]]:
    """The hand-authored logical dependency edges (``Depends-On`` / ``Assumes``) of a graph."""
    return {
        (e.source, e.target)
        for e in graph.edges
        if e.relation in DEPENDENCY_RELATIONS
    }


def lean_to_node_map(graph) -> dict[str, str]:
    """Map each node's Lean FQN(s) to the node id (for collapsing the raw graph)."""
    out: dict[str, str] = {}
    for n in graph.nodes.values():
        for fqn in n.lean:
            out[fqn] = n.id
    return out
