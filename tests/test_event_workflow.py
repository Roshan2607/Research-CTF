import pytest
import event_core as core


def test_four_level_pipeline_and_locking(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "STATE", tmp_path / "event_state.json")
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)  # bypass cooldown for fast test
    core.create_team("TEAM01", "Pilot Team", "StrongPass123")
    assert core.authenticate("team01", "StrongPass123")["name"] == "Pilot Team"
    assert core.authenticate("TEAM01", "wrong") is None

    # Complete Level 0 demo onboarding
    assert core.team_progress("TEAM01")[1] == 0
    assert core.attempt_flag("TEAM01", 0, "wrong")["correct"] is False
    assert core.attempt_flag("TEAM01", 0, "FLAG{TRIE}")["correct"] is True
    core.save_draft("TEAM01", 0, "source_id,target_id,relationship_type,evidence_reference\n")
    core.finalise(
        "TEAM01",
        0,
        "source_id,target_id,relationship_type,evidence_reference\n",
        True,
        {"points": 15.0},
        explanation="Level 0 demo onboarding",
    )
    assert core.team_progress("TEAM01")[1] == 1

    level_graphs = {
        1: "source_id,target_id,relationship_type,evidence_reference\nP01,P02,EXTENDS,Section 1 Page 2\n",
        2: "source_id,target_id,relationship_type,evidence_reference\nP01,P02,EXTENDS,Section 1 Page 2\nP02,P03,CITES,Section 2 Page 5\n",
        3: "source_id,target_id,relationship_type,evidence_reference\nP01,P02,EXTENDS,Section 1 Page 2\nP02,P03,CITES,Section 2 Page 5\nP03,P05,CITES,Section 3 Page 8\n",
        4: "source_id,target_id,relationship_type,evidence_reference\nP01,P02,EXTENDS,Section 1 Page 2\nP02,P03,CITES,Section 2 Page 5\nP03,P05,CITES,Section 3 Page 8\nP05,P07,CITES,Section 4 Page 11\n",
    }

    # Complete competition levels 1 through 4
    for level, answer in enumerate([
        "tree reconstruction",
        "leaf-only observations",
        "hidden internal structure",
        "shared path similarity",
    ], 1):
        assert core.team_progress("TEAM01")[1] == level
        assert core.attempt_flag("TEAM01", level, "not it")["correct"] is False
        assert core.attempt_flag("TEAM01", level, answer)["correct"] is True
        core.save_draft("TEAM01", level, level_graphs[level])
        core.finalise(
            "TEAM01",
            level,
            level_graphs[level],
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
    assert len(snap["submissions"]) == 5
    sub1 = snap["submissions"]["TEAM01:1"]
    assert sub1["explanation"] == "Detailed explanation of shared topology inference"
    assert sub1["flag_points"] == 10  # 1 wrong attempt, well within 5 free attempts


def test_flag_attempts_do_not_unlock_next_level(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "STATE", tmp_path / "event_state.json")
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM02", "Another Team", "StrongPass123")
    core.attempt_flag("TEAM02", 0, "FLAG{TRIE}")
    assert core.team_progress("TEAM02") == ([], 0)


def test_finalise_requires_a_flag_attempt_but_not_a_correct_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "STATE", tmp_path / "event_state.json")
    monkeypatch.setattr(core, "LOG", tmp_path / "events.jsonl")
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM03", "Flag Required Team", "StrongPass123")

    graph = "source_id,target_id,relationship_type,evidence_reference\n"
    try:
        core.finalise("TEAM03", 0, graph, False, {}, explanation="test")
        assert False, "a flag attempt must be required"
    except ValueError:
        pass

    result = core.attempt_flag("TEAM03", 0, "wrong answer")
    assert result["correct"] is False
    rec = core.finalise("TEAM03", 0, graph, False, {}, explanation="test explanation")
    assert rec["flag_correct"] is False
    assert rec["flag_points"] == 0
    assert rec["explanation"] == "test explanation"
    assert core.team_progress("TEAM03") == ([0], 1)


