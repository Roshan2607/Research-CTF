"""Comprehensive automated tests for Section A: Backend and Data Model.

Covers:
- Team and storage (creation, duplicates, cluster assignment, restart persistence, malformed JSON recovery, concurrency)
- Flag validation (correct flags, first 5 free wrong, 6th+ penalties, cooldown enforcement, attempts during cooldown not counted, team/level isolation, wrong cluster/level flags, demo flag isolation)
- Submissions (valid submission, missing graph, missing flag, missing explanation, duplicate submission, submission after lock, concurrent submissions, failure non-locking, cross-team submission rejection)
- Knowledge graph (genuinely immutable snapshots, node/edge persistence, cross-level updates, immutability, post-lock modification rejection)
- Graph validation in backend (rejection of self-loops, unreleased papers, invalid relationship types, duplicate edges, malformed CSV)
- Sequential level progression (level 2 blocked before level 1, cross-cluster blocked, demo progression)
- Graph ownership & team isolation (team mismatch, non-existent team, cross-team isolation)
- Configuration validation (missing config, malformed JSON, invalid cooldowns, invalid points, inconsistent clusters)
- Safe corrupted-state recovery (quarantine file creation, preservation of corrupted data, explicit recovery)
- Real multiprocessing concurrency tests (simultaneous registration, attempts, submissions, graph updates)
- Security (answer keys protected, score tampering prevention, cluster tampering prevention, cooldown bypass prevention, submission locking bypass prevention)
"""
from __future__ import annotations

import concurrent.futures
import copy
import json
import multiprocessing as mp
import os
import time
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import event_core as core
from challenge.graph_store import (
    GraphEdge,
    LevelGraphSnapshot,
    TeamKnowledgeGraph,
    parse_and_validate_csv,
    validate_graph_structure,
)
from challenge.submission import LevelSubmissionService
from scoring.flag_validator import LevelFlagValidator, normalise_flag


# ==============================================================================
# MULTIPROCESSING WORKERS (Must be top-level for spawn context)
# ==============================================================================

def _mp_register_worker(args):
    team_id, name, pw, state_path = args
    os.environ["UL_EVENT_STATE"] = str(state_path)
    import event_core as c
    c.STATE = Path(state_path)
    try:
        c.create_team(team_id, name, pw)
        return True
    except Exception as e:
        return str(e)


def _mp_flag_attempt_worker(args):
    team_id, level, answer, state_path = args
    os.environ["UL_EVENT_STATE"] = str(state_path)
    import event_core as c
    c.STATE = Path(state_path)
    c.COOLDOWN_SECONDS = 0
    try:
        return c.attempt_flag(team_id, level, answer)
    except Exception as e:
        return {"error": str(e)}


def _mp_finalise_worker(args):
    team_id, level, csv_text, expl, state_path = args
    os.environ["UL_EVENT_STATE"] = str(state_path)
    import event_core as c
    c.STATE = Path(state_path)
    c.COOLDOWN_SECONDS = 0
    try:
        c.finalise(team_id, level, csv_text, True, {"points": 10.0}, explanation=expl)
        return "SUCCESS"
    except PermissionError:
        return "LOCKED"
    except Exception as e:
        return f"ERROR: {e}"


def _mp_graph_draft_worker(args):
    team_id, level, csv_text, state_path = args
    os.environ["UL_EVENT_STATE"] = str(state_path)
    import event_core as c
    c.STATE = Path(state_path)
    try:
        c.save_draft(team_id, level, csv_text)
        return "OK"
    except Exception as e:
        return f"ERROR: {e}"


# ==============================================================================
# FIXTURES
# ==============================================================================

@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """Isolate backend state, logs, and CSV exports to tmp_path."""
    state_file = tmp_path / "event_state.json"
    log_file = tmp_path / "events.jsonl"
    team_csv = tmp_path / "teams.csv"
    sub_csv = tmp_path / "submissions.csv"

    os.environ["UL_EVENT_STATE"] = str(state_file)
    monkeypatch.setattr(core, "STATE", state_file)
    monkeypatch.setattr(core, "LOG", log_file)
    monkeypatch.setattr(core, "TEAM_CSV", team_csv)
    monkeypatch.setattr(core, "SUB_CSV", sub_csv)
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 30)
    monkeypatch.setattr(core, "FREE_WRONG_ATTEMPTS", 5)
    monkeypatch.setattr(core, "FLAG_POINTS_PER_LEVEL", 10)
    monkeypatch.setattr(core, "GRAPH_POINTS_PER_LEVEL", 15.0)

    return tmp_path


# ==============================================================================
# 1. TEAM AND STORAGE TESTS
# ==============================================================================

def test_team_creation_and_retrieval(isolated_env):
    tid = core.create_team("TEAM_ALPHA", "Alpha Squad", "Password123!", cluster=core.CLUSTER)
    assert tid == "TEAM_ALPHA"

    auth_ok = core.authenticate("TEAM_ALPHA", "Password123!")
    assert auth_ok is not None
    assert auth_ok["team_id"] == "TEAM_ALPHA"
    assert auth_ok["name"] == "Alpha Squad"
    assert auth_ok["cluster"] == core.CLUSTER
    assert auth_ok["is_demo"] is False

    assert core.authenticate("team_alpha", "Password123!") is not None
    assert core.authenticate("TEAM_ALPHA", "WrongPass123") is None


def test_duplicate_team_rejection(isolated_env):
    core.create_team("TEAM_DUP", "Original Team", "Password123!")
    with pytest.raises(ValueError, match="already exists"):
        core.create_team("TEAM_DUP", "Duplicate Team", "AnotherPass123!")
    with pytest.raises(ValueError, match="already exists"):
        core.create_team("team_dup", "Duplicate Team Lower", "AnotherPass123!")


def test_invalid_team_id_and_cluster_assignment(isolated_env):
    with pytest.raises(ValueError, match="team ID"):
        core.create_team("!!INVALID!!", "Bad Team", "Password123!")
    with pytest.raises(ValueError, match="team ID"):
        core.create_team("T", "Short ID", "Password123!")
    with pytest.raises(ValueError, match="at least 8 characters"):
        core.create_team("TEAM_SHORT_PW", "Short PW Team", "short")
    with pytest.raises(ValueError, match="cluster"):
        core.create_team("TEAM_BAD_CL", "Bad Cluster Team", "Password123!", cluster="NonExistentCluster")


