import copy

import pytest

from graph.builder import load_master_records
from graph.validation import check_relation, errors, promote_edge, validate_records


@pytest.fixture(scope="module")
def records():
    return load_master_records()


def test_master_graph_is_valid(records):
    assert errors(validate_records(records)) == []


def test_every_edge_has_provenance(records):
    for e in records["edges"]:
        assert e["evidence"], e["id"]
        for ev in e["evidence"]:
            assert ev["supporting_source"] and ev["doi_or_url"] and ev["location"] and ev["basis"]
        assert e["explanation"]


def test_papers_have_required_metadata(records):
    for n in records["nodes"]:
        if n["type"] == "PAPER":
            assert n["doi"] and n["abstract"] and n["authors"] and n["year"]
            assert n["participant_id"].startswith("P")


def test_duplicate_edges_detected(records):
    bad = copy.deepcopy(records)
    dup = copy.deepcopy(next(e for e in bad["edges"] if e["type"] == "SHARES_PRINCIPLE"))
    dup["id"] = "E999"
    dup["source"], dup["target"] = dup["target"], dup["source"]  # symmetric duplicate in reverse order
    bad["edges"].append(dup)
    msgs = [i.message for i in errors(validate_records(bad))]
    assert any("duplicate of edge" in m for m in msgs)


def test_invalid_relationship_type_rejected(records):
    bad = copy.deepcopy(records)
    bad["edges"][0]["type"] = "INSPIRED_BY"
    assert any("unknown relationship type" in i.message for i in errors(validate_records(bad)))


def test_invalid_signature_rejected(records):
    nodes = {n["id"]: n for n in records["nodes"]}
    probs = check_relation("CITES", nodes["PAPER_SAITOUNEI1987"], nodes["METH_NEIGHBOR_JOINING"])
    assert any("not allowed" in p for p in probs)


def test_temporally_impossible_direction_rejected(records):
    nodes = {n["id"]: n for n in records["nodes"]}
    probs = check_relation("CITES", nodes["PAPER_SAITOUNEI1987"], nodes["PAPER_NITATIKONDA2011"])
    assert any("invalid direction" in p for p in probs)
    assert check_relation("CITES", nodes["PAPER_NITATIKONDA2011"], nodes["PAPER_SAITOUNEI1987"]) == []


def test_missing_evidence_rejected(records):
    bad = copy.deepcopy(records)
    bad["edges"][0]["evidence"] = []
    assert any("provenance" in i.message for i in errors(validate_records(bad)))


def test_ai_proposed_edge_cannot_be_verified_without_human(records):
    bad = copy.deepcopy(records)
    e = bad["edges"][0]
    e["proposed_by"] = "ai"
    e["status"] = "VERIFIED"
    e.pop("verified_by", None)
    assert any("human verifier" in i.message for i in errors(validate_records(bad)))


def test_promotion_requires_named_reviewer_and_evidence():
    edge = {"id": "X", "status": "AI_PROPOSED", "evidence": [{"supporting_source": "s"}]}
    with pytest.raises(ValueError):
        promote_edge(edge, reviewer="  ")
    with pytest.raises(ValueError):
        promote_edge({**edge, "evidence": []}, reviewer="Dr Reviewer")
    out = promote_edge(edge, reviewer="Dr Reviewer")
    assert out["status"] == "VERIFIED" and out["verified_by"] == "Dr Reviewer"
    assert edge["status"] == "AI_PROPOSED"  # original untouched


def test_hidden_connection_not_in_master_graph(records):
    pair = {"PAPER_RATNASAMY1999", "PAPER_SAITOUNEI1987"}
    for e in records["edges"]:
        assert {e["source"], e["target"]} != pair
