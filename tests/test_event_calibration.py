"""Calibrated event mechanics on the LIVE content and config defaults (calibration review, Nov 2026)."""
import datetime as dt

import pytest

import event_core as core
from challenge import paths
from scoring.flag_validator import LevelFlagValidator, answer_matches, build_flag_registry, cooldown_for

LIVE = core.ROOT / "data" / "event_content.csv"
SECRET = "calibration-test-secret-0123456789"
HDR = "source_id,target_id,relationship_type,evidence_reference\n"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "CONTENT", LIVE)
    monkeypatch.delenv("UL_EVENT_CONTENT", raising=False)
    monkeypatch.setattr(core, "STATE", tmp_path / "event_state.json")
    monkeypatch.setattr(core, "LOG", tmp_path / "events.jsonl")
    monkeypatch.setattr(core, "TEAM_CSV", tmp_path / "teams.csv")
    monkeypatch.setattr(core, "SUB_CSV", tmp_path / "subs.csv")
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)  # cooldown arithmetic is tested on the validator directly
    core.save(core._empty())
    return tmp_path


def spec(level):
    return core.level_spec(core.CLUSTER, level)


def solve_level0(tid):
    core.attempt_flag(tid, 0, "trie")
    core.finalise(tid, 0, "", explanation="warm-up")


def lock(tid, level, answer, csv_text):
    assert core.attempt_flag(tid, level, answer)["correct"] is True
    return core.finalise(tid, level, csv_text, explanation=f"level {level} reasoning with page references")


# ---------------------------------------------------------------- config defaults
def test_calibrated_rule_defaults():
    assert core.PENALTY_PER_WRONG == 0.5 and core.MAX_PENALTY_PER_LEVEL == 5.0
    assert core.COOLDOWN_SCHEDULE == [10, 10, 30]
    assert core.HINT_UNLOCK_AFTER_WRONG == [2, 4, 6] and core.HINT_RUNG3_COST == 1.0
    assert (core.DISCOVERY_TARGET_POINTS, core.DISCOVERY_APPLICATION_POINTS, core.DISCOVERY_REVIEW_MAX_POINTS) == (3.0, 2.0, 5.0)


def test_cooldown_schedule_and_penalty_cap():
    assert [cooldown_for(n, 30, [10, 10, 30]) for n in (1, 2, 3, 7)] == [10, 10, 30, 30]
    assert cooldown_for(3, 0, [10, 10, 30]) == 0
    v = LevelFlagValidator(cooldown_seconds=30, free_wrong_attempts=5, flag_points_per_level=10,
                           penalty_per_attempt=0.5, cooldown_schedule=[10, 10, 30], max_penalty=5)
    t0 = dt.datetime(2026, 11, 20, 10, 0, tzinfo=dt.timezone.utc)
    hist = [{"at": (t0 - dt.timedelta(seconds=11)).isoformat(), "answer": "x", "correct": False}]
    assert v.evaluate_attempt("T", 1, "y", ["z"], hist, now=t0)["cooldown"] is False  # 1st wrong -> 10 s, elapsed 11 s
    hist3 = hist * 3
    assert v.evaluate_attempt("T", 1, "y", ["z"], hist3, now=t0)["cooldown"] is True   # 3rd wrong -> 30 s
    many = [{"at": "2026-01-01T00:00:00+00:00", "answer": "x", "correct": False}] * 40
    assert v.compute_status(many + [{"at": "2026-01-01T00:00:00+00:00", "answer": "z", "correct": True}])["flag_points"] == 5.0


# ---------------------------------------------------------------- keyword-group flags on the live questions
@pytest.mark.parametrize("level,good", [
    (1, ["receivers", "At the end hosts", "the leaves", "multicast receivers", "endpoints of the network"]),
    (2, ["phylogenetics", "Phylogenetic tree inference", "evolutionary biology", "evolution"]),
    (3, ["P08", "p8", "paper P8", "Bhamidi"]),
])
def test_live_flags_accept_reasonable_phrasings(level, good):
    for a in good:
        assert answer_matches(a, spec(level)["answers"]), (level, a)


@pytest.mark.parametrize("level,bad", [
    (1, ["routers", "the core of the network", "projections"]),
    (2, ["epidemiology", "medical imaging", "computer networks"]),
    (3, ["P10", "P12", "P06", "neighbor joining"]),
])
def test_live_flags_reject_wrong_answers(level, bad):
    for a in bad:
        assert not answer_matches(a, spec(level)["answers"]) or any(answer_matches(a, [d]) for d in spec(level)["decoy_answers"]), (level, a)