def test_persistence_after_restart(isolated_env):
    core.create_team("TEAM_PERSIST", "Persist Team", "Password123!")
    core.save_draft("TEAM_PERSIST", 1, "source_id,target_id,relationship_type,evidence_reference\nP01,P02,EXTENDS,Note\n")

    fresh_state = core.load()
    assert "TEAM_PERSIST" in fresh_state["teams"]
    assert "TEAM_PERSIST:1" in fresh_state["drafts"]
    assert core.get_draft("TEAM_PERSIST", 1).strip().startswith("source_id,target_id")


def test_safe_corrupted_state_recovery_and_quarantine(isolated_env):
    corrupt_content = "{ corrupt json: [ missing closing brackets "
    core.STATE.write_text(corrupt_content, encoding="utf-8")

    # Regular load raises CorruptedStateError to protect participant data
    with pytest.raises(core.CorruptedStateError, match="quarantine backup was created"):
        core.load()

    # Verify original file was preserved
    assert core.STATE.read_text(encoding="utf-8") == corrupt_content

    # Verify quarantine backup was created
    quarantined = list(core.STATE.parent.glob("event_state_corrupted_*.json"))
    assert len(quarantined) >= 1
    assert quarantined[0].read_text(encoding="utf-8") == corrupt_content

    # Explicit recovery operation reinitializes empty state
    recovered = core.recover_corrupted_state()
    assert isinstance(recovered, dict)
    assert recovered["teams"] == {}


def test_concurrent_storage_updates(isolated_env):
    def register(i: int):
        try:
            core.create_team(f"TEAM_C_{i:02d}", f"Concurrent Team {i}", "Password123!")
            return True
        except Exception as e:
            return str(e)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(register, range(20)))

    assert all(r is True for r in results)
    d = core.load()
    assert len(d["teams"]) == 20


# ==============================================================================
# 2. FLAG VALIDATION TESTS
# ==============================================================================

def test_flag_validation_correct_immediate_feedback(isolated_env, monkeypatch):
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM_FLAG_1", "Flag Team 1", "Password123!")

    res = core.attempt_flag("TEAM_FLAG_1", 1, "tree reconstruction")
    assert res["correct"] is True
    assert res["earned_points"] == 10
    assert "Correct flag!" in res["message"]

    status = core.flag_status("TEAM_FLAG_1", 1)
    assert status["correct"] is True
    assert status["flag_points"] == 10
    assert status["penalty_points"] == 0
    assert status["attempts"] == 1


def test_first_five_incorrect_attempts_free(isolated_env, monkeypatch):
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM_FREE_5", "Free 5 Team", "Password123!")

    for i in range(1, 6):
        res = core.attempt_flag("TEAM_FREE_5", 1, f"wrong guess {i}")
        assert res["correct"] is False
        assert f"{5 - i} free wrong attempts remaining" in res["message"]

    st = core.flag_status("TEAM_FREE_5", 1)
    assert st["attempts"] == 5
    assert st["wrong_attempts"] == 5
    assert st["penalty_points"] == 0

    res_correct = core.attempt_flag("TEAM_FREE_5", 1, "tree reconstruction")
    assert res_correct["correct"] is True
    assert res_correct["earned_points"] == 10


def test_sixth_and_subsequent_incorrect_attempts_penalty(isolated_env, monkeypatch):
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM_PENALTY", "Penalty Team", "Password123!")

    for i in range(1, 6):
        core.attempt_flag("TEAM_PENALTY", 1, f"wrong guess {i}")

    r6 = core.attempt_flag("TEAM_PENALTY", 1, "wrong guess 6")
    assert r6["correct"] is False
    assert "Penalty: -1 flag point(s)" in r6["message"]
    st6 = core.flag_status("TEAM_PENALTY", 1)
    assert st6["penalty_points"] == 1

    core.attempt_flag("TEAM_PENALTY", 1, "wrong guess 7")
    st7 = core.flag_status("TEAM_PENALTY", 1)
    assert st7["penalty_points"] == 2

    rc = core.attempt_flag("TEAM_PENALTY", 1, "tree reconstruction")
    assert rc["correct"] is True
    assert rc["earned_points"] == 8
    st_c = core.flag_status("TEAM_PENALTY", 1)
    assert st_c["flag_points"] == 8


def test_flag_cooldown_enforcement_and_rejected_attempt_not_counted(isolated_env):
    core.create_team("TEAM_CD_REJ", "Cooldown Rejection Team", "Password123!")

    first = core.attempt_flag("TEAM_CD_REJ", 1, "wrong attempt 1")
    assert first["correct"] is False
    assert first["cooldown_remaining"] == 30

    st1 = core.flag_status("TEAM_CD_REJ", 1)
    assert st1["attempts"] == 1
    assert st1["wrong_attempts"] == 1

    second = core.attempt_flag("TEAM_CD_REJ", 1, "wrong attempt during cooldown")
    assert second["correct"] is False
    assert second.get("cooldown") is True
    assert "Cooldown active" in second["message"]

    st2 = core.flag_status("TEAM_CD_REJ", 1)
    assert st2["attempts"] == 1
    assert st2["wrong_attempts"] == 1
    assert st2["penalty_points"] == 0


def test_attempt_after_cooldown_expiration(isolated_env):
    core.create_team("TEAM_CD_EXP", "Cooldown Expiration Team", "Password123!")
    validator = LevelFlagValidator(cooldown_seconds=30, free_wrong_attempts=5, flag_points_per_level=10)

    t0 = datetime.now(timezone.utc)
    res1 = validator.evaluate_attempt(
        team_id="TEAM_CD_EXP",
        level=1,
        answer="wrong answer 1",
        expected_answers=["tree reconstruction"],
        attempt_history=[],
        now=t0,
    )
    assert res1["correct"] is False
    history = [res1["attempt_record"]]

    t_early = t0 + timedelta(seconds=10)
    res_early = validator.evaluate_attempt(
        team_id="TEAM_CD_EXP",
        level=1,
        answer="wrong answer early",
        expected_answers=["tree reconstruction"],
        attempt_history=history,
        now=t_early,
    )
    assert res_early.get("cooldown") is True
    assert res_early.get("record_attempt") is False

    t_expired = t0 + timedelta(seconds=31)
    res_expired = validator.evaluate_attempt(
        team_id="TEAM_CD_EXP",
        level=1,
        answer="wrong answer after cooldown",
        expected_answers=["tree reconstruction"],
        attempt_history=history,
        now=t_expired,
    )
    assert res_expired.get("cooldown") is False
    assert res_expired.get("record_attempt") is True
    assert res_expired["wrong_count"] == 2


