"""Headless checks of the event portal and admin console (streamlit.testing AppTest)."""
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

import event_core as core  # noqa: E402

LIVE = core.ROOT / "data" / "event_content.csv"
HDR = "source_id,target_id,relationship_type,evidence_reference\n"
L1 = HDR + "P02,P05,CITES,ref\nP13,P05,CITES,ref\nP13,P02,CITES,ref\nP02,P05,ANALOGOUS_PROBLEM,abstracts\nP05,P13,ANALOGOUS_PROBLEM,abstracts\n"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "CONTENT", LIVE)
    monkeypatch.delenv("UL_EVENT_CONTENT", raising=False)
    monkeypatch.setattr(core, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(core, "LOG", tmp_path / "events.jsonl")
    monkeypatch.setattr(core, "TEAM_CSV", tmp_path / "teams.csv")
    monkeypatch.setattr(core, "SUB_CSV", tmp_path / "subs.csv")
    monkeypatch.setattr(core, "COOLDOWN_SECONDS", 0)
    core.save(core._empty())
    core.create_team("TEAM01", "Alpha", "StrongPass123")
    return tmp_path


def _ok(at):
    assert not at.exception, [str(e.value)[:400] for e in at.exception]


def _login(at):
    at.text_input[0].input("TEAM01")
    at.text_input[1].input("StrongPass123")
    at.button[0].click()
    at.run()
    _ok(at)


def _go(at, section):
    at.radio[0].set_value(section).run()
    _ok(at)


def test_portal_flow_level0_to_level1(env):
    at = AppTest.from_file(str(core.ROOT / "event_portal.py"), default_timeout=90).run()
    _ok(at)
    _login(at)
    for section in ("Start", "Papers", "Knowledge Graph", "Submit"):
        _go(at, section)
    page = " ".join(str(m.value) for m in at.markdown)
    assert "FLAG{TRIE}" not in page and "TRIE" not in " ".join(str(m.value) for m in at.metric)

    # Level 0 warm-up through the UI
    _go(at, "Submit")
    next(t for t in at.text_input if t.label == "Flag answer").input("prefix tree")
    next(b for b in at.button if "flag" in b.label.lower()).click()
    at.run()
    _ok(at)
    lock = next(b for b in at.button if b.label.startswith("Lock & Submit"))
    assert lock.disabled  # no graph yet
    core.save_draft("TEAM01", 0, HDR + "L0A,L0B,SHARES_PRINCIPLE,both store shared beginnings once\n")
    at.run()
    next(t for t in at.text_area if t.label == "Evidence & Reasoning").input("shared prefixes stored once")
    next(b for b in at.button if b.label.startswith("Lock & Submit")).click()
    at.run()
    _ok(at)
    assert core.team_progress("TEAM01")[1] == 1

    # Level 1 (fresh session - AppTest keeps stale widget state across a level change):
    # lock is disabled until a flag is entered; graph scored on the server
    core.save_draft("TEAM01", 1, L1)
    at = AppTest.from_file(str(core.ROOT / "event_portal.py"), default_timeout=90).run()
    _login(at)
    _go(at, "Submit")
    assert next(b for b in at.button if b.label.startswith("Lock & Submit")).disabled
    next(t for t in at.text_input if t.label == "Flag answer").input("the receivers")
    next(b for b in at.button if "flag" in b.label.lower()).click()
    at.run()
    _ok(at)
    next(t for t in at.text_area if t.label == "Evidence & Reasoning").input("P02 and P13 cite P05 (reference lists)")
    next(b for b in at.button if b.label.startswith("Lock & Submit")).click()
    at.run()
    _ok(at)
    rec = core.load()["submissions"]["TEAM01:1"]
    assert rec["graph_score"]["points"] == core.GRAPH_POINTS_PER_LEVEL


def test_portal_hint_ladder_and_final_discovery_form(env, monkeypatch):
    core.attempt_flag("TEAM01", 0, "trie")
    core.finalise("TEAM01", 0, "", explanation="warm-up")
    core.release_hint_for_all(1, 1)
    at = AppTest.from_file(str(core.ROOT / "event_portal.py"), default_timeout=90).run()
    _login(at)
    _go(at, "Papers")
    reveal = [b for b in at.button if b.label.startswith("Reveal Hint")]
    assert len(reveal) == 1 and "Hint 1" in reveal[0].label
    reveal[0].click()
    at.run()
    _ok(at)
    assert core.hint_status("TEAM01", 1)[0]["revealed"]

    # jump to level 4 and check standard flag box is shown
    core.attempt_flag("TEAM01", 1, "receivers")
    core.finalise("TEAM01", 1, L1, explanation="x")
    core.attempt_flag("TEAM01", 2, "phylogenetics")
    core.finalise("TEAM01", 2, L1, explanation="x")
    core.attempt_flag("TEAM01", 3, "P08")
    core.finalise("TEAM01", 3, L1, explanation="x")
    at.run()
    _go(at, "Submit")
    assert any(t.label == "Flag answer" for t in at.text_input)
    assert any("Confirm Final Submission" in b.label or "Lock & Submit" in b.label for b in at.button)


def test_admin_requires_strong_uncompromised_password(env, monkeypatch):
    monkeypatch.setenv("ORGANISER_PASSWORD", "IEEE_Etal2026")
    at = AppTest.from_file(str(core.ROOT / "event_admin.py"), default_timeout=90).run()
    at.text_input[0].input("wrong-password-attempt")
    at.button[0].click()
    at.run()
    assert len(at.tabs) == 0
    at.text_input[0].input("IEEE_Etal2026")
    at.button[0].click()
    at.run()
    _ok(at)
    assert len(at.tabs) == 5
    assert "DemoPass123" in " ".join(str(c.value) for c in at.caption)
