import math

import pandas as pd
import pytest

from scoring.graph_scorer import GraphScorer, parse_submission
from scoring.weighted_metrics import Counts, compute, compute_from_rows

W = {"ordinary": 1.0, "decoy_induced": 0.5, "injection_induced": 3.0}


@pytest.fixture(scope="module")
def scorer():
    return GraphScorer.from_answer_key()


def by_class(scorer, cls):
    return sorted(t for t, c in scorer.classes.items() if c == cls)


def csv_of(edges, evidence=""):
    df = pd.DataFrame(edges, columns=["source_id", "target_id", "relationship_type"])
    df["evidence_reference"] = evidence
    return df.to_csv(index=False)


# ---------------------------------------------------------------- metric formula
def test_formula_matches_specification():
    c = Counts(tp=6, fn=4, fp_ordinary=2, fp_decoy=2, fp_injection=1)
    m = compute(c, W)
    wp = 6 / (6 + 2 * 1.0 + 2 * 0.5 + 1 * 3.0)
    r = 6 / 10
    assert math.isclose(m.weighted_precision, wp)
    assert math.isclose(m.recall, r)
    assert math.isclose(m.weighted_f1, 2 * wp * r / (wp + r))


def test_zero_denominators_are_safe():
    m = compute(Counts(), W)
    assert (m.weighted_precision, m.recall, m.weighted_f1) == (0.0, 0.0, 0.0)
    m = compute_from_rows([], [], [])
    assert m.weighted_f1 == 0.0


# ---------------------------------------------------------------- behaviour against the live answer key
def test_perfect_submission_scores_one(scorer):
    r = scorer.score(by_class(scorer, "reference"))
    for split in ("public", "private", "all"):
        assert r.metrics[split].weighted_f1 == pytest.approx(1.0)


def test_correct_edges_increase_score(scorer):
    ref = by_class(scorer, "reference")
    a = scorer.score(ref[:5]).metrics["all"].weighted_f1
    b = scorer.score(ref[:15]).metrics["all"].weighted_f1
    assert 0 < a < b <= 1