def test_independent_attempt_counts_for_teams_and_levels(isolated_env, monkeypatch):
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM_IND_A", "Team Ind A", "Password123!")
    core.create_team("TEAM_IND_B", "Team Ind B", "Password123!")

    for _ in range(6):
        core.attempt_flag("TEAM_IND_A", 1, "wrong")
    assert core.flag_status("TEAM_IND_A", 1)["wrong_attempts"] == 6
    assert core.flag_status("TEAM_IND_A", 1)["penalty_points"] == 1

    assert core.flag_status("TEAM_IND_B", 1)["wrong_attempts"] == 0
    assert core.flag_status("TEAM_IND_B", 1)["penalty_points"] == 0


def test_wrong_cluster_and_level_flags(isolated_env):
    core.create_team("TEAM_CROSS", "Cross Team", "Password123!")

    res_bad_lvl = core.attempt_flag("TEAM_CROSS", 99, "tree reconstruction")
    assert res_bad_lvl["correct"] is False
    assert "not configured" in res_bad_lvl["message"]


def test_demo_flag_isolation_and_pipeline(isolated_env, monkeypatch):
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    demo_id = core.ensure_demo_team("DEMO00", "Facilitator Demo", "DemoPass123!")
    core.create_team("REAL_TEAM", "Real Team", "Password123!")

    res_wrong = core.attempt_flag(demo_id, 0, "FLAG{WRONG}")
    assert res_wrong["correct"] is False

    res_correct = core.attempt_flag(demo_id, 0, "FLAG{TRIE}")
    assert res_correct["correct"] is True
    assert res_correct["earned_points"] == 10

    snap = core.admin_snapshot()
    real_ids = [t["team_id"] for t in snap["teams"]]
    demo_ids = [t["team_id"] for t in snap["demo_teams"]]
    assert "REAL_TEAM" in real_ids
    assert "DEMO00" not in real_ids
    assert "DEMO00" in demo_ids


# ==============================================================================
# 3. SUBMISSION MANAGEMENT TESTS
# ==============================================================================

def test_valid_final_submission_and_locking(isolated_env, monkeypatch):
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM_SUB_1", "Sub Team 1", "Password123!")
    core.attempt_flag("TEAM_SUB_1", 1, "tree reconstruction")

    graph_csv = "source_id,target_id,relationship_type,evidence_reference\nP01,P02,EXTENDS,Sec. 2\n"
    explanation = "Discovered shared phylogenetic tree topology inference."

    svc = LevelSubmissionService()
    rec = svc.submit_level(
        team_id="TEAM_SUB_1",
        level=1,
        graph_csv=graph_csv,
        explanation=explanation,
        graph_score={"points": 14.5},
    )

    assert rec["locked"] is True
    assert rec["flag_correct"] is True
    assert rec["flag_points"] == 10
    assert rec["explanation"] == explanation
    assert svc.is_locked("TEAM_SUB_1", 1) is True


def test_missing_fields_rejected_without_locking(isolated_env, monkeypatch):
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM_SUB_MISS", "Missing Fields Team", "Password123!")
    core.attempt_flag("TEAM_SUB_MISS", 1, "tree reconstruction")

    svc = LevelSubmissionService()
    graph_csv = "source_id,target_id,relationship_type,evidence_reference\nP01,P02,EXTENDS,Sec. 2\n"

    with pytest.raises(ValueError, match="explanation"):
        svc.submit_level("TEAM_SUB_MISS", 1, graph_csv=graph_csv, explanation="")
    assert svc.is_locked("TEAM_SUB_MISS", 1) is False

    with pytest.raises(ValueError, match="graph"):
        svc.submit_level("TEAM_SUB_MISS", 1, graph_csv="", explanation="Valid explanation")
    assert svc.is_locked("TEAM_SUB_MISS", 1) is False

    with pytest.raises(ValueError, match="relationship edge"):
        svc.submit_level("TEAM_SUB_MISS", 1, graph_csv="source_id,target_id,relationship_type,evidence_reference\n", explanation="Valid explanation")
    assert svc.is_locked("TEAM_SUB_MISS", 1) is False


def test_missing_flag_attempt_rejected(isolated_env):
    core.create_team("TEAM_NO_FLAG", "No Flag Team", "Password123!")
    graph_csv = "source_id,target_id,relationship_type,evidence_reference\nP01,P02,EXTENDS,Sec. 2\n"

    svc = LevelSubmissionService()
    with pytest.raises(ValueError, match="at least one flag attempt"):
        svc.submit_level("TEAM_NO_FLAG", 1, graph_csv=graph_csv, explanation="Explanation")
    assert svc.is_locked("TEAM_NO_FLAG", 1) is False


def test_duplicate_submission_and_modification_after_lock_rejected(isolated_env, monkeypatch):
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM_LOCK", "Lock Team", "Password123!")
    core.attempt_flag("TEAM_LOCK", 1, "tree reconstruction")

    graph_csv = "source_id,target_id,relationship_type,evidence_reference\nP01,P02,EXTENDS,Sec. 2\n"
    core.finalise("TEAM_LOCK", 1, graph_csv, True, {"points": 12.0}, explanation="Initial explanation")

    with pytest.raises(PermissionError, match="already been submitted and locked"):
        core.finalise("TEAM_LOCK", 1, graph_csv, True, {}, explanation="Modified explanation")

    with pytest.raises(PermissionError, match="locked"):
        core.save_draft("TEAM_LOCK", 1, "source_id,target_id,relationship_type,evidence_reference\nP01,P02,EXTENDS,Ref\n")

    flag_res = core.attempt_flag("TEAM_LOCK", 1, "another answer")
    assert flag_res["correct"] is False
    assert "already locked" in flag_res["message"]


