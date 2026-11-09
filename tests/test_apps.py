"""Headless end-to-end checks of both Streamlit apps (streamlit.testing.v1.AppTest)."""
import json

import pandas as pd
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from challenge import paths, submission  # noqa: E402
from challenge.submission import ParticipantBackend  # noqa: E402
from challenge.submission_store import SubmissionStore  # noqa: E402
from scoring.flag_validator import build_flag_registry  # noqa: E402

SECRET = "apptest-secret-0123456789abcdef"
PASSWORD = "organiser-test-pw"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("UL_SUBMISSIONS_DIR", str(tmp_path))
    monkeypatch.setenv("FLAG_HMAC_SECRET", SECRET)
    monkeypatch.setenv("ORGANISER_PASSWORD", PASSWORD)
    monkeypatch.setenv("FINAL_DEADLINE", "2030-01-01T00:00:00+00:00")
    reg = build_flag_registry(paths.read_json(paths.FINAL_ANSWER), SECRET)
    monkeypatch.setattr(submission, "_registry", lambda: reg)
    store = SubmissionStore(tmp_path)
    team = store.create_team("Team Alpha", ["Ada", "Alan"])
    store.release_hint(1)
    return store, team


def _no_exceptions(at):
    assert not at.exception, [str(e.value)[:500] for e in at.exception]


def test_participant_app_full_flow(env):
    store, team = env
    at = AppTest.from_file(str(paths.ROOT / "app.py"), default_timeout=90).run()
    _no_exceptions(at)
    assert at.title[0].value == "Proof of Thought"
    assert len(at.tabs) == 7
    page_text = json.dumps([m.value for m in at.markdown])
    assert "Hint 1" in page_text and "Hint 2" not in page_text  # only released hints are shown
    for forbidden in ("DECOY", "TARGET paper", "canonical", "Nextstrain"):
        assert forbidden not in page_text

    at.sidebar.text_input[0].input(team["code"])
    at.sidebar.button[0].click()
    at.run()
    _no_exceptions(at)
    assert "Team Alpha" in at.sidebar.success[0].value

    edges = pd.read_csv(paths.SAMPLES_DIR / "sample_submission_revised.csv", dtype=str)
    at.session_state["edges"] = edges
    at.run()
    next(b for b in at.button if (b.label or "").startswith("Submit current graph")).click()
    at.run()
    _no_exceptions(at)
    metrics = {m.label: m.value for m in at.metric}
    assert set(metrics) == {"Weighted F1", "Weighted precision", "Recall"}
    assert 0 < float(metrics["Weighted F1"]) <= 1
    assert len(store.graph_submissions(team["team_id"])) == 1

    # final one-shot submission through the form
    form_text = [t for t in at.text_area]
    form_text[0].input("Both rebuild a hidden tree whose internal nodes are never observed, using only measurements at the leaves.")
    form_text[1].input("P12 p.5 network inference is similar to phylogenetic inference; P08 p.5")
    form_text[2].input("https://docs.nextstrain.org/projects/augur/en/stable/usage/cli/ancestral.html")
    form_text[3].input("No historical lineage; different algorithms (ML vs pair-joining).")
    for ti in at.text_input:
        if ti.label.startswith("Real-world"):
            ti.input("Nextstrain")
    sel = [s for s in at.selectbox if s.label.startswith("Hidden connected paper")][0]
    sel.select(paths.read_json(paths.FINAL_ANSWER)["target_participant_id"])
    at.checkbox[0].check()
    next(b for b in at.button if (b.label or "") == "Submit final answer").click()
    at.run()
    _no_exceptions(at)
    assert store.has_final(team["team_id"])
    rec = store.final_submissions()[team["team_id"]]
    assert rec["evaluation"]["result"] == "CORRECT"
    shown = json.dumps([s.value for s in at.success])
    assert "locked" in shown and "CORRECT" not in shown  # no correctness feedback before deadline

    # a second attempt is refused
    be = ParticipantBackend(store)
    res = be.submit_final(team["team_id"], {"base_id": "P05", "target_id": "P01", "principle": "x" * 50, "application": "y",
                                            "paper_evidence": "P01", "application_evidence": "https://x", "limitations": "z"})
    assert not res["accepted"] and "locked" in res["errors"][0]


def test_backend_returns_aggregate_only(env):
    store, team = env
    be = ParticipantBackend(store)
    text = (paths.SAMPLES_DIR / "sample_submission_initial.csv").read_text(encoding="utf-8")
    res = be.submit_graph(team["team_id"], text)
    assert res["accepted"] and set(res["score"]) == {"split", "weighted_f1", "weighted_precision", "recall", "edges_scored"}
    assert be.submit_graph(team["team_id"], "source_id,target_id,relationship_type\n")["accepted"] is False
    assert len(be.history(team["team_id"])) == 1
    # rate limit: an immediate resubmission is refused and does not count
    again = be.submit_graph(team["team_id"], text)
    assert not again["accepted"] and "wait" in again["errors"][0]


def test_organiser_app_requires_password_and_runs(env):
    at = AppTest.from_file(str(paths.ROOT / "organiser_app.py"), default_timeout=180).run()
    _no_exceptions(at)
    assert len(at.tabs) == 0, "nothing but the password prompt before unlocking"
    at.text_input[0].input("wrong")
    at.button[0].click()
    at.run()
    assert len(at.tabs) == 0 and at.error
    at.text_input[0].input(PASSWORD)
    at.button[0].click()
    at.run()
    _no_exceptions(at)
    assert len(at.tabs) == 13
    for label in ("Run Stages 1-4", "Run extraction check on all cards", "Run naive vs guarded extraction"):
        next(b for b in at.button if b.label == label).click()
        at.run()
        _no_exceptions(at)