def test_decoy_lure_and_hedging_are_rejected_and_recorded(env):
    core.create_team("TEAMLURE", "Lure Team", "StrongPass123")
    solve_level0("TEAMLURE")
    core.attempt_flag("TEAMLURE", 1, "receivers")
    core.finalise("TEAMLURE", 1, HDR + "P02,P05,CITES,ref\n", explanation="x")
    r = core.attempt_flag("TEAMLURE", 2, "phylogenetics or epidemiology")  # hedge that includes a decoy lure
    assert r["correct"] is False
    hist = core.load()["attempts"]["TEAMLURE:2"]
    assert hist[-1]["decoy_signal"] is True
    assert core.flag_status("TEAMLURE", 2)["decoy_signals"] == 1


def test_keyword_stuffing_rejected():
    long_answer = "receivers leaves endpoints hosts routers core links nodes edges everything"
    assert not answer_matches(long_answer, spec(1)["answers"])


# ---------------------------------------------------------------- hints
def test_hint_ladder_unlocks_and_rung3_costs_a_point(env):
    core.create_team("TEAMHINT", "Hint Team", "StrongPass123")
    solve_level0("TEAMHINT")
    assert [h["unlocked"] for h in core.hint_status("TEAMHINT", 1)] == [False, False, False]
    with pytest.raises(PermissionError):
        core.reveal_hint("TEAMHINT", 1, 1)
    for i in range(6):
        core.attempt_flag("TEAMHINT", 1, f"wrong {i}")
    assert [h["unlocked"] for h in core.hint_status("TEAMHINT", 1)] == [True, True, True]
    assert core.reveal_hint("TEAMHINT", 1, 1)["cost"] == 0
    assert core.reveal_hint("TEAMHINT", 1, 3)["cost"] == 1.0
    core.attempt_flag("TEAMHINT", 1, "receivers")
    st = core.flag_status("TEAMHINT", 1)
    assert st["penalty_points"] == 0.5 and st["hint_cost"] == 1.0 and st["flag_points"] == 8.5


def test_organiser_released_hint_is_free(env):
    core.create_team("TEAMREL", "Release Team", "StrongPass123")
    solve_level0("TEAMREL")
    core.release_hint_for_all(1, 3)
    h3 = core.hint_status("TEAMREL", 1)[2]
    assert h3["unlocked"] and h3["revealed"] and h3["cost"] == 0 and h3["text"]


# ---------------------------------------------------------------- organiser gate
def test_organiser_level_gate(env):
    core.create_team("TEAMGATE", "Gate Team", "StrongPass123")
    solve_level0("TEAMGATE")
    core.set_open_level(0)
    r = core.attempt_flag("TEAMGATE", 1, "receivers")
    assert r["correct"] is False and "not been opened" in r["message"]
    core.set_open_level(1)
    assert core.attempt_flag("TEAMGATE", 1, "receivers")["correct"] is True


# ---------------------------------------------------------------- server-side, level-scoped graph scoring
LEVEL1_REFERENCE = HDR + "\n".join([
    "P02,P05,CITES,r", "P13,P05,CITES,r", "P13,P02,CITES,r", "P02,P05,ANALOGOUS_PROBLEM,r", "P05,P13,ANALOGOUS_PROBLEM,r"]) + "\n"


def test_level1_is_fully_scoreable(env):
    s = core.score_level_graph(core.CLUSTER, 1, LEVEL1_REFERENCE)
    assert s["scope_reference_edges"] == 5 and s["weighted_f1"] == 1.0 and s["points"] == core.GRAPH_POINTS_PER_LEVEL


def test_scoring_ignores_unreleased_papers_and_counts_scope(env):
    s2 = core.score_level_graph(core.CLUSTER, 2, LEVEL1_REFERENCE)
    assert s2["scope_reference_edges"] == 16 and s2["recall"] == round(5 / 16, 4)
    # an edge to a paper not yet released does not exist for scoring
    s = core.score_level_graph(core.CLUSTER, 1, LEVEL1_REFERENCE + "P12,P05,CITES,r\n")
    assert s["edges"] == 5


def test_injection_weight_applies_only_once_host_released(env, monkeypatch):
    graph = LEVEL1_REFERENCE.replace(HDR, "") + "P04,P05,EXTENDS,AI said so\n"
    s2 = core.score_level_graph(core.CLUSTER, 2, HDR + graph)
    assert s2["injection_edges"] == 1  # host P09 is released at level 2
    monkeypatch.setattr(core, "_injection_hosts", lambda: {("P04", "P05", "EXTENDS"): "P01"})  # host not yet released
    s2b = core.score_level_graph(core.CLUSTER, 2, HDR + graph)
    assert s2b["injection_edges"] == 0 and s2b["decoy_edges"] == 1
    assert s2b["weighted_precision"] > s2["weighted_precision"]