def test_concurrent_final_submissions_exactly_one_succeeds(isolated_env, monkeypatch):
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM_CONCUR_SUB", "Concurrent Sub Team", "Password123!")
    core.attempt_flag("TEAM_CONCUR_SUB", 1, "tree reconstruction")

    graph_csv = "source_id,target_id,relationship_type,evidence_reference\nP01,P02,EXTENDS,Sec. 2\n"

    def try_submit(i: int):
        try:
            core.finalise("TEAM_CONCUR_SUB", 1, graph_csv, True, {"points": 10.0}, explanation=f"Worker {i}")
            return "SUCCESS"
        except PermissionError:
            return "LOCKED"
        except Exception as e:
            return f"ERROR: {e}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(try_submit, range(5)))

    assert results.count("SUCCESS") == 1
    assert results.count("LOCKED") == 4


# ==============================================================================
# 4. KNOWLEDGE GRAPH TESTS & GENUINE IMMUTABILITY
# ==============================================================================

def test_knowledge_graph_node_and_edge_persistence(isolated_env):
    core.create_team("TEAM_KG", "Knowledge Graph Team", "Password123!")
    g = core.get_team_graph("TEAM_KG")
    assert len(g.edges) == 0

    edges_lvl1 = [
        {"source_id": "P01", "target_id": "P02", "relationship_type": "EXTENDS", "evidence_reference": "Ref 1"},
        {"source_id": "P02", "target_id": "P01", "relationship_type": "CITES", "evidence_reference": "Ref 2"},
    ]
    g.set_edges_from_list(edges_lvl1, current_level=1)
    core.save_team_graph("TEAM_KG", g)

    reloaded = core.get_team_graph("TEAM_KG")
    assert len(reloaded.edges) == 2
    assert reloaded.get_nodes() == ["P01", "P02"]
    assert ("P01", "P02", "EXTENDS") in reloaded.get_edge_tuples()


def test_graph_updates_across_levels_and_snapshot_immutability(isolated_env, monkeypatch):
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM_KG_PROG", "Progressive KG Team", "Password123!")

    # Level 1: Add edge and finalize
    core.attempt_flag("TEAM_KG_PROG", 1, "tree reconstruction")
    csv_l1 = "source_id,target_id,relationship_type,evidence_reference\nP01,P02,EXTENDS,Sec. 1\n"
    core.finalise("TEAM_KG_PROG", 1, csv_l1, True, {}, explanation="Level 1 done")

    snap1 = core.get_graph_snapshot("TEAM_KG_PROG", 1)
    assert snap1 is not None
    assert len(snap1["edges"]) == 1
    assert snap1["edges"][0]["source_id"] == "P01"

    # Level 2: Team extends graph with new edges
    core.attempt_flag("TEAM_KG_PROG", 2, "leaf-only observations")
    csv_l2 = (
        "source_id,target_id,relationship_type,evidence_reference\n"
        "P01,P02,EXTENDS,Sec. 1\n"
        "P03,P04,ANALOGOUS_PROBLEM,Sec. 3\n"
    )
    core.finalise("TEAM_KG_PROG", 2, csv_l2, True, {}, explanation="Level 2 done")

    snap2 = core.get_graph_snapshot("TEAM_KG_PROG", 2)
    assert snap2 is not None
    assert len(snap2["edges"]) == 2

    # Level 1 snapshot remains completely unaltered (immutable)
    snap1_again = core.get_graph_snapshot("TEAM_KG_PROG", 1)
    assert len(snap1_again["edges"]) == 1
    assert snap1_again["csv_text"] == snap1["csv_text"]


def test_snapshots_cannot_be_mutated_through_exposed_interfaces(isolated_env, monkeypatch):
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM_IMMUT", "Immutability Test Team", "Password123!")
    core.attempt_flag("TEAM_IMMUT", 1, "tree reconstruction")
    csv_l1 = "source_id,target_id,relationship_type,evidence_reference\nP01,P02,EXTENDS,Sec. 1\n"
    core.finalise("TEAM_IMMUT", 1, csv_l1, True, {}, explanation="Level 1 done")

    g = core.get_team_graph("TEAM_IMMUT")
    snap_obj = g.get_snapshot(1)
    assert snap_obj is not None

    # 1. Attempting to mutate snapshot attributes directly raises FrozenInstanceError
    with pytest.raises((FrozenInstanceError, AttributeError)):
        snap_obj.level = 99

    # 2. Attempting to mutate edges tuple raises AttributeError
    with pytest.raises(AttributeError):
        snap_obj.edges.append({"source_id": "HACK", "target_id": "HACK", "relationship_type": "EXTENDS"})

    # 3. Attempting to mutate mappingproxy edge item directly raises TypeError
    with pytest.raises(TypeError):
        snap_obj.edges[0]["source_id"] = "MUTATED"

    # 4. Mutating dictionary returned by to_dict() does not affect internal stored snapshot
    snap_dict = snap_obj.to_dict()
    snap_dict["edges"][0]["source_id"] = "MUTATED_DICT"
    snap_fresh = g.get_snapshot(1)
    assert snap_fresh.edges[0]["source_id"] == "P01"

    # 5. Attempting to overwrite existing snapshot via save_team_graph is rejected
    fake_snap = LevelGraphSnapshot.create(
        level=1,
        submitted_at=snap_obj.submitted_at,
        edges=[{"source_id": "P01", "target_id": "P02", "relationship_type": "CITES"}],  # altered rel
        nodes=["P01", "P02"],
        csv_text="tampered",
    )
    g_tampered = core.get_team_graph("TEAM_IMMUT")
    g_tampered._snapshots[1] = fake_snap
    with pytest.raises(PermissionError, match="Historical snapshot"):
        core.save_team_graph("TEAM_IMMUT", g_tampered)

    # 6. Verify original stored snapshot survived untouched
    verified_snap = core.get_graph_snapshot("TEAM_IMMUT", 1)
    assert verified_snap["edges"][0]["relationship_type"] == "EXTENDS"


# ==============================================================================
# 5. BACKEND GRAPH VALIDATION TESTS
# ==============================================================================