def test_flag_cooldown_enforcement(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "STATE", tmp_path / "event_state.json")
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 30)
    core.create_team("TEAM_CD", "Cooldown Team", "StrongPass123")

    first_attempt = core.attempt_flag("TEAM_CD", 0, "wrong answer 1")
    assert first_attempt["correct"] is False
    assert first_attempt.get("cooldown_remaining", 0) == 30

    # Immediate second attempt should trigger cooldown
    second_attempt = core.attempt_flag("TEAM_CD", 0, "wrong answer 2")
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
        res = core.attempt_flag("TEAM_PEN", 0, f"wrong {i}")
        assert res["correct"] is False
        status = core.flag_status("TEAM_PEN", 0)
        assert status["penalty_points"] == 0

    # 6th wrong attempt costs 1 point
    res6 = core.attempt_flag("TEAM_PEN", 0, "wrong 6")
    assert res6["correct"] is False
    status6 = core.flag_status("TEAM_PEN", 0)
    assert status6["wrong_attempts"] == 6
    assert status6["penalty_points"] == 1

    # 7th wrong attempt costs 2 points total
    res7 = core.attempt_flag("TEAM_PEN", 0, "wrong 7")
    status7 = core.flag_status("TEAM_PEN", 0)
    assert status7["wrong_attempts"] == 7
    assert status7["penalty_points"] == 2

    # Now solve correctly: earned points = 10 - 2 = 8
    res_correct = core.attempt_flag("TEAM_PEN", 0, "FLAG{TRIE}")
    assert res_correct["correct"] is True
    assert res_correct["earned_points"] == 8

    # Finalise and verify points recorded in submission
    rec = core.finalise(
        "TEAM_PEN",
        0,
        "source_id,target_id,relationship_type,evidence_reference\n",
        True,
        {"points": 14.0},
        explanation="Solves shared task via trie prefix tree",
    )
    assert rec["flag_correct"] is True
    assert rec["flag_points"] == 8


def test_demo_team_isolation(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "STATE", tmp_path / "event_state.json")
    core.create_team("REAL01", "Real Team", "StrongPass123", is_demo=False)
    core.ensure_demo_team("DEMO01", "Demo Facilitator", "StrongPass123")

    snap = core.admin_snapshot()
    teams = {t["team_id"]: t for t in snap["teams"]}
    demo_teams = {t["team_id"]: t for t in snap["demo_teams"]}
    assert "REAL01" in teams
    assert "DEMO01" not in teams  # completely isolated from official leaderboard
    assert "DEMO01" in demo_teams


def test_organiser_score_adjustment(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "STATE", tmp_path / "event_state.json")
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM_ADJ", "Adjustment Team", "StrongPass123")
    core.attempt_flag("TEAM_ADJ", 0, "FLAG{TRIE}")
    core.finalise(
        "TEAM_ADJ",
        0,
        "source_id,target_id,relationship_type,evidence_reference\n",
        True,
        {"points": 10.0},
        explanation="Initial student explanation",
    )

    updated = core.adjust_submission_score("TEAM_ADJ", 0, manual_adjustment=2.5, notes="Excellent cross-paper reasoning")
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
    assert len(core.levels_for_cluster(new_name)) == 5
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


def test_level_0_demo_workflow(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "STATE", tmp_path / "event_state.json")
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    demo = core.load_demo_level0()
    assert demo["flag"] == "FLAG{TRIE}"
    assert "FLAG{WRONG}" in demo["planted_injection"]
    assert demo["synthetic"] is True
    assert len(demo["papers"]) == 2
    assert core.check_demo_flag("FLAG{TRIE}") is True
    assert core.check_demo_flag("trie") is True
    assert core.check_demo_flag("FLAG{WRONG}") is False

    # Verify DEMO00 end-to-end journey
    core.ensure_demo_team("DEMO00", "Level 0 Demo Team", "DemoPass123!")
    comp, curr = core.team_progress("DEMO00")
    assert comp == []
    assert curr == 0
    att = core.attempt_flag("DEMO00", 0, "FLAG{TRIE}")
    assert att["correct"] is True
    sub = core.finalise(
        "DEMO00",
        0,
        "source_id,target_id,relationship_type,evidence_reference\nL0A,L0B,SHARES_PRINCIPLE,Prefix deduplication\n",
        True,
        {"points": 15.0},
        explanation="Demo onboarding prefix trees",
    )
    assert sub["level"] == 0
    assert sub["flag_correct"] is True
    comp2, curr2 = core.team_progress("DEMO00")
    assert comp2 == [0]
    assert curr2 is None