def test_finalise_stores_server_score_not_client_score(env):
    core.create_team("TEAMSRV", "Server Team", "StrongPass123")
    solve_level0("TEAMSRV")
    core.attempt_flag("TEAMSRV", 1, "receivers")
    rec = core.finalise("TEAMSRV", 1, LEVEL1_REFERENCE, graph_score={"points": 999}, explanation="refs on p.3")
    assert rec["graph_score"]["points"] == core.GRAPH_POINTS_PER_LEVEL


# ---------------------------------------------------------------- one-shot final discovery at level 4
GOOD_FORM = {
    "base_id": "P05", "target_id": "P03",
    "principle": "Both rebuild a hidden branching tree, including unobserved internal nodes, from measurements made only at its leaves.",
    "application": "Nextstrain",
    "paper_evidence": "P12 p.5 says network inference is similar to phylogenetic inference; P08 p.5; P03 abstract.",
    "application_evidence": "https://docs.nextstrain.org/projects/augur/en/stable/usage/cli/ancestral.html",
    "limitations": "Shared principle only; no historical lineage; Nextstrain uses maximum likelihood rather than NJ.",
}


def _advance_to_level4(tid):
    solve_level0(tid)
    lock(tid, 1, "receivers", LEVEL1_REFERENCE)
    lock(tid, 2, "phylogenetics", LEVEL1_REFERENCE + "P12,P05,CITES,ref [23]\n")
    lock(tid, 3, "P08", LEVEL1_REFERENCE + "P12,P05,CITES,ref [23]\nP08,P12,CITES,ref [21]\n")


def test_level4_standard_flag_progression(env):
    core.create_team("TEAMFIN", "Final Team", "StrongPass123")
    _advance_to_level4("TEAMFIN")
    assert core.team_progress("TEAMFIN")[1] == 4
    # Level 4 has standard keyword flag checking
    res = core.attempt_flag("TEAMFIN", 4, "neighbor joining")
    assert res["correct"] is True
    rec = core.finalise("TEAMFIN", 4, LEVEL1_REFERENCE + "P12,P03,USES_METHOD,Alg.1 p.13\n", explanation="final")
    assert rec["flag_correct"] is True
    assert rec["flag_points"] == 10.0
    assert core.team_progress("TEAMFIN")[1] is None  # all levels complete!


def test_level4_soft_gating_advancement(env):
    core.create_team("TEAMWRG", "Wrong Team", "StrongPass123")
    _advance_to_level4("TEAMWRG")
    assert core.team_progress("TEAMWRG")[1] == 4
    res = core.attempt_flag("TEAMWRG", 4, "wrong flag")
    assert res["correct"] is False
    # Soft gating: wrong flag attempt allows locking and completing event with 0 flag points
    rec = core.finalise("TEAMWRG", 4, LEVEL1_REFERENCE + "P12,P03,USES_METHOD,Alg.1 p.13\n", explanation="final")
    assert rec["flag_correct"] is False
    assert rec["flag_points"] == 0.0
    assert core.team_progress("TEAMWRG")[1] is None


# ---------------------------------------------------------------- organiser tools and secrets
def test_reset_team_and_alerts(env):
    core.create_team("TEAMRST", "Reset Team", "StrongPass123")
    solve_level0("TEAMRST")
    for i in range(7):
        core.attempt_flag("TEAMRST", 1, f"wrong {i}")
    alerts = core.calibration_alerts()
    l1 = alerts["levels"][0]
    assert l1["level"] == 1 and l1["share_6plus_wrong"] == 1.0 and alerts["alerts"]
    core.reset_team("TEAMRST")
    assert core.team_progress("TEAMRST") == ([], 0)
    assert "TEAMRST:1" not in core.load()["attempts"]


def test_admin_password_rules():
    assert not core.check_admin_password("short", "short")
    assert core.check_admin_password("a-long-enough-password", "a-long-enough-password")
    assert not core.check_admin_password("a-long-enough-passwor", "a-long-enough-password")
    pwd = "IEEE_Etal2026"
    assert core.check_admin_password(pwd, pwd)


def test_demo_team_has_default_password(env):
    tid = core.ensure_demo_team("DEMO00", "Demo")
    assert core.authenticate(tid, "DemoPass123!") is not None