def test_backend_graph_validation_rejections(isolated_env, monkeypatch):
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM_GRAPH_VAL", "Graph Validation Team", "Password123!")

    # 1. Self-loop rejected in save_draft
    bad_self_loop = "source_id,target_id,relationship_type,evidence_reference\nP01,P01,EXTENDS,Ref\n"
    with pytest.raises(ValueError, match="self-loop"):
        core.save_draft("TEAM_GRAPH_VAL", 1, bad_self_loop)

    # 2. Unreleased paper rejected in save_draft (P03 is Level 2, not released in Level 1)
    bad_unreleased = "source_id,target_id,relationship_type,evidence_reference\nP01,P03,EXTENDS,Ref\n"
    with pytest.raises(ValueError, match="unreleased"):
        core.save_draft("TEAM_GRAPH_VAL", 1, bad_unreleased)

    # 3. Invalid relationship type rejected in save_draft
    bad_rel = "source_id,target_id,relationship_type,evidence_reference\nP01,P02,INVALID_TYPE,Ref\n"
    with pytest.raises(ValueError, match="invalid relationship_type"):
        core.save_draft("TEAM_GRAPH_VAL", 1, bad_rel)

    # 4. Duplicate edge rejected in save_draft
    bad_dup = (
        "source_id,target_id,relationship_type,evidence_reference\n"
        "P01,P02,EXTENDS,Ref 1\n"
        "P01,P02,EXTENDS,Ref 2\n"
    )
    with pytest.raises(ValueError, match="duplicate edge"):
        core.save_draft("TEAM_GRAPH_VAL", 1, bad_dup)

    # 5. Self-loop rejected in finalise
    core.attempt_flag("TEAM_GRAPH_VAL", 1, "tree reconstruction")
    with pytest.raises(ValueError, match="self-loop"):
        core.finalise("TEAM_GRAPH_VAL", 1, bad_self_loop, True, {}, explanation="Test")


# ==============================================================================
# 6. SEQUENTIAL PROGRESSION TESTS
# ==============================================================================

def test_sequential_level_progression_enforcement(isolated_env, monkeypatch):
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM_SEQ", "Sequential Team", "Password123!")

    # Attempting flag for Level 2 before Level 1 is complete is blocked
    res_l2_flag = core.attempt_flag("TEAM_SEQ", 2, "leaf-only observations")
    assert res_l2_flag["correct"] is False
    assert "complete Level 1 first" in res_l2_flag["message"]

    # Saving draft for Level 2 before Level 1 is complete is blocked
    with pytest.raises(PermissionError, match="complete Level 1 first"):
        core.save_draft("TEAM_SEQ", 2, "source_id,target_id,relationship_type,evidence_reference\nP01,P02,EXTENDS,Ref\n")

    # Finalizing Level 2 before Level 1 is complete is blocked
    with pytest.raises(PermissionError, match="complete Level 1 first"):
        core.finalise("TEAM_SEQ", 2, "source_id,target_id,relationship_type,evidence_reference\nP01,P02,EXTENDS,Ref\n", True, {}, explanation="L2 early")

    # Complete Level 1 legitimately
    core.attempt_flag("TEAM_SEQ", 1, "tree reconstruction")
    core.finalise("TEAM_SEQ", 1, "source_id,target_id,relationship_type,evidence_reference\nP01,P02,EXTENDS,Ref\n", True, {}, explanation="L1 done")

    # Now Level 2 is unlocked
    completed, current = core.team_progress("TEAM_SEQ")
    assert completed == [1]
    assert current == 2

    # Level 2 flag attempt is now accepted
    res_l2_now = core.attempt_flag("TEAM_SEQ", 2, "leaf-only observations")
    assert res_l2_now["correct"] is True


def test_level_0_demo_progression(isolated_env, monkeypatch):
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    demo_id = core.ensure_demo_team("DEMO_SEQ", "Demo Progression", "DemoPass123!")

    # Demo cluster only has level 0; level 1 must be rejected
    res_bad = core.attempt_flag(demo_id, 1, "tree reconstruction")
    assert res_bad["correct"] is False
    assert "not configured" in res_bad["message"]

    with pytest.raises(ValueError, match="not configured"):
        core.save_draft(demo_id, 1, "source_id,target_id,relationship_type\nL0A,L0B,EXTENDS\n")


# ==============================================================================
# 7. GRAPH OWNERSHIP AND TEAM ISOLATION
# ==============================================================================

def test_graph_ownership_and_team_isolation(isolated_env):
    core.create_team("TEAM_OWNER_A", "Team A", "Password123!")
    core.create_team("TEAM_OWNER_B", "Team B", "Password123!")

    graph_a = core.get_team_graph("TEAM_OWNER_A")
    assert graph_a.team_id == "TEAM_OWNER_A"

    # 1. Non-existent team cannot save graph
    with pytest.raises(ValueError, match="does not exist"):
        core.save_team_graph("NON_EXISTENT", graph_a)

    # 2. Team A's graph cannot be saved under Team B's ID
    with pytest.raises(ValueError, match="does not match"):
        core.save_team_graph("TEAM_OWNER_B", graph_a)

    # 3. Valid save under own ID succeeds
    core.save_team_graph("TEAM_OWNER_A", graph_a)


# ==============================================================================
# 8. CONFIGURATION VALIDATION TESTS
# ==============================================================================

def test_configuration_validation_errors(tmp_path):
    bad_cfg_file = tmp_path / "bad_config.json"

    # 1. Non-existent file
    with pytest.raises(core.ConfigurationError, match="not found"):
        core.load_config(tmp_path / "missing.json")

    # 2. Malformed JSON
    bad_cfg_file.write_text("{ unclosed json: ", encoding="utf-8")
    with pytest.raises(core.ConfigurationError, match="Malformed"):
        core.load_config(bad_cfg_file)

    # 3. Invalid cooldown seconds (negative)
    cfg = copy.deepcopy(core._CFG)
    cfg["rules"]["cooldown_seconds"] = -10
    bad_cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
    with pytest.raises(core.ConfigurationError, match="cooldown_seconds"):
        core.load_config(bad_cfg_file)

    # 4. Invalid point values (zero or negative)
    cfg = copy.deepcopy(core._CFG)
    cfg["rules"]["flag_points_per_level"] = 0
    bad_cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
    with pytest.raises(core.ConfigurationError, match="flag_points_per_level"):
        core.load_config(bad_cfg_file)

    # 5. Inconsistent cluster definition
    cfg = copy.deepcopy(core._CFG)
    cfg["default_cluster"] = "UnknownCluster"
    bad_cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
    with pytest.raises(core.ConfigurationError, match="default_cluster"):
        core.load_config(bad_cfg_file)


