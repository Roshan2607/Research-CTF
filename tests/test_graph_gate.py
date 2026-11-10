"""Graph progression gate: correct flag AND server-side weighted F1 >= the level floor."""
import time

import pytest

import event_core as core

HDR = "source_id,target_id,relationship_type,evidence_reference\n"
GATE = {"enabled": True, "floors": {"1": 0.40, "2": 0.50}, "retry_cooldown_seconds": 0}


@pytest.fixture
def team(tmp_path, monkeypatch):
    monkeypatch.delenv("UL_GRAPH_GATE", raising=False)
    monkeypatch.setattr(core, "STATE", tmp_path / "event_state.json")
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    monkeypatch.setattr(core, "COOLDOWN_SCHEDULE", None)
    monkeypatch.setattr(core, "_GATE", dict(GATE))
    core.create_team("GATE01", "Gate Team", "StrongPass123")
    core.attempt_flag("GATE01", 0, "FLAG{TRIE}")
    core.save_draft("GATE01", 0, HDR)
    core.finalise("GATE01", 0, HDR, explanation="warm-up")
    core.attempt_flag("GATE01", 1, core.level_spec(core.CLUSTER, 1)["answers"][0])
    return "GATE01"


def edges(cls, n, level=1):
    sc = core._main_scorer()
    rel = set(core.released_papers(level, core.CLUSTER))
    found = sorted(t for t, c in sc.classes.items() if c == cls and t[0] in rel and t[1] in rel)[:n]
    return found


def csv(es):
    return HDR + "".join(f"{s},{t},{r},evidence\n" for s, t, r in es)


def test_floor_lookup(monkeypatch):
    monkeypatch.delenv("UL_GRAPH_GATE", raising=False)
    assert core.graph_gate_floor(0) is None
    core._GATE = dict(GATE)
    assert core.graph_gate_floor(1) == 0.40 and core.graph_gate_floor(2) == 0.50 and core.graph_gate_floor(3) is None
    core._GATE = {"enabled": False, "floors": {"1": 0.4}}
    assert core.graph_gate_floor(1) is None
    monkeypatch.setenv("UL_GRAPH_GATE", "off")
    core._GATE = dict(GATE)
    assert core.graph_gate_floor(1) is None  # kill switch wins


def test_weak_graph_is_refused_and_the_team_stays_on_the_level(team):
    bad = csv(edges("ordinary", 5))
    with pytest.raises(ValueError, match="not strong enough"):
        core.finalise(team, 1, bad, explanation="x")
    assert core.team_progress(team)[1] == 1
    assert f"{team}:1" not in core.load()["submissions"]
    assert any(a["action"] == "graph_gate_failed" for a in core.load()["audit"])


def test_strong_graph_locks_and_advances(team):
    good = csv(edges("reference", 5))
    rec = core.finalise(team, 1, good, explanation="x")
    assert rec["graph_score"]["weighted_f1"] >= 0.40 and core.team_progress(team)[1] == 2


def test_team_can_fix_the_graph_and_retry(team):
    with pytest.raises(ValueError):
        core.finalise(team, 1, csv(edges("ordinary", 4)), explanation="x")
    core.finalise(team, 1, csv(edges("reference", 3) + edges("ordinary", 1)), explanation="x")
    assert core.team_progress(team)[1] == 2


def test_retry_cooldown_rate_limits_the_score_oracle(team, monkeypatch):
    monkeypatch.setattr(core, "_GATE", {**GATE, "retry_cooldown_seconds": 60})
    bad = csv(edges("ordinary", 3))
    with pytest.raises(ValueError, match="not strong enough"):
        core.finalise(team, 1, bad, explanation="x")
    with pytest.raises(ValueError, match="Please wait"):
        core.finalise(team, 1, bad, explanation="x")  # no score revealed on the rate-limited retry


def test_organiser_waiver_releases_a_stuck_team(team):
    bad = csv(edges("ordinary", 4))
    with pytest.raises(ValueError):
        core.finalise(team, 1, bad, explanation="x")
    with pytest.raises(ValueError, match="reviewer"):
        core.waive_graph_gate(team, 1, "")
    core.waive_graph_gate(team, 1, "Organiser A", "stuck, time up")
    assert core.finalise(team, 1, bad, explanation="x")["locked"]
    assert any(a["action"] == "graph_gate_waived" for a in core.load()["audit"])


def test_flag_is_still_required(team, monkeypatch):
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("GATE02", "No flag", "StrongPass123")
    core.attempt_flag("GATE02", 0, "FLAG{TRIE}")
    core.save_draft("GATE02", 0, HDR)
    core.finalise("GATE02", 0, HDR, explanation="w")
    with pytest.raises(ValueError, match="flag attempt"):
        core.finalise("GATE02", 1, csv(edges("reference", 5)), explanation="x")


def test_disabled_gate_changes_nothing(team, monkeypatch):
    monkeypatch.setattr(core, "_GATE", {"enabled": False, "floors": {"1": 0.9}})
    assert core.finalise(team, 1, csv(edges("ordinary", 4)), explanation="x")["locked"]
