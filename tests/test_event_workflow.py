import json
import event_core as core


def test_four_level_pipeline_and_locking(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "STATE", tmp_path / "event_state.json")
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
        core.save_draft("TEAM01", level, "source_id,target_id,relationship_type,evidence_reference\\n")
        core.finalise("TEAM01", level, "source_id,target_id,relationship_type,evidence_reference\\n",
                      True, {"points": 30})
        assert core.team_progress("TEAM01")[1] == (level + 1 if level < 4 else None)
        try:
            core.finalise("TEAM01", level, "changed", True, {})
            assert False, "submitted level should be immutable"
        except PermissionError:
            pass

    assert len(core.admin_snapshot()["submissions"]) == 4


def test_flag_attempts_do_not_unlock_next_level(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "STATE", tmp_path / "event_state.json")
    core.create_team("TEAM02", "Another Team", "StrongPass123")
    core.attempt_flag("TEAM02", 1, "tree reconstruction")
    assert core.team_progress("TEAM02") == ([], 1)


def test_finalise_requires_a_flag_attempt_but_not_a_correct_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "STATE", tmp_path / "event_state.json")
    monkeypatch.setattr(core, "LOG", tmp_path / "events.jsonl")
    core.create_team("TEAM03", "Flag Required Team", "StrongPass123")

    graph = "source_id,target_id,relationship_type,evidence_reference\\n"
    try:
        core.finalise("TEAM03", 1, graph, False, {})
        assert False, "a flag attempt must be required"
    except ValueError:
        pass

    result = core.attempt_flag("TEAM03", 1, "wrong answer")
    assert result["correct"] is False
    rec = core.finalise("TEAM03", 1, graph, False, {})
    assert rec["flag_correct"] is False
    assert core.team_progress("TEAM03") == ([1], 2)


def test_clusters_can_be_created_from_a_template(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "STATE", tmp_path / "event_state.json")
    monkeypatch.setattr(core, "LOG", tmp_path / "events.jsonl")
    monkeypatch.setattr(core, "CONTENT", tmp_path / "event_content.csv")
    source_rows = core._read_csv(
        core.ROOT / "data" / "event_content.csv"
    )
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
