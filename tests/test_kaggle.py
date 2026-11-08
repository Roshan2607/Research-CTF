"""The Kaggle metric must agree with the local scorer (the source of truth)."""
import pandas as pd
import pytest

from challenge import paths
from challenge.participant_data import participant_infos
from scoring.graph_scorer import GraphScorer, parse_submission
from scoring.kaggle_format import edges_to_kaggle, kaggle_to_edges, load_candidates
from scoring.kaggle_metric import ParticipantVisibleError, score
from scoring.reference import build_reference_table


@pytest.fixture(scope="module")
def solution():
    rows = build_reference_table(
        paths.read_json(paths.MASTER_GRAPH),
        paths.read_json(paths.SCORING_POLICY),
        paths.read_json(paths.DECOYS),
        paths.read_json(paths.INJECTIONS),
        paths.load_config(),
    )
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def scorer():
    return GraphScorer.from_answer_key()


@pytest.mark.parametrize("name", ["initial", "revised"])
def test_kaggle_metric_matches_local_scorer(name, solution, scorer):
    text = (paths.SAMPLES_DIR / f"sample_submission_{name}.csv").read_text(encoding="utf-8")
    parsed = parse_submission(text, participant_infos())
    assert parsed.ok
    local = scorer.score(parsed.edges)
    sub, unknown = edges_to_kaggle(parsed.edges)
    assert unknown == []
    sol = solution[["id", "label", "fp_weight", "Usage"]]
    assert score(sol.drop(columns="Usage"), sub, "id") == pytest.approx(local.metrics["all"].weighted_f1)
    for usage, split in (("Public", "public"), ("Private", "private")):
        part = sol[sol.Usage == usage].drop(columns="Usage")
        assert score(part, sub[sub.id.isin(part.id)], "id") == pytest.approx(local.metrics[split].weighted_f1)


def test_public_candidate_file_matches_solution_ids(solution):
    cand = load_candidates()
    assert list(cand["id"]) == list(solution["id"])
    assert set(cand.columns) == {"id", "source_id", "target_id", "relationship_type"}


def test_public_kaggle_files_leak_nothing():
    for f in ("candidate_edges.csv", "sample_submission.csv"):
        df = pd.read_csv(paths.KAGGLE_DIR / f)
        assert not {"label", "fp_weight", "Usage", "edge_class"} & set(df.columns)
    assert (pd.read_csv(paths.KAGGLE_DIR / "sample_submission.csv")["predicted"] == 0).all()


def test_roundtrip_conversion():
    edges = [("P12", "P05", "CITES"), ("P12", "P08", "SHARES_PRINCIPLE")]
    sub, _ = edges_to_kaggle(edges)
    back = set(kaggle_to_edges(sub))
    assert back == {("P12", "P05", "CITES"), ("P08", "P12", "SHARES_PRINCIPLE")}


def test_metric_rejects_bad_submissions(solution):
    sol = solution[["id", "label", "fp_weight"]]
    with pytest.raises(ParticipantVisibleError):
        score(sol, pd.DataFrame({"id": sol.id, "pred": 0}), "id")
    with pytest.raises(ParticipantVisibleError):
        score(sol, pd.DataFrame({"id": sol.id[:-1], "predicted": 0}), "id")
    with pytest.raises(ParticipantVisibleError):
        score(sol, pd.DataFrame({"id": sol.id, "predicted": 2}), "id")
    assert score(sol, pd.DataFrame({"id": sol.id, "predicted": 0}), "id") == 0.0
