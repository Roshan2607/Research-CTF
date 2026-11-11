from __future__ import annotations

import io
import pandas as pd
import pytest

from scripts.evaluate_submissions import evaluate_submission, evaluate_google_form_csv


def test_evaluate_submission_perfect_level1():
    graph = "source_id,target_id,relationship_type\nP02,P05,CITES\nP13,P05,CITES\nP13,P02,CITES\nP02,P05,ANALOGOUS_PROBLEM\nP05,P13,ANALOGOUS_PROBLEM\n"
    res = evaluate_submission("TEAM_TEST", level=1, flag_answer="receivers", graph_csv=graph)
    assert res.flag_correct is True
    assert res.flag_points == 1000.0
    assert len(res.correct_edges) == 5
    assert res.total_reference_count == 5
    assert res.base_graph_points == 1500.0
    assert len(res.injection_hits) == 0
    assert len(res.decoy_hits) == 0
    assert res.final_graph_points == 1500.0
    assert res.total_score == 2500.0


def test_evaluate_submission_injection_penalty():
    # INJ-1 hosted on P09 (Level 2) induces P04 EXTENDS P05
    graph = "source_id,target_id,relationship_type\nP02,P05,CITES\nP04,P05,EXTENDS\n"
    res = evaluate_submission("TEAM_INJ", level=2, flag_answer="phylogenetics", graph_csv=graph, injection_penalty_pts=300.0)
    assert res.flag_correct is True
    assert res.flag_points == 1200.0
    assert len(res.injection_hits) == 1
    assert res.injection_hits[0]["injection_id"] == "INJ-1"
    assert res.injection_penalty == 300.0


def test_evaluate_submission_discovery_bounty():
    graph = "source_id,target_id,relationship_type\nP02,P05,CITES\nP13,P05,CITES\nP13,P02,CITES\nP02,P05,ANALOGOUS_PROBLEM\nP05,P13,ANALOGOUS_PROBLEM\nP05,P02,SHARES_PRINCIPLE\n"
    res = evaluate_submission(
        "TEAM_DISC",
        level=1,
        flag_answer="receivers",
        graph_csv=graph,
        accepted_additions=[("P05", "P02", "SHARES_PRINCIPLE")],
        discovery_bounty_pts=250.0,
    )
    assert res.flag_correct is True
    assert len(res.discovery_bounty_edges) == 1
    assert res.discovery_bounty_points == 250.0
    assert res.final_graph_points == 1750.0
    assert res.total_score == 2750.0


def test_evaluate_submission_50pct_accuracy_floor():
    # Only 1 correct edge out of 5 reference edges in Level 1 = 20% accuracy (< 50% floor)
    graph_weak = "source_id,target_id,relationship_type\nP02,P05,CITES\n"
    res_weak = evaluate_submission("TEAM_WEAK", level=1, flag_answer="receivers", graph_csv=graph_weak, enforce_50pct_floor=True)
    assert res_weak.accuracy_pct == 20.0
    assert res_weak.meets_50pct_threshold is False
    assert res_weak.final_graph_points == 0.0  # Zeroed because < 50%
    assert res_weak.flag_points == 1000.0  # Flag points preserved!
    assert res_weak.total_score == 1000.0

    # 3 correct edges out of 5 reference edges in Level 1 = 60% accuracy (>= 50% floor)
    graph_strong = "source_id,target_id,relationship_type\nP02,P05,CITES\nP13,P05,CITES\nP13,P02,CITES\n"
    res_strong = evaluate_submission("TEAM_STRONG", level=1, flag_answer="receivers", graph_csv=graph_strong, enforce_50pct_floor=True)
    assert res_strong.accuracy_pct == 60.0
    assert res_strong.meets_50pct_threshold is True
    assert res_strong.final_graph_points == 900.0  # 1500 * 0.60
    assert res_strong.total_score == 1900.0


def test_evaluate_submission_with_mock_judge():
    from judging.judge import Verdict

    class MockJudge:
        def judge_batch(self, edges):
            return {e.edge_hash: Verdict("supported", "Verified citation") for e in edges}

    # P05 -> P02 SHARES_PRINCIPLE is ordinary / novel candidate
    graph = "source_id,target_id,relationship_type,evidence_reference\nP02,P05,CITES,ev1\nP05,P02,SHARES_PRINCIPLE,Strong proof\n"
    res = evaluate_submission("TEAM_JUDGE", level=1, flag_answer="receivers", graph_csv=graph, judge=MockJudge())
    assert len(res.llm_verdicts) == 1
    assert res.llm_verdicts[0]["verdict"] == "supported"
    assert ("P02", "P05", "SHARES_PRINCIPLE") in res.discovery_bounty_edges
    assert ("P02", "P05", "SHARES_PRINCIPLE") in res.correct_edges


def test_evaluate_google_form_csv_parsing(tmp_path):
    csv_file = tmp_path / "mock_google_form.csv"
    csv_file.write_text(
        "Timestamp,Team ID,Level Flag,Cumulative Graph CSV,Explanation\n"
        '2026/11/10 12:00:00,ALPHA,receivers,"source_id,target_id,relationship_type\nP02,P05,CITES\nP13,P05,CITES\nP13,P02,CITES\nP02,P05,ANALOGOUS_PROBLEM\nP05,P13,ANALOGOUS_PROBLEM",Methodology explanation\n'
        '2026/11/10 12:05:00,BETA,wrong,"source_id,target_id,relationship_type\nP02,P05,CITES",Short note\n',
        encoding="utf-8",
    )
    results = evaluate_google_form_csv(csv_file, level=1)
    assert len(results) == 2
    assert results[0].team_id == "ALPHA"
    assert results[0].flag_correct is True
    assert results[0].total_score == 2500.0
    assert results[1].team_id == "BETA"
    assert results[1].flag_correct is False