# ==============================================================================
# 9. MULTIPROCESS CONCURRENCY TESTS (REAL SEPARATE PROCESSES)
# ==============================================================================

def test_multiprocess_simultaneous_team_registration(isolated_env):
    state_file = isolated_env / "event_state.json"
    tasks = [(f"MP_TEAM_{i:02d}", f"MP Team {i}", "Password123!", state_file) for i in range(8)]

    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=4) as pool:
        results = pool.map(_mp_register_worker, tasks)

    assert all(r is True for r in results)
    d = core.load()
    for i in range(8):
        assert f"MP_TEAM_{i:02d}" in d["teams"]


def test_multiprocess_simultaneous_flag_attempts(isolated_env, monkeypatch):
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("MP_FLAG_TEAM", "MP Flag Team", "Password123!")
    state_file = isolated_env / "event_state.json"

    tasks = [("MP_FLAG_TEAM", 1, f"wrong attempt {i}", state_file) for i in range(6)]

    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=4) as pool:
        results = pool.map(_mp_flag_attempt_worker, tasks)

    # All 6 attempts should be logged without data loss
    st = core.flag_status("MP_FLAG_TEAM", 1)
    assert st["attempts"] == 6
    assert st["wrong_attempts"] == 6
    assert st["penalty_points"] == 1  # 6th attempt incurs 1 point penalty


def test_multiprocess_simultaneous_final_submissions_exactly_one_succeeds(isolated_env, monkeypatch):
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("MP_SUB_TEAM", "MP Sub Team", "Password123!")
    core.attempt_flag("MP_SUB_TEAM", 1, "tree reconstruction")
    state_file = isolated_env / "event_state.json"

    csv_text = "source_id,target_id,relationship_type,evidence_reference\nP01,P02,EXTENDS,Ref\n"
    tasks = [("MP_SUB_TEAM", 1, csv_text, f"Explanation from proc {i}", state_file) for i in range(5)]

    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=5) as pool:
        results = pool.map(_mp_finalise_worker, tasks)

    # Exactly one process must succeed, all other processes receive LOCKED
    assert results.count("SUCCESS") == 1
    assert results.count("LOCKED") == 4

    d = core.load()
    assert d["submissions"]["MP_SUB_TEAM:1"]["locked"] is True


def test_multiprocess_simultaneous_graph_draft_updates(isolated_env):
    state_file = isolated_env / "event_state.json"
    for i in range(4):
        core.create_team(f"MP_DRAFT_{i}", f"Draft Team {i}", "Password123!")

    tasks = [
        (f"MP_DRAFT_{i}", 1, "source_id,target_id,relationship_type,evidence_reference\nP01,P02,EXTENDS,Ref\n", state_file)
        for i in range(4)
    ]

    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=4) as pool:
        results = pool.map(_mp_graph_draft_worker, tasks)

    assert all(r == "OK" for r in results)
    for i in range(4):
        assert "P01" in core.get_draft(f"MP_DRAFT_{i}", 1)


# ==============================================================================
# 10. SECURITY & TAMPERING PREVENTION TESTS
# ==============================================================================

def test_security_answer_keys_not_exposed(isolated_env):
    core.create_team("TEAM_SEC", "Security Team", "Password123!")

    res_wrong = core.attempt_flag("TEAM_SEC", 1, "random string")
    res_str = json.dumps(res_wrong).lower()
    assert "tree reconstruction" not in res_str
    assert "answers" not in res_wrong

    res_correct = core.attempt_flag("TEAM_SEC", 1, "tree reconstruction")
    res_c_str = json.dumps(res_correct).lower()
    assert "reconstructing a tree" not in res_c_str
    assert "answers" not in res_correct


def test_security_client_cannot_tamper_scores_or_cluster(isolated_env, monkeypatch):
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM_TAMPER", "Tamper Team", "Password123!", cluster=core.CLUSTER)
    core.attempt_flag("TEAM_TAMPER", 1, "wrong answer")

    graph_csv = "source_id,target_id,relationship_type,evidence_reference\nP01,P02,EXTENDS,Sec. 1\n"
    rec = core.finalise(
        team="TEAM_TAMPER",
        level=1,
        csv_text=graph_csv,
        flag_correct=True,
        graph_score={"points": 10.0},
        explanation="Explanation",
    )
    assert rec["flag_correct"] is False
    assert rec["flag_points"] == 0


# ==============================================================================
# 11. FINAL SECTION A HARDENING REGRESSION TESTS
# ==============================================================================

def test_locked_edge_deletion_prevention(isolated_env, monkeypatch):
    """Regression test 1: Prevent deletion or modification of locked graph edges."""
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM_LOCKED_EDGE", "Locked Edge Team", "Password123!")

    # 2. Add an edge and attempt flag
    edge_csv = "source_id,target_id,relationship_type,evidence_reference\nP01,P02,EXTENDS,Section 3.1 Page 4\n"
    core.save_draft("TEAM_LOCKED_EDGE", 1, edge_csv)
    core.attempt_flag("TEAM_LOCKED_EDGE", 1, "tree reconstruction")

    # 3. Finalize Level 1
    core.finalise(
        "TEAM_LOCKED_EDGE",
        1,
        edge_csv,
        explanation="Initial proof-of-thought graph reconstruction",
    )

    # 4. Retrieve active graph
    graph = core.get_team_graph("TEAM_LOCKED_EDGE")
    assert len(graph.edges) == 1
    orig_edge = graph.edges[0]
    assert orig_edge.source_id == "P01"
    assert orig_edge.target_id == "P02"
    assert orig_edge.relationship_type == "EXTENDS"
    assert orig_edge.evidence_reference == "Section 3.1 Page 4"
    assert orig_edge.added_at_level == 1

    # Verify snapshot was created and contains the edge
    snap1 = graph.get_snapshot(1)
    assert snap1 is not None
    assert len(snap1.edges) == 1

    # 5. Remove the previously submitted edge from the active graph
    graph.edges.clear()
    assert len(graph.edges) == 0

    # 6. Call save_team_graph() -> Verify PermissionError is raised
    with pytest.raises(PermissionError, match="cannot be removed, altered, or reassigned"):
        core.save_team_graph("TEAM_LOCKED_EDGE", graph)

    # 7. Verify that both active graph and historical snapshot remain unchanged
    reloaded_graph = core.get_team_graph("TEAM_LOCKED_EDGE")
    assert len(reloaded_graph.edges) == 1
    assert reloaded_graph.edges[0].source_id == "P01"
    assert reloaded_graph.edges[0].target_id == "P02"
    assert reloaded_graph.edges[0].relationship_type == "EXTENDS"
    assert reloaded_graph.edges[0].evidence_reference == "Section 3.1 Page 4"
    assert reloaded_graph.edges[0].added_at_level == 1

    reloaded_snap = reloaded_graph.get_snapshot(1)
    assert reloaded_snap is not None
    assert len(reloaded_snap.edges) == 1
    assert reloaded_snap.edges[0]["source_id"] == "P01"
    assert reloaded_snap.edges[0]["evidence_reference"] == "Section 3.1 Page 4"
    assert reloaded_snap.edges[0]["added_at_level"] == 1


