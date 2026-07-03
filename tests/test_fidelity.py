"""Tests for per-claim statement-fidelity records and the axiom-without-fidelity audit gate.

The kernel checks the PROOF; nothing checks that a cited axiom's STATEMENT matches its source
paper. A fidelity record in claims.toml says a human did that review; the opt-in
``claimgraph audit --require-fidelity`` gate fails on axiomatised claims that carry none.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

from claimgraph import blueprint as bp
from claimgraph.build import build_graph, seed_registry
from claimgraph.emit import from_dict, to_dict
from claimgraph.model import ClaimGraph
from claimgraph.reconcile import audit, compute_agreement, reconcile

SCHEMA = Path(__file__).resolve().parent.parent / "schema" / "claimgraph.schema.json"

FID = {
    "reviewed": "2026-07-01",
    "paper": "Doe & Roe 2024, Thm 3.2, p.14",
    "evidence": "audits/kernel-bound-fidelity.md",
}

TEX = r"""
\begin{proposition}[Kernel bound]\label{prop:kernel-bound}
  \lean{Demo.kernelBound}
  The Green's kernel admits the cited bound.
\end{proposition}
"""

AXIOMS = (
    "DECLARATION       STATUS  NON-STANDARD AXIOMS\n"
    "----------------  ------  ----\n"
    "Demo.kernelBound  axiom   Demo.kernelBound\n"
)

COMMITS = (
    "formalize(kernel-bound): cite the kernel bound as an axiom\n"
    "\n"
    "Lean: Demo.kernelBound\n"
    "Status: math.axiomatised\n"
)

CLAIMS_TOML = """\
[claims."Demo.kernelBound"]
kind      = "theorem"
statement = "The Green's kernel admits the cited bound."
"""

FIDELITY_TOML = """\
[claims."Demo.kernelBound".fidelity]
reviewed = "2026-07-01"
paper    = "Doe & Roe 2024, Thm 3.2, p.14"
evidence = "audits/kernel-bound-fidelity.md"
"""


# --- seed_registry passthrough ---------------------------------------------------------------------

def test_seed_registry_fidelity_passthrough():
    g = ClaimGraph()
    seed_registry(g, {
        "a": {"kind": "conjecture", "statement": "s", "fidelity": dict(FID)},
        "b": {"kind": "theorem", "statement": "t"},
    })
    assert g.nodes["a"].fidelity == FID
    assert g.nodes["b"].fidelity is None


def test_seed_registry_coerces_toml_dates_and_drops_non_dicts():
    """TOML-native dates become ISO strings (JSON-safe); a non-dict record is dropped."""
    g = ClaimGraph()
    seed_registry(g, {
        "a": {"fidelity": {"reviewed": datetime.date(2026, 7, 1), "paper": "p"}},
        "b": {"fidelity": "not-a-record"},
    })
    assert g.nodes["a"].fidelity == {"reviewed": "2026-07-01", "paper": "p"}
    assert g.nodes["b"].fidelity is None


# --- classification + the audit gate ---------------------------------------------------------------

def _grounded(fidelity: dict | None):
    """A one-axiom blueprint graph reconciled with a registry that may carry a fidelity record."""
    bp_graph = bp.blueprint_graph(bp.parse_blueprint_tex(TEX), bp.parse_axiom_report(AXIOMS))
    entry = {"kind": "theorem", "statement": "The Green's kernel admits the cited bound."}
    if fidelity:
        entry["fidelity"] = fidelity
    commit_graph = build_graph([], registry={"Demo.kernelBound": entry})
    return compute_agreement(reconcile(bp_graph, commit_graph), with_commits=True)


def test_cited_axiom_without_record_is_axiom_without_fidelity():
    g = _grounded(None)
    n = g.nodes["prop:kernel-bound"]
    assert n.kernel == bp.AXIOMATISED
    assert n.agreement == "axiom-without-fidelity"


def test_fidelity_record_survives_reconcile_and_makes_the_axiom_consistent():
    """The registry keys the record by Lean FQN; it must land on the unified blueprint label."""
    g = _grounded(dict(FID))
    n = g.nodes["prop:kernel-bound"]
    assert n.fidelity == FID
    assert n.agreement == "consistent"


def test_audit_gate_fires_only_with_require_fidelity():
    g = _grounded(None)
    assert audit(g) == []                        # default: not a validity gap, existing repos pass
    assert audit(g, strict=True) == []           # --strict is coverage, not fidelity
    assert [n.id for n in audit(g, require_fidelity=True)] == ["prop:kernel-bound"]
    # with the record, the gate passes even when required
    assert audit(_grounded(dict(FID)), require_fidelity=True) == []


# --- serialization ----------------------------------------------------------------------------------

def test_fidelity_round_trips_through_emit():
    g = ClaimGraph()
    g.node("x").fidelity = dict(FID)
    g.node("y")  # unset: the key must be omitted so existing consumers are byte-unchanged
    d = to_dict(g)
    by_id = {n["id"]: n for n in d["nodes"]}
    assert by_id["x"]["fidelity"] == FID
    assert "fidelity" not in by_id["y"]
    assert from_dict(d).nodes["x"].fidelity == FID


def test_fidelity_output_validates_against_schema():
    jsonschema = pytest.importorskip("jsonschema")
    g = _grounded(dict(FID))
    jsonschema.validate(to_dict(g), json.loads(SCHEMA.read_text()))


# --- the CLI flag, end to end -----------------------------------------------------------------------

@pytest.fixture()
def repo_files(tmp_path):
    (tmp_path / "content.tex").write_text(TEX, encoding="utf-8")
    (tmp_path / "axioms.txt").write_text(AXIOMS, encoding="utf-8")
    (tmp_path / "history.commits").write_text(COMMITS, encoding="utf-8")
    (tmp_path / "claims.toml").write_text(CLAIMS_TOML, encoding="utf-8")
    (tmp_path / "claims-fidelity.toml").write_text(CLAIMS_TOML + "\n" + FIDELITY_TOML,
                                                   encoding="utf-8")
    return tmp_path


def _audit(files, claims: str, *flags):
    from typer.testing import CliRunner

    from claimgraph.cli import app
    return CliRunner().invoke(app, [
        "audit", str(files / "content.tex"),
        "-f", str(files / "history.commits"),
        "-c", str(files / claims),
        "--axioms", str(files / "axioms.txt"),
        *flags,
    ])


def test_cli_audit_passes_by_default_without_fidelity_records(repo_files):
    res = _audit(repo_files, "claims.toml")
    assert res.exit_code == 0, res.output
    assert "ok: no honesty gaps." in res.output


def test_cli_audit_require_fidelity_fails_on_unreviewed_axiom(repo_files):
    res = _audit(repo_files, "claims.toml", "--require-fidelity")
    assert res.exit_code == 1
    assert "axiom-without-fidelity: prop:kernel-bound" in res.output


def test_cli_audit_require_fidelity_passes_with_the_record(repo_files):
    res = _audit(repo_files, "claims-fidelity.toml", "--require-fidelity")
    assert res.exit_code == 0, res.output
    assert "fidelity gaps" in res.output  # the ok message names what was checked