def test_missing_edges_reduce_recall_not_precision(scorer):
    ref = by_class(scorer, "reference")
    m = scorer.score(ref[: len(ref) // 2]).metrics["all"]
    assert m.weighted_precision == pytest.approx(1.0)
    assert m.recall < 1.0


def test_unsupported_edges_reduce_precision(scorer):
    ref = by_class(scorer, "reference")
    ordinary = by_class(scorer, "ordinary")
    m = scorer.score(ref + ordinary[:10]).metrics["all"]
    assert m.recall == pytest.approx(1.0)
    assert m.weighted_precision == pytest.approx(len(ref) / (len(ref) + 10))


def test_wrong_relationship_type_is_penalised(scorer):
    # P12 CITES P05 is a reference edge; P12 SHARES_PRINCIPLE P05 is defensible-neutral, so use a pair
    # whose alternative type is classified ordinary.
    good = ("P08", "P09", "CITES")
    wrong = ("P08", "P09", "USES_METHOD")
    assert scorer.classify(good) == "reference"
    assert scorer.classify(wrong) == "ordinary"
    m_good = scorer.score([good]).metrics["all"]
    m_wrong = scorer.score([wrong]).metrics["all"]
    assert m_wrong.weighted_f1 == 0.0 < m_good.weighted_f1


def test_decoy_and_injection_weights_applied(scorer):
    ref = by_class(scorer, "reference")
    ordinary = by_class(scorer, "ordinary")[0]
    decoy = by_class(scorer, "decoy_induced")[0]
    inj = by_class(scorer, "injection_induced")[0]
    wfp = lambda extra: scorer.score(ref + [extra]).metrics["all"].weighted_fp  # noqa: E731
    assert wfp(ordinary) == pytest.approx(1.0)
    assert wfp(decoy) == pytest.approx(0.5)
    assert wfp(inj) == pytest.approx(3.0)
    f = lambda extra: scorer.score(ref + [extra]).metrics["all"].weighted_f1  # noqa: E731
    assert f(decoy) > f(ordinary) > f(inj)


def test_injection_edges_are_the_annotated_ones(scorer):
    assert set(by_class(scorer, "injection_induced")) == {("P04", "P05", "EXTENDS"), ("P08", "P03", "USES_METHOD")}


def test_hidden_pair_is_neutral_for_every_type(scorer):
    for rel in ("SHARES_PRINCIPLE", "ANALOGOUS_PROBLEM"):
        assert scorer.classify(("P05", "P03", rel)) == "neutral"
    r = scorer.score([("P03", "P05", "SHARES_PRINCIPLE")])
    assert r.metrics["all"].weighted_f1 == 0.0 and r.metrics["all"].weighted_fp == 0.0


def test_neutral_edges_do_not_change_score(scorer):
    ref = by_class(scorer, "reference")
    neutral = by_class(scorer, "neutral")
    assert scorer.score(ref).metrics["all"] == scorer.score(ref + neutral).metrics["all"]


def test_accepted_alternative_becomes_reference():
    edge = ("P12", "P05", "EXTENDS")  # neutral initially
    base = GraphScorer.from_answer_key()
    assert base.classify(edge) == "neutral"
    promoted = GraphScorer.from_answer_key(accepted_additions=[edge])
    assert promoted.classify(edge) == "reference"
    assert promoted.score([edge]).metrics["all"].weighted_f1 > 0


def test_scores_stay_in_range(scorer):
    import random

    rnd = random.Random(7)
    universe = list(scorer.classes)
    for _ in range(50):
        sample = rnd.sample(universe, rnd.randint(0, 80))
        for m in scorer.score(sample).metrics.values():
            assert 0.0 <= m.weighted_precision <= 1.0
            assert 0.0 <= m.recall <= 1.0
            assert 0.0 <= m.weighted_f1 <= 1.0


def test_participant_view_is_aggregate_only(scorer):
    view = scorer.score(by_class(scorer, "reference")[:3]).participant_view("public")
    assert set(view) == {"split", "weighted_f1", "weighted_precision", "recall", "edges_scored"}


# ---------------------------------------------------------------- parsing / validation
def test_empty_submission_does_not_crash(scorer):
    p = parse_submission("", scorer.infos)
    assert p.ok and p.edges == []
    p = parse_submission("source_id,target_id,relationship_type\n", scorer.infos)
    assert p.ok and p.edges == []
    assert scorer.score(p.edges).metrics["public"].weighted_f1 == 0.0


def test_duplicates_are_counted_once(scorer):
    text = csv_of([("P12", "P05", "CITES"), ("p12", " P05", "cites"), ("P08", "P12", "SHARES_PRINCIPLE"), ("P12", "P08", "SHARES_PRINCIPLE")])
    p = parse_submission(text, scorer.infos)
    assert p.ok and len(p.edges) == 2
    assert sum("duplicate" in w for w in p.warnings) == 2


def test_unknown_ids_and_types_rejected(scorer):
    p = parse_submission(csv_of([("P99", "P05", "CITES"), ("P12", "P05", "INSPIRED_BY"), ("P12", "P05", "ADDRESSES")]), scorer.infos)
    assert not p.ok and len(p.errors) == 3
    assert any("unknown source_id" in e for e in p.errors)
    assert any("invalid relationship_type" in e for e in p.errors)
    assert any("cannot be submitted" in e for e in p.errors)


def test_invalid_direction_rejected(scorer):
    p = parse_submission(csv_of([("P05", "P12", "CITES")]), scorer.infos)  # 1999 paper cannot cite a 2008/2011 one
    assert not p.ok and "invalid direction" in p.errors[0]
    p = parse_submission(csv_of([("P05", "P05", "SHARES_PRINCIPLE")]), scorer.infos)
    assert not p.ok and "itself" in p.errors[0]


def test_malformed_submissions_rejected(scorer):
    assert not parse_submission("from,to\nP01,P02\n", scorer.infos).ok
    assert not parse_submission('source_id,target_id,relationship_type\n"P01,P02\n', scorer.infos).ok
    too_many = csv_of([("P12", "P05", "CITES")] * 301)
    assert not parse_submission(too_many, scorer.infos, max_rows=300).ok


def test_evidence_reference_is_optional_and_kept(scorer):
    p = parse_submission(csv_of([("P12", "P05", "CITES")], evidence="P12 ref [23]"), scorer.infos)
    assert p.evidence[("P12", "P05", "CITES")] == "P12 ref [23]"
    p = parse_submission("source_id,target_id,relationship_type\nP12,P05,CITES\n", scorer.infos)
    assert p.ok and p.evidence == {}