def test_locked_edge_level_reassignment(isolated_env, monkeypatch):
    """Regression test: Changing locked edge added_at_level to 2 is rejected; state unchanged."""
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM_REASSIGN", "Reassign Team", "Password123!")
    edge_csv = "source_id,target_id,relationship_type,evidence_reference\nP01,P02,EXTENDS,Section 1\n"
    core.attempt_flag("TEAM_REASSIGN", 1, "tree reconstruction")
    core.finalise("TEAM_REASSIGN", 1, edge_csv, explanation="L1 done")

    graph = core.get_team_graph("TEAM_REASSIGN")
    assert graph.edges[0].added_at_level == 1

    # Tamper: change added_at_level to 2
    graph.edges = [
        GraphEdge(
            source_id="P01",
            target_id="P02",
            relationship_type="EXTENDS",
            evidence_reference="Section 1",
            added_at_level=2,
        )
    ]
    with pytest.raises(PermissionError, match="cannot be removed, altered, or reassigned"):
        core.save_team_graph("TEAM_REASSIGN", graph)

    # Verify persisted state remains strictly unchanged
    reloaded = core.get_team_graph("TEAM_REASSIGN")
    assert reloaded.edges[0].added_at_level == 1
    snap = reloaded.get_snapshot(1)
    assert snap.edges[0]["added_at_level"] == 1


def test_locked_edge_evidence_alteration(isolated_env, monkeypatch):
    """Regression test: Altering locked edge evidence_reference is rejected; state unchanged."""
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM_ALT_EV", "Evidence Alt Team", "Password123!")
    edge_csv = "source_id,target_id,relationship_type,evidence_reference\nP01,P02,EXTENDS,Original Evidence\n"
    core.attempt_flag("TEAM_ALT_EV", 1, "tree reconstruction")
    core.finalise("TEAM_ALT_EV", 1, edge_csv, explanation="L1 done")

    graph = core.get_team_graph("TEAM_ALT_EV")

    # Tamper: alter evidence
    graph.edges = [
        GraphEdge(
            source_id="P01",
            target_id="P02",
            relationship_type="EXTENDS",
            evidence_reference="Tampered Evidence",
            added_at_level=1,
        )
    ]
    with pytest.raises(PermissionError, match="cannot be removed, altered, or reassigned"):
        core.save_team_graph("TEAM_ALT_EV", graph)

    # Verify persisted state remains unchanged
    reloaded = core.get_team_graph("TEAM_ALT_EV")
    assert reloaded.edges[0].evidence_reference == "Original Evidence"


def test_locked_edge_deletion_direct(isolated_env, monkeypatch):
    """Regression test: Deleting a locked edge is rejected; state unchanged."""
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM_DEL_EDGE", "Del Edge Team", "Password123!")
    edge_csv = "source_id,target_id,relationship_type,evidence_reference\nP01,P02,EXTENDS,Section 1\n"
    core.attempt_flag("TEAM_DEL_EDGE", 1, "tree reconstruction")
    core.finalise("TEAM_DEL_EDGE", 1, edge_csv, explanation="L1 done")

    graph = core.get_team_graph("TEAM_DEL_EDGE")
    graph.edges = []
    with pytest.raises(PermissionError, match="cannot be removed, altered, or reassigned"):
        core.save_team_graph("TEAM_DEL_EDGE", graph)

    reloaded = core.get_team_graph("TEAM_DEL_EDGE")
    assert len(reloaded.edges) == 1
    assert reloaded.edges[0].source_id == "P01"


def test_evidence_validation_server_side(isolated_env, monkeypatch):
    """Regression test 2: Enforce server-side evidence validation across all entrypoints."""
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM_EVIDENCE", "Evidence Team", "Password123!")

    # 1. save_draft rejects missing evidence
    bad_missing_ev = "source_id,target_id,relationship_type,evidence_reference\nP01,P02,EXTENDS,\n"
    with pytest.raises(ValueError, match="missing or empty evidence_reference"):
        core.save_draft("TEAM_EVIDENCE", 1, bad_missing_ev)

    # 2. save_draft rejects whitespace-only evidence
    bad_ws_ev = "source_id,target_id,relationship_type,evidence_reference\nP01,P02,EXTENDS,   \t  \n"
    with pytest.raises(ValueError, match="missing or empty evidence_reference"):
        core.save_draft("TEAM_EVIDENCE", 1, bad_ws_ev)

    # 3. save_team_graph rejects edges with missing or whitespace-only evidence
    graph = core.get_team_graph("TEAM_EVIDENCE")
    graph.edges = [
        GraphEdge(source_id="P01", target_id="P02", relationship_type="EXTENDS", evidence_reference="   ")
    ]
    with pytest.raises(ValueError, match="missing or empty evidence_reference"):
        core.save_team_graph("TEAM_EVIDENCE", graph)

    # 4. finalise rejects edges with missing or whitespace evidence
    core.attempt_flag("TEAM_EVIDENCE", 1, "tree reconstruction")
    with pytest.raises(ValueError, match="missing or empty evidence_reference"):
        core.finalise("TEAM_EVIDENCE", 1, bad_missing_ev, explanation="Valid explanation")

    with pytest.raises(ValueError, match="missing or empty evidence_reference"):
        core.finalise("TEAM_EVIDENCE", 1, bad_ws_ev, explanation="Valid explanation")

    # 5. Valid evidence succeeds across save_draft, save_team_graph, and finalise
    valid_csv = "source_id,target_id,relationship_type,evidence_reference\nP01,P02,EXTENDS,Fig 3b on page 7\n"
    core.save_draft("TEAM_EVIDENCE", 1, valid_csv)
    g = core.get_team_graph("TEAM_EVIDENCE")
    assert len(g.edges) == 1
    assert g.edges[0].evidence_reference == "Fig 3b on page 7"

    # save_team_graph with valid evidence
    core.save_team_graph("TEAM_EVIDENCE", g)

    # finalise with valid evidence succeeds
    rec = core.finalise("TEAM_EVIDENCE", 1, valid_csv, explanation="Detailed explanation")
    assert rec["edge_count"] == 1
    assert rec["locked"] is True