def test_only_verified_content_is_configured():
    """Every competition paper must come from the provenance-checked corpus; Level 0 must be labelled synthetic."""
    import json

    assert core.clusters() == [core.CLUSTER]
    corpus = json.loads((core.ROOT / "data/participant/participant_papers.json").read_text(encoding="utf-8"))["papers"]
    verified = {p["participant_id"]: p for p in corpus}
    demo = core.load_demo_level0()
    assert demo.get("synthetic") is True
    demo_ids = {p["id"] for p in demo["papers"]}
    for r in core._content():
        pid = r["paper_id"]
        card = core.ROOT / r["challenge_card_path"]
        assert card.exists(), f"Card not found at {card}"
        if r["level"] == "0":
            assert pid in demo_ids and r["paper_title"].startswith("[Synthetic demo]")
        else:
            assert pid in verified, f"{pid} is not in the verified corpus"
            assert r["paper_title"] == verified[pid]["title"]
    # no card may claim to quote a publication unless its abstract is the verified one
    for p in demo["papers"]:
        assert p["excerpt"].startswith("SYNTHETIC DEMO TEXT")


def test_edge_case_prevent_out_of_order_flags_and_skipping(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "STATE", tmp_path / "event_state.json")
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM_EDGE", "Edge Team", "StrongPass123")

    # Team is on level 0; attempting level 2 flag must be refused
    att2 = core.attempt_flag("TEAM_EDGE", 2, "leaf-only observations")
    assert att2["correct"] is False
    assert "Level 2" in att2["message"]

    # Attempting to finalise level 2 before active level is locked must raise PermissionError
    try:
        core.finalise("TEAM_EDGE", 2, "source_id,target_id,relationship_type\nP01,P02,CITES\n", True, {}, explanation="test")
        assert False, "Finalising level out of order should raise PermissionError"
    except PermissionError:
        pass


def test_edge_case_locked_edges_cannot_be_deleted_or_altered(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "STATE", tmp_path / "event_state.json")
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.create_team("TEAM_LOCK", "Lock Team", "StrongPass123")

    # Solve and finalise level 0
    core.attempt_flag("TEAM_LOCK", 0, "FLAG{TRIE}")
    core.finalise("TEAM_LOCK", 0, "source_id,target_id,relationship_type\nL0A,L0B,SHARES_PRINCIPLE\n", True, {"points": 15.0}, explanation="L0")

    # Solve and finalise level 1 with 2 edges
    core.attempt_flag("TEAM_LOCK", 1, "tree reconstruction")
    l1_csv = "source_id,target_id,relationship_type\nP01,P02,CITES\nP02,P01,EXTENDS\n"
    core.finalise("TEAM_LOCK", 1, l1_csv, True, {"points": 10.0}, explanation="L1 explanation")

    # In level 2, try to submit a graph that dropped P02->P01
    core.attempt_flag("TEAM_LOCK", 2, "leaf-only observations")
    tampered_l2_csv = "source_id,target_id,relationship_type\nP01,P02,CITES\nP03,P04,CITES\n"  # dropped P02->P01 EXTENDS!
    try:
        core.finalise("TEAM_LOCK", 2, tampered_l2_csv, True, {"points": 10.0}, explanation="L2 explanation")
        assert False, "Dropping prior locked edges must be rejected"
    except ValueError as e:
        assert "Prior locked edges" in str(e)

    # Valid cumulative graph including all L1 edges plus new L2 edge succeeds
    valid_l2_csv = "source_id,target_id,relationship_type\nP01,P02,CITES\nP02,P01,EXTENDS\nP03,P04,CITES\n"
    rec = core.finalise("TEAM_LOCK", 2, valid_l2_csv, True, {"points": 10.0}, explanation="L2 explanation")
    assert rec["edge_count"] == 3


def test_edge_case_deduplication_and_max_rows(tmp_path, monkeypatch):
    available = ["P01", "P02"]
    allowed = ["CITES", "EXTENDS"]

    # 1. Duplicates are deduplicated
    dupe_csv = "source_id,target_id,relationship_type\nP01,P02,CITES\nP01,P02,CITES\nP01,P02,CITES\n"
    rows, errs = core.parse_uploaded_graph_csv(dupe_csv, available, allowed)
    assert not errs
    assert len(rows) == 1

    # 2. Exceeding 300 rows is rejected
    large_csv = "source_id,target_id,relationship_type\n" + ("P01,P02,CITES\n" * 350)
    rows, errs = core.parse_uploaded_graph_csv(large_csv, available, allowed)
    assert len(errs) == 1
    assert "Too many rows" in errs[0]
