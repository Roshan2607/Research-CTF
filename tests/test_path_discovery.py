import pytest

from challenge import paths
from graph.alternative_paths import diverse_paths, path_similarity
from graph.application_discovery import NotDefensibleError, build_report
from graph.builder import build_graph, paper_projection
from graph.path_discovery import discover_paths, path_exists
from graph.pipeline import run_pipeline
from graph.relationship_explainer import as_proposed_edge, explain_pair

BASE, TARGET = "PAPER_RATNASAMY1999", "PAPER_SAITOUNEI1987"


@pytest.fixture(scope="module")
def g():
    return build_graph()


@pytest.fixture(scope="module")
def canon():
    return paths.read_json(paths.CANONICAL_PATH)


def test_canonical_path_exists_in_organiser_graph(g, canon):
    assert canon["path"][0] == BASE and canon["path"][-1] == TARGET
    assert path_exists(g, canon["path"])
    for tr in canon["transitions"]:
        for s, t, rel in tr["supporting_edges"]:
            data = g.get_edge_data(*sorted((s, t)) if rel in ("SHARES_PRINCIPLE", "ANALOGOUS_PROBLEM") else (s, t))
            assert rel in data and data[rel]["status"] == "VERIFIED"


def test_canonical_path_retrievable_by_stage1(g, canon):
    found = [p.nodes for p in discover_paths(g, BASE, TARGET)]
    assert canon["path"] in found


def test_alternative_paths_independently_represented(g, canon):
    alts = paths.read_json(paths.ALTERNATIVE_PATHS)["paths"]
    assert 2 <= len(alts) <= 4
    seen = {tuple(canon["path"])}
    for a in alts:
        assert tuple(a["path"]) not in seen, "alternative duplicates another path"
        seen.add(tuple(a["path"]))
        assert a["verification_status"] == "VERIFIED"
        assert path_exists(g, a["path"])
        assert a["path"][0] == BASE and a["path"][-1] == TARGET


def test_hidden_connection_not_traversable(g):
    pg = paper_projection(g)
    assert not pg.has_edge(BASE, TARGET)
    assert not g.has_edge(BASE, TARGET) and not g.has_edge(TARGET, BASE)
    # stored only in the protected answer key
    fa = paths.read_json(paths.FINAL_ANSWER)
    assert {fa["hidden_connection"]["source"], fa["hidden_connection"]["target"]} == {BASE, TARGET}


def test_stage1_only_uses_verified_edges(g):
    verified_ids = {d["id"] for _, _, d in g.edges(data=True) if d["status"] == "VERIFIED"}
    for p in discover_paths(g, BASE, TARGET):
        assert p.edge_ids() <= verified_ids


def test_relevance_pruning_removes_off_topic_papers(g):
    for p in discover_paths(g, BASE, TARGET, relevance_pruning=True):
        assert "PAPER_DEMERS1987" not in p.nodes and "PAPER_CANDES2006" not in p.nodes


def test_stage2_produces_diverse_routes(g):
    sel = diverse_paths(g, BASE, TARGET, k=4)
    assert len(sel) >= 3
    inter = [set(d.path.nodes[1:-1]) for d in sel]
    assert len({frozenset(i) for i in inter}) == len(inter)
    # the machine-learning route (ALT-B) is found despite being lower-scored than the tomography routes
    assert any("PAPER_CHOI2011" in d.path.nodes for d in sel)
    assert path_similarity(sel[0].path, sel[1].path) < 1.0


def test_stage3_rediscovers_hidden_principle_but_does_not_verify_it(g):
    ex = explain_pair(g, BASE, TARGET)
    sp = [e for e in ex if e.pattern == "shared_principle"]
    assert sp and sp[0].principle == "PRIN_LEAF_ONLY_TREE"
    assert sp[0].cross_domain and not sp[0].direct_edge
    assert all(e.status == "AI_PROPOSED" for e in ex), "algorithmic relations must never be auto-verified"
    assert as_proposed_edge(sp[0], g)["status"] == "AI_PROPOSED"


def test_stage3_marks_existing_relation_verified(g):
    ex = explain_pair(g, "PAPER_NITATIKONDA2011", TARGET)
    assert any(e.status == "VERIFIED" for e in ex if e.relation_type == "ANALOGOUS_PROBLEM")


def test_stage4_requires_defensible_relation(g):
    ex = [e for e in explain_pair(g, BASE, TARGET) if e.pattern == "shared_principle"][0]
    reports = build_report(g, ex, paths.read_json(paths.FINAL_ANSWER))
    assert reports[0].application == "APP_NEXTSTRAIN"
    assert reports[0].lineage_claim == "none"
    assert reports[0].research_usage and reports[0].implementation and reports[0].limitations
    ex.defensible = False
    with pytest.raises(NotDefensibleError):
        build_report(g, ex)


def test_full_pipeline_runs():
    res = run_pipeline(BASE, TARGET, paths.read_json(paths.FINAL_ANSWER))
    assert res.stage1 and res.stage2 and res.stage3 and res.stage4
    assert res.stage4_skipped_reason is None
