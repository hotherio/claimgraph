"""Read a Lean Blueprint as a ClaimGraph, and ground its \\leanok against the kernel.

A blueprint node carries the same information CKC tracks: a stable id (its ``\\label``), one or more
Lean declarations (``\\lean``), a "formalized" claim (``\\leanok``/``\\mathlibok``), and dependency
edges (``\\uses``). We read those directly so nobody re-authors anything, then optionally ground each
node against ``#print axioms`` via the existing ``axiom-report`` bridge.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .model import ClaimGraph, Edge, Node

MC = "math.machine-checked"
AXIOMATISED = "math.axiomatised"
OPEN = "math.open"
PROVED_INFORMAL = "math.proved-informal"

# blueprint environments we treat as claim nodes, and the CKC kind they map to.
_ENVS = {
    "definition": "definition",
    "theorem": "theorem",
    "lemma": "theorem",
    "proposition": "theorem",
    "corollary": "theorem",
    "conjecture": "conjecture",
}
_ENV_RE = re.compile(
    r"\\begin\{(" + "|".join(_ENVS) + r")\}(.*?)\\end\{\1\}", re.DOTALL
)
_MACRO_STRIP = re.compile(
    r"\\(label|lean|uses|proves|mathlibok|discussion)\{[^}]*\}|\\(leanok|notready)\b|^\s*\[[^\]]*\]"
)


def _macro(block: str, name: str) -> str | None:
    m = re.search(r"\\" + name + r"\{([^}]*)\}", block)
    return m.group(1) if m else None


def _items(value: str | None) -> list[str]:
    return [p.strip() for p in value.split(",")] if value else []


@dataclass
class BlueprintNode:
    label: str
    lean: list[str] = field(default_factory=list)
    leanok: bool = False
    mathlibok: bool = False
    uses: list[str] = field(default_factory=list)
    proves: list[str] = field(default_factory=list)
    kind: str = "theorem"
    statement: str | None = None


def _strip_comments(text: str) -> str:
    """Drop LaTeX line comments so macro names mentioned in prose/comments are not parsed."""
    return re.sub(r"(?<!\\)%.*", "", text)


# The "macro head": the leading run of an environment body made only of macros
# (\lean{}, \leanok, \uses{}, ...), a [title], and whitespace, before any prose. \leanok mentioned
# later in prose (paper-igl writes "(not \leanok)") must not be read as the formalization flag.
_HEAD_RE = re.compile(r"^\s*(?:\[[^\]]*\]|\\[a-zA-Z]+(?:\{[^}]*\})?|\s)*")
_LEANOK_RE = re.compile(r"\\leanok(?![a-zA-Z])")
_MATHLIBOK_RE = re.compile(r"\\mathlibok(?![a-zA-Z])")


def parse_blueprint_tex(text: str) -> list[BlueprintNode]:
    """Parse blueprint nodes out of a content.tex fragment (the universal, version-proof path)."""
    text = _strip_comments(text)
    nodes: list[BlueprintNode] = []
    for env, block in _ENV_RE.findall(text):
        label = _macro(block, "label")
        if not label:
            continue
        title = re.match(r"\s*\[([^\]]*)\]", block)
        head = _HEAD_RE.match(block).group(0)
        body = _MACRO_STRIP.sub("", block)
        body = re.sub(r"\s+", " ", body).strip()
        nodes.append(
            BlueprintNode(
                label=label.strip(),
                lean=_items(_macro(block, "lean")),
                leanok=bool(_LEANOK_RE.search(head)),
                mathlibok=bool(_MATHLIBOK_RE.search(head)),
                uses=_items(_macro(block, "uses")),
                proves=_items(_macro(block, "proves")),
                kind=_ENVS[env],
                statement=(title.group(1).strip() if title else (body[:140] or None)),
            )
        )
    return nodes


def parse_blueprint_json(data: dict | list) -> list[BlueprintNode]:
    """Parse a LeanArchitect ``blueprintJson`` export (name/latexLabel/statement/proof NodeParts)."""
    records = data["nodes"] if isinstance(data, dict) and "nodes" in data else data
    out: list[BlueprintNode] = []
    for r in records:
        stmt, proof = r.get("statement") or {}, r.get("proof") or {}
        uses = list(stmt.get("usesLabels", [])) + list(proof.get("usesLabels", []))
        out.append(
            BlueprintNode(
                label=r.get("latexLabel") or r.get("name", ""),
                lean=[r["name"]] if r.get("name") else [],
                leanok=bool(proof.get("leanok", proof)) and not r.get("notReady", False),
                uses=[u for u in uses if u],
                kind="definition" if (r.get("latexEnv") == "definition") else "theorem",
                statement=r.get("title") or (stmt.get("text") or "")[:140] or None,
            )
        )
    return out


def read_blueprint(path: str | Path) -> list[BlueprintNode]:
    p = Path(path)
    if p.suffix == ".json":
        return parse_blueprint_json(json.loads(p.read_text(encoding="utf-8")))
    return parse_blueprint_tex(p.read_text(encoding="utf-8"))


# --- kernel grounding (optional) ------------------------------------------------------------------

def run_axiom_report(
    project: str | Path | None,
    tex: str | Path | None = None,
    names: list[str] | None = None,
    bin_path: str | None = None,
) -> dict[str, str] | None:
    """Return ``{lean_fqn: clean|sorryAx|axiom}`` from ``axiom-report``, or ``None`` if unavailable.

    Reuses the lean-math ``axiom-report`` bridge (same as ``ckc_axiom_check``); the binary is taken
    from ``bin_path``, then ``$CKC_AXIOM_REPORT``, then ``axiom-report`` on PATH. Pass a ``.tex`` for
    the regular blueprint path, or explicit ``names`` (e.g. from a JSON export).
    """
    report = bin_path or os.environ.get("CKC_AXIOM_REPORT") or "axiom-report"
    cmd = [report]
    if project:
        cmd.append(str(project))
    if tex:
        cmd += ["--tex", str(tex)]
    cmd += list(names or [])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except (FileNotFoundError, OSError):
        return None
    if not proc.stdout.strip():
        return None
    return parse_axiom_report(proc.stdout)


def parse_axiom_report(text: str) -> dict[str, str]:
    """Parse the ``DECLARATION  STATUS  NON-STANDARD AXIOMS`` table into ``{fqn: status}``."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^(\S+)\s+(clean|sorryAx|axiom)\b", line)
        if m and m.group(1) not in ("DECLARATION",) and not set(m.group(1)) <= {"-"}:
            out[m.group(1)] = m.group(2)
    return out


