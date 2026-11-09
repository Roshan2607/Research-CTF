import pytest
import event_core as core


def test_four_level_pipeline_and_locking(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "STATE", tmp_path / "event_state.json")
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)  # bypass cooldown for fast test
    core.create_team("TEAM01", "Pilot Team", "StrongPass123")
    assert core.authenticate("team01", "StrongPass123")["name"] == "Pilot Team"
    assert core.authenticate("TEAM01", "wrong") is None

    for level, answer in enumerate([
        "tree reconstruction",
        "leaf-only observations",
        "hidden internal structure",
        "shared path similarity",
    ], 1):
        assert core.team_progress("TEAM01")[1] == level
        assert core.attempt_flag("TEAM01", level, "not it")["correct"] is False
        assert core.attempt_flag("TEAM01", level, answer)["correct"] is True
        core.save_draft("TEAM01", level, "source_id,target_id,relationship_type,evidence_reference\n")
        core.finalise(
            "TEAM01",
            level,
            "source_id,target_id,relationship_type,evidence_reference\n",
            True,
            {"points": 12.5},
            explanation="Detailed explanation of shared topology inference",
        )
        assert core.team_progress("TEAM01")[1] == (level + 1 if level < 4 else None)
        try:
            core.finalise("TEAM01", level, "changed", True, {}, explanation="new")
            assert False, "submitted level should be immutable"
        except PermissionError:
            pass

    snap = core.admin_snapshot()
    assert len(snap["submissions"]) == 4
    sub1 = snap["submissions"]["TEAM01:1"]
    assert sub1["explanation"] == "Detailed explanation of shared topology inference"
    assert sub1["flag_points"] == 10  # 1 wrong attempt, well within 5 free attempts


def test_flag_attempts_do_not_unlock_next_level(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "STATE", tmp_path / "event_state.json")
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM02", "Another Team", "StrongPass123")
    core.attempt_flag("TEAM02", 1, "tree reconstruction")
    assert core.team_progress("TEAM02") == ([], 1)


def test_finalise_requires_a_flag_attempt_but_not_a_correct_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "STATE", tmp_path / "event_state.json")
    monkeypatch.setattr(core, "LOG", tmp_path / "events.jsonl")
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM03", "Flag Required Team", "StrongPass123")

    graph = "source_id,target_id,relationship_type,evidence_reference\n"
    try:
        core.finalise("TEAM03", 1, graph, False, {}, explanation="test")
        assert False, "a flag attempt must be required"
    except ValueError:
        pass

    result = core.attempt_flag("TEAM03", 1, "wrong answer")
    assert result["correct"] is False
    rec = core.finalise("TEAM03", 1, graph, False, {}, explanation="test explanation")
    assert rec["flag_correct"] is False
    assert rec["flag_points"] == 0
    assert rec["explanation"] == "test explanation"
    assert core.team_progress("TEAM03") == ([1], 2)


def test_flag_cooldown_enforcement(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "STATE", tmp_path / "event_state.json")
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 30)
    core.create_team("TEAM_CD", "Cooldown Team", "StrongPass123")

    first_attempt = core.attempt_flag("TEAM_CD", 1, "wrong answer 1")
    assert first_attempt["correct"] is False
    assert first_attempt.get("cooldown_remaining", 0) == 30

    # Immediate second attempt should trigger cooldown
    second_attempt = core.attempt_flag("TEAM_CD", 1, "wrong answer 2")
    assert second_attempt["correct"] is False
    assert second_attempt.get("cooldown") is True
    assert second_attempt["cooldown_remaining"] > 0
    assert "Cooldown active" in second_attempt["message"]


def test_flag_penalty_scaling(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "STATE", tmp_path / "event_state.json")
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM_PEN", "Penalty Team", "StrongPass123")

    # 5 wrong attempts should all be free
    for i in range(1, 6):
        res = core.attempt_flag("TEAM_PEN", 1, f"wrong {i}")
        assert res["correct"] is False
        status = core.flag_status("TEAM_PEN", 1)
        assert status["penalty_points"] == 0

    # 6th wrong attempt costs 1 point
    res6 = core.attempt_flag("TEAM_PEN", 1, "wrong 6")
    assert res6["correct"] is False
    status6 = core.flag_status("TEAM_PEN", 1)
    assert status6["wrong_attempts"] == 6
    assert status6["penalty_points"] == 1

    # 7th wrong attempt costs 2 points total
    res7 = core.attempt_flag("TEAM_PEN", 1, "wrong 7")
    status7 = core.flag_status("TEAM_PEN", 1)
    assert status7["wrong_attempts"] == 7
    assert status7["penalty_points"] == 2

    # Now solve correctly: earned points = 10 - 2 = 8
    res_correct = core.attempt_flag("TEAM_PEN", 1, "tree reconstruction")
    assert res_correct["correct"] is True
    assert res_correct["earned_points"] == 8

    # Finalise and verify points recorded in submission
    rec = core.finalise(
        "TEAM_PEN",
        1,
        "source_id,target_id,relationship_type,evidence_reference\n",
        True,
        {"points": 14.0},
        explanation="Solves shared task via neighbor joining",
    )
    assert rec["flag_correct"] is True
    assert rec["flag_points"] == 8


