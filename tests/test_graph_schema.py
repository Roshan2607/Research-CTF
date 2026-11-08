from graph.builder import build_graph, load_master_records
from graph.schema import (
    RELATIONS,
    SUBMITTABLE_RELATIONS,
    SYMMETRIC_RELATIONS,
    ClaimKind,
    NodeType,
    Status,
    canonical_pair,
    data_dictionary,
    edge_key,
)

REQUIRED_RELATIONS = {
    "CITES",
    "ADDRESSES",
    "USES_METHOD",
    "EXTENDS",
    "OPERATIONALISES",
    "SHARES_PRINCIPLE",
    "ANALOGOUS_PROBLEM",
    "APPLICATION_OF",
}


def test_vocabulary_contains_required_relations():
    assert REQUIRED_RELATIONS <= set(RELATIONS)


def test_every_relation_has_direction_and_meaning():
    for spec in RELATIONS.values():
        assert spec.meaning and spec.direction and spec.example
        assert spec.signatures


def test_claim_kinds_distinguish_citation_from_method_and_concept():
    assert RELATIONS["CITES"].claim_kind is ClaimKind.BIBLIOGRAPHIC
    assert RELATIONS["USES_METHOD"].claim_kind is ClaimKind.METHODOLOGICAL
    assert RELATIONS["EXTENDS"].claim_kind is ClaimKind.METHODOLOGICAL
    assert RELATIONS["SHARES_PRINCIPLE"].claim_kind is ClaimKind.CONCEPTUAL
    assert RELATIONS["ANALOGOUS_PROBLEM"].claim_kind is ClaimKind.INTERPRETIVE


def test_all_node_types_in_master_graph_are_valid():
    recs = load_master_records()
    valid = {t.value for t in NodeType}
    types = {n["type"] for n in recs["nodes"]}
    assert types <= valid
    assert types == valid, "graph should be heterogeneous and use every node type"


def test_all_relationship_types_in_master_graph_are_valid():
    recs = load_master_records()
    assert {e["type"] for e in recs["edges"]} <= set(RELATIONS)
    assert {e["status"] for e in recs["edges"]} <= {s.value for s in Status}


def test_corpus_size_and_domains():
    recs = load_master_records()
    papers = [n for n in recs["nodes"] if n["type"] == "PAPER"]
    assert 12 <= len(papers) <= 15
    assert len({p["domain"] for p in papers}) >= 3


def test_symmetric_canonicalisation():
    assert canonical_pair("P09", "P02", "SHARES_PRINCIPLE") == ("P02", "P09")
    assert canonical_pair("P09", "P02", "CITES") == ("P09", "P02")
    assert edge_key("P09", "P02", "ANALOGOUS_PROBLEM") == edge_key("P02", "P09", "ANALOGOUS_PROBLEM")
    assert SYMMETRIC_RELATIONS == {"SHARES_PRINCIPLE", "ANALOGOUS_PROBLEM"}


def test_edge_direction_preserved_in_built_graph():
    g = build_graph()
    # Ni & Tatikonda (2011) cites Ratnasamy & McCanne (1999), never the reverse.
    assert g.has_edge("PAPER_NITATIKONDA2011", "PAPER_RATNASAMY1999", key="CITES")
    assert not g.has_edge("PAPER_RATNASAMY1999", "PAPER_NITATIKONDA2011", key="CITES")


def test_participant_dictionary_only_contains_submittable_paper_relations():
    rows = data_dictionary(participant=True)
    assert {r["relationship_type"] for r in rows} == set(SUBMITTABLE_RELATIONS)
    for r in rows:
        assert r["allowed_signatures"]
    # examples must not mention corpus identifiers
    text = " ".join(r["example"] + r["meaning"] for r in rows)
    for i in range(1, 16):
        assert f"P{i:02d}" not in text