_KERNEL_STATUS = {"clean": MC, "axiom": AXIOMATISED, "sorryAx": OPEN}


def kernel_status_for(node: BlueprintNode, kernel: dict[str, str] | None) -> str | None:
    """Combine a node's Lean declarations' kernel readings into one CKC status (worst wins)."""
    if not kernel or not node.lean:
        return None
    readings = [kernel.get(fqn) for fqn in node.lean if fqn in kernel]
    if not readings:
        return None
    if "sorryAx" in readings:
        return OPEN
    if "axiom" in readings:
        return AXIOMATISED
    return MC


def claimed_status(node: BlueprintNode) -> str | None:
    """The blueprint's *claim*: machine-checked iff \\leanok / \\mathlibok, else no claim."""
    return MC if (node.leanok or node.mathlibok) else None


def blueprint_graph(nodes: list[BlueprintNode], kernel: dict[str, str] | None = None) -> ClaimGraph:
    """Build a ClaimGraph from blueprint nodes, keyed by blueprint label, grounded if kernel given."""
    g = ClaimGraph()
    for bn in nodes:
        n = g.node(bn.label)
        n.kind = bn.kind
        n.statement = bn.statement
        n.lean = bn.lean
        n.claimed = claimed_status(bn)
        n.kernel = kernel_status_for(bn, kernel)
        # working status: kernel reality if known, else the blueprint's own reading.
        if n.kernel is not None:
            n.status = n.kernel
        elif bn.leanok or bn.mathlibok:
            n.status = MC
        elif bn.lean:
            n.status = OPEN
        else:
            # A prose-only node (no \lean): a paper-level concept with no formal obligation. It is
            # NOT "proved-informal" (a definition is not a proof), and -- crucially -- it must not
            # drag a kernel-clean user's validity down, so we leave its status unset.
            n.status = None
        # `\uses` is a COVERAGE edge, not a validity dependency (see model.COVERAGE_RELATIONS):
        # an expository "built on that concept" link, the authority on validity is the kernel.
        for dep in bn.uses:
            g.edges.append(Edge(source=bn.label, target=dep, relation="Uses"))
        for tgt in bn.proves:
            g.edges.append(Edge(source=bn.label, target=tgt, relation="Proves"))
    return g