def test_demo_team_isolation(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "STATE", tmp_path / "event_state.json")
    core.create_team("REAL01", "Real Team", "StrongPass123", is_demo=False)
    core.create_team("DEMO01", "Demo Facilitator", "StrongPass123", is_demo=True)

    snap = core.admin_snapshot()
    teams = {t["team_id"]: t for t in snap["teams"]}
    assert teams["REAL01"]["is_demo"] is False
    assert teams["DEMO01"]["is_demo"] is True


def test_organiser_score_adjustment(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "STATE", tmp_path / "event_state.json")
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM_ADJ", "Adjustment Team", "StrongPass123")
    core.attempt_flag("TEAM_ADJ", 1, "tree reconstruction")
    core.finalise(
        "TEAM_ADJ",
        1,
        "source_id,target_id,relationship_type,evidence_reference\n",
        True,
        {"points": 10.0},
        explanation="Initial student explanation",
    )

    updated = core.adjust_submission_score("TEAM_ADJ", 1, manual_adjustment=2.5, notes="Excellent cross-paper reasoning")
    assert updated["manual_adjustment"] == 2.5
    assert updated["organiser_notes"] == "Excellent cross-paper reasoning"


def test_clusters_can_be_created_from_a_template(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "STATE", tmp_path / "event_state.json")
    monkeypatch.setattr(core, "LOG", tmp_path / "events.jsonl")
    monkeypatch.setattr(core, "CONTENT", tmp_path / "event_content.csv")
    source_rows = core._read_csv(core.ROOT / "data" / "event_content.csv")
    import csv

    with core.CONTENT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(source_rows[0]))
        writer.writeheader()
        writer.writerows(source_rows)

    new_name = "Second Test Cluster"
    core.create_cluster_from_template(new_name, core.CLUSTER)
    assert new_name in core.clusters()
    assert len(core.levels_for_cluster(new_name)) == 4
    core.create_team("TEAM04", "Second Cluster Team", "StrongPass123", new_name)
    assert core.authenticate("TEAM04", "StrongPass123")["cluster"] == new_name


def test_parse_uploaded_graph_csv_standard_and_codex():
    available = ["P01", "P02", "P03"]
    allowed_rels = ["USES_DATA", "EXTENDS", "ANALOGOUS_PROBLEM"]

    # 1. Standard format
    standard_csv = "source_id,target_id,relationship_type,evidence_reference\nP02,P01,USES_DATA,Page 3 Section 2\n"
    rows, errs = core.parse_uploaded_graph_csv(standard_csv, available, allowed_rels)
    assert not errs
    assert len(rows) == 1
    assert rows[0]["source_id"] == "P02"
    assert rows[0]["relationship_type"] == "USES_DATA"

    # 2. Codex variant format (source, target, relation, evidence)
    codex_csv = "source,target,relation,evidence\nP03,P01,EXTENDS,Section 4\n"
    rows, errs = core.parse_uploaded_graph_csv(codex_csv, available, allowed_rels)
    assert not errs
    assert len(rows) == 1
    assert rows[0]["source_id"] == "P03"

    # 3. Invalid inputs: self loop, unknown paper, invalid rel
    bad_csv = (
        "source_id,target_id,relationship_type\n"
        "P01,P01,USES_DATA\n"        # self-loop
        "P99,P01,USES_DATA\n"        # unreleased paper
        "P02,P01,INVALID_RELATION\n" # invalid rel
    )
    rows, errs = core.parse_uploaded_graph_csv(bad_csv, available, allowed_rels)
    assert len(errs) == 3
    assert any("self-loop" in e for e in errs)
    assert any("unreleased" in e for e in errs)
    assert any("invalid relationship_type" in e for e in errs)
