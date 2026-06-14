"""Correctness tests for the ClaimGraph computed views, against the IGL worked-trace fixture."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from claimgraph import affected, build
from claimgraph.emit import to_dict

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "igl"
SCHEMA = Path(__file__).resolve().parent.parent / "schema" / "claimgraph.schema.json"


@pytest.fixture(scope="module")
def graph():
    return build(
        fixture=str(EXAMPLES / "igl.commits"),
        claims=str(EXAMPLES / "claims.toml"),
    )


def test_effective_status_demotes_to_axiomatised(graph):
    """approxError is machine-checked itself but Depends-On an axiomatised node (#print axioms)."""
    node = graph.nodes["IGL.approxError"]
    assert node.status == "math.machine-checked"
    assert node.effective_status == "math.axiomatised"
    assert node.weakest_dep == "IGL.expSumRank_logBound"


def test_closes_promotes_the_conjecture(graph):
    """formalize(fubini) Closes the master-formula conjecture, which inherits machine-checked."""
    assert graph.nodes["master-formula"].status == "math.machine-checked"


def test_disproves_breaks_the_target(graph):
    assert graph.nodes["naive-separable"].status == "math.disproved"


def test_dependent_of_broken_node_is_in_question(graph):
    """compensation keeps its own status but is flagged in-question, not itself disproved."""
    node = graph.nodes["IGL.compensatedFactorization"]
    assert node.status == "math.proved-informal"
    assert node.effective_status == "math.proved-informal"
    assert node.in_question is True


def test_affected(graph):
    assert affected(graph, "naive-separable") == ["IGL.compensatedFactorization"]


def test_refute_event_does_not_absorb_status(graph):
    """The refute(separability) event scope must not become a disproved claim."""
    assert graph.nodes["refute:separability"].status is None


def test_science_thread_not_replicated(graph):
    assert graph.nodes["tensor-rank-helps"].status == "sci.not-replicated"


def test_output_validates_against_schema(graph):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA.read_text())
    jsonschema.validate(to_dict(graph), schema)


# --- the Four Colour Theorem showcase fixture -----------------------------------------------------

FOUR_COLOR = Path(__file__).resolve().parent.parent / "examples" / "four-color"


@pytest.fixture(scope="module")
def fct():
    return build(
        fixture=str(FOUR_COLOR / "four-color.commits"),
        claims=str(FOUR_COLOR / "claims.toml"),
    )


def test_fct_final_theorem_machine_checked(fct):
    assert fct.nodes["four-color"].status == "math.machine-checked"


def test_fct_refuted_proofs_are_disproved(fct):
    assert fct.nodes["kempe"].status == "math.disproved"
    assert fct.nodes["tait"].status == "math.disproved"


def test_fct_computer_assisted_proof_is_axiomatised(fct):
    assert fct.nodes["appel-haken"].status == "math.axiomatised"


def test_fct_proof_commits_assert_their_scope(fct):
    """A proof(...) that Closes/Assumes other claims must still assert its own scoped claim,
    not collapse into a synthetic 'proof:<scope>' event node."""
    assert "appel-haken" in fct.nodes and "rsst" in fct.nodes
    assert not any(nid.startswith("proof:") for nid in fct.nodes)
