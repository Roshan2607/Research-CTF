"""Tests verifying the fixes for all items in the code review."""
import datetime as dt
import os
import pytest
import pandas as pd
import event_core as core
import scoring.flag_validator as fv
from event_core import safe_csv


@pytest.fixture()
def clean_env(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(core, "LOG", tmp_path / "events.jsonl")
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.save(core._empty())
    return tmp_path


def solve_level0(tid):
    core.attempt_flag(tid, 0, "trie")
    core.finalise(tid, 0, "", explanation="warm-up")


def test_demo_team_papers_tab_no_keyerror(clean_env):
    """Bug 1: demo team papers tab / hint status must never crash with KeyError: flag_mode."""
    core.ensure_demo_team("DEMO00", "Level 0 Demo Team", "DemoPass123!")
    status = core.hint_status("DEMO00", 0)
    assert isinstance(status, list)


def test_naive_deadline_handling(clean_env, monkeypatch):
    """Bug 2: naive deadline ISO strings without timezone must not crash final_results_visible."""
    monkeypatch.setenv("FINAL_DEADLINE", "2026-11-10T18:00:00")
    dl = core.final_deadline()
    assert dl is not None
    assert dl.tzinfo is not None
    # Comparison with aware datetime should succeed
    vis = core.final_results_visible()
    assert isinstance(vis, bool)
    # Comparison with custom naive datetime should also succeed
    vis_naive = core.final_results_visible(at=dt.datetime(2026, 11, 10, 19, 0, 0))
    assert vis_naive is True


def test_hedged_answers_rejected():
    """Item 5: hedged answers like 'P08 P06 P11' or > 4 words must be rejected."""
    val = fv.LevelFlagValidator()
    # Hedged with multiple paper IDs
    res = val.evaluate_attempt("T1", 3, "P08 P06 P11", ["p08"], [])
    assert res["correct"] is False
    assert "single paper ID" in res["message"]

    # More than 4 words
    res2 = val.evaluate_attempt("T1", 3, "P08 or maybe another one", ["p08"], [])
    assert res2["correct"] is False
    assert "maximum 4 words" in res2["message"]

    # Valid concise answer
    res3 = val.evaluate_attempt("T1", 3, "P08", ["p08"], [])
    assert res3["correct"] is True


def test_natural_aliases():
    """Item 6: Natural aliases like 'end-to-end', 'biology', 'paper 8', 'P 8' must be accepted."""
    val = fv.LevelFlagValidator()
    # P 8 and paper 8
    assert val.evaluate_attempt("T1", 3, "paper 8", ["p08"], [])["correct"] is True
    assert val.evaluate_attempt("T1", 3, "P 8", ["p08"], [])["correct"] is True
    assert val.evaluate_attempt("T1", 3, "paper 08", ["p08"], [])["correct"] is True

    # end-to-end
    assert fv.answer_matches("end-to-end", ["end-to-end", "receivers"]) is True
    assert fv.answer_matches("end to end", ["end-to-end", "receivers"]) is True

    # biology
    assert fv.answer_matches("biology", ["phylogenetics", "biology"]) is True


def test_hint3_cost_is_two_points():
    """Item 9: Hint 3 cost is configured to 2.0 points."""
    assert core.HINT_RUNG3_COST == 2.0


def test_override_restricted_to_current_level_and_waive(clean_env):
    """Item 10: Overrides must be restricted to current level, with optional penalty waiver."""
    core.create_team("TOVR", "Override Team", "Pass12345678")
    solve_level0("TOVR")
    # Current level is 1; overriding level 2 must fail
    with pytest.raises(PermissionError, match="currently on Level 1"):
        core.override_flag("TOVR", 2, "admin", "too early")

    # Wrong attempt on level 1
    core.attempt_flag("TOVR", 1, "wrong answer")
    assert core.flag_status("TOVR", 1)["wrong_attempts"] == 1

    # Override level 1 with waive_penalties=True
    core.override_flag("TOVR", 1, "admin", "accepted answer", waive_penalties=True)
    st = core.flag_status("TOVR", 1)
    assert st["correct"] is True
    assert st["wrong_attempts"] == 0
    assert st["penalty_points"] == 0.0


def test_reveal_hint_blocked_after_flag_solved(clean_env):
    """Item 10: Cannot reveal paid hints after solving the flag."""
    core.create_team("THNT", "Hint Block Team", "Pass12345678")
    solve_level0("THNT")
    for _ in range(6):
        core.attempt_flag("THNT", 1, "wrong")
    # Solve the flag
    core.attempt_flag("THNT", 1, "receivers")
    assert core.flag_status("THNT", 1)["correct"] is True

    # Attempting to reveal hint 3 now must fail
    with pytest.raises(PermissionError, match="already solved"):
        core.reveal_hint("THNT", 1, 3)


def test_csv_formula_injection_escaping():
    """Item 11: CSV exports must escape cells starting with =, +, -, @."""
    df = pd.DataFrame([
        {"team": "=CMD|' /C calc'!A0", "note": "+1234", "flag": "@formula", "clean": "Normal"}
    ])
    csv_out = safe_csv(df)
    assert "'=CMD" in csv_out
    assert "'+1234" in csv_out
    assert "'@formula" in csv_out
    assert "Normal" in csv_out


def test_session_expiry_and_revocation(clean_env):
    """Item 12: Revoke sessions on reset, enforce 14-day expiry, constant-time dummy hash."""
    core.create_team("TSES", "Session Team", "Pass12345678")
    tok = core.create_session("TSES")
    assert core.authenticate_session(tok) is not None

    # Reset team should revoke token
    core.reset_team("TSES")
    assert core.authenticate_session(tok) is None

    # Unknown team authentication should safely return None without timing leak
    assert core.authenticate("NON_EXISTENT_TEAM", "random_pwd") is None


def test_input_size_limits(clean_env):
    """Item 13: Enforce size limits on flag answers, drafts, and explanations."""
    core.create_team("TLIM", "Limit Team", "Pass12345678")
    solve_level0("TLIM")
    # Flag answer > 200 chars
    long_ans = "a" * 201
    res = core.attempt_flag("TLIM", 1, long_ans)
    assert res["correct"] is False
    assert "maximum length of 200" in res["message"]

    # Draft > 50KB
    long_draft = "a" * 50001
    with pytest.raises(ValueError, match="50KB"):
        core.save_draft("TLIM", 1, long_draft)

    # Explanation > 3000 chars
    core.attempt_flag("TLIM", 1, "receivers")
    hdr = "source_id,target_id,relationship_type,evidence_reference\nP02,P05,CITES,ref\n"
    long_expl = "e" * 3001
    with pytest.raises(ValueError, match="3000 characters"):
        core.finalise("TLIM", 1, hdr, explanation=long_expl)