def test_empty_state_handling_quarantine(isolated_env):
    """Regression test 3: Existing empty state file is treated as corrupted, quarantined, not overwritten."""
    # Write an empty (0 byte) state file
    core.STATE.write_text("", encoding="utf-8")
    assert core.STATE.exists()
    assert core.STATE.stat().st_size == 0

    # Normal load must raise CorruptedStateError and create quarantine backup
    with pytest.raises(core.CorruptedStateError, match="corrupted"):
        core.load()

    # Original file is preserved and not silently overwritten
    assert core.STATE.exists()

    # Quarantine file must exist in data/submissions/
    quarantine_files = list(core.STATE.parent.glob(f"{core.STATE.stem}_corrupted_*"))
    assert len(quarantine_files) >= 1

    # Attempting to create a team without recovery must also fail
    with pytest.raises(core.CorruptedStateError):
        core.create_team("TEAM_FAIL", "Fail Team", "Password123!")

    # Explicit recovery reinitializes cleanly
    recovered = core.recover_corrupted_state()
    assert isinstance(recovered, dict)
    assert recovered["teams"] == {}

    # State now works after explicit recovery
    core.create_team("TEAM_RECOVERED", "Recovered Team", "Password123!")
    assert "TEAM_RECOVERED" in core.load()["teams"]


def test_finalise_rejects_empty_and_header_only_graph(isolated_env, monkeypatch):
    """Regression test 4: finalise() rejects CSV submissions with no relationship edges; level remains unlocked."""
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM_NON_EMPTY", "Non Empty Graph Team", "Password123!")
    core.attempt_flag("TEAM_NON_EMPTY", 1, "tree reconstruction")

    # 1. Reject empty string CSV
    with pytest.raises(ValueError, match="at least one relationship edge|required to finalize"):
        core.finalise("TEAM_NON_EMPTY", 1, "", explanation="Explanation for empty")

    # Verify level is NOT locked
    completed, current = core.team_progress("TEAM_NON_EMPTY")
    assert completed == []
    assert current == 1

    # 2. Reject header-only CSV (no edges)
    header_only_csv = "source_id,target_id,relationship_type,evidence_reference\n"
    with pytest.raises(ValueError, match="at least one relationship edge"):
        core.finalise("TEAM_NON_EMPTY", 1, header_only_csv, explanation="Explanation for header only")

    # Verify level is STILL not locked
    completed, current = core.team_progress("TEAM_NON_EMPTY")
    assert completed == []
    assert current == 1

    # 3. Empty drafts ARE permitted in save_draft
    core.save_draft("TEAM_NON_EMPTY", 1, header_only_csv)
    assert core.get_draft("TEAM_NON_EMPTY", 1) == header_only_csv

    # 4. Submission with actual relationship edge succeeds and locks level
    valid_csv = "source_id,target_id,relationship_type,evidence_reference\nP01,P02,EXTENDS,Section 2\n"
    core.finalise("TEAM_NON_EMPTY", 1, valid_csv, explanation="Valid final graph")

    completed, current = core.team_progress("TEAM_NON_EMPTY")
    assert completed == [1]
    assert current == 2


def test_empty_graph_submission_filename_bypass_eliminated(isolated_env, monkeypatch):
    """Regression test: Confirm that caller filename matching 'test_event_workflow.py' cannot bypass empty graph check."""
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM_BYPASS_CHECK", "Bypass Check Team", "Password123!")
    core.attempt_flag("TEAM_BYPASS_CHECK", 1, "tree reconstruction")

    # Compile and execute runner with filename pretending to be test_event_workflow.py
    code = compile(
        "import event_core as c\n"
        "c.finalise('TEAM_BYPASS_CHECK', 1, 'source_id,target_id,relationship_type,evidence_reference\\n', explanation='attempt')\n",
        "/some/path/to/test_event_workflow.py",
        "exec",
    )

    with pytest.raises(ValueError, match="at least one relationship edge"):
        exec(code, {"__name__": "__main__"})

    # Verify level is NOT locked
    completed, current = core.team_progress("TEAM_BYPASS_CHECK")
    assert completed == []
    assert current == 1


def test_configuration_consistency_and_authoritative_definitions(isolated_env):
    """Regression test 5: Configuration consistency with event_content.csv and operational demo team."""
    # 1. Configured clusters are available
    clusters = core.clusters(include_demo=True)
    assert "Hidden Structures: Networking × Evolutionary Biology" in clusters
    assert "Level 0 Demo" in clusters

    # 2. ensure_demo_team() uses configured demo team settings
    demo_tid = core.ensure_demo_team()
    assert demo_tid == "DEMO00"
    team_data = core.load()["teams"]["DEMO00"]
    assert team_data["name"] == "Level 0 Demo Team"
    assert team_data["cluster"] == "Level 0 Demo"
    assert team_data["is_demo"] is True

    # 3. validate_config checks num_levels against event_content.csv
    valid_cfg = {
        "num_levels": 4,
        "default_cluster": core.CLUSTER,
        "clusters": [core.CLUSTER, "Level 0 Demo"],
        "rules": {},
    }
    assert core.validate_config(valid_cfg) == []

    mismatched_cfg = {
        "num_levels": 99,
        "default_cluster": core.CLUSTER,
        "clusters": [core.CLUSTER],
    }
    errs = core.validate_config(mismatched_cfg)
    assert any("does not match authoritative level count" in e for e in errs)
