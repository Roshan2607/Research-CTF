import datetime as dt
import json

import pytest

from challenge import paths
from challenge.submission_store import SubmissionStore
from scoring.flag_validator import (
    FinalSubmissionService,
    SecretMissing,
    build_flag_registry,
    evaluate,
    get_secret,
    normalise_application,
    normalise_pid,
    token,
)

SECRET = "test-secret-0123456789abcdef"
UTC = dt.timezone.utc


@pytest.fixture(scope="module")
def answer():
    return paths.read_json(paths.FINAL_ANSWER)


@pytest.fixture()
def registry(answer):
    return build_flag_registry(answer, SECRET)


@pytest.fixture()
def service(tmp_path, registry):
    store = SubmissionStore(tmp_path)
    return FinalSubmissionService(store, registry, deadline="2030-01-01T00:00:00+00:00", secret=SECRET)


def good(answer, **over):
    sub = {
        "base_id": answer["base_participant_id"],
        "target_id": answer["target_participant_id"],
        "principle": "Both reconstruct a hidden tree with unobserved internal nodes from measurements made only at the leaves, "
        "using a distance / shared-path similarity between pairs of leaves.",
        "application": "Nextstrain",
        "paper_evidence": "P12 p.5 states the network inference problem is similar to phylogenetic inference; P08 p.5.",
        "application_evidence": "https://docs.nextstrain.org/projects/augur/en/stable/usage/cli/ancestral.html",
        "limitations": "No historical lineage; Nextstrain uses maximum likelihood, not the same algorithm.",
    }
    sub.update(over)
    return sub


def test_normalisation_is_consistent():
    variants = ["Nextstrain", " nextstrain ", "NEXTSTRAIN", "Next-strain", "The Nextstrain", "Nextstraín"]
    assert len({normalise_application(v) for v in variants}) == 1
    assert normalise_application("https://www.nextstrain.org/") == "nextstrainorg"
    assert normalise_pid("p3") == normalise_pid(" P03 ") == normalise_pid("P3") == "P03"


def test_correct_answer_accepted(answer, registry):
    ev = evaluate(good(answer), registry, SECRET)
    assert ev["result"] == "CORRECT" and ev["application_status"] == "CANONICAL"
    for alias in ("nextstrain.org", "Nextstrain (Augur/Auspice)", "NextStrain Augur"):
        assert evaluate(good(answer, application=alias), registry, SECRET)["application_status"] == "CANONICAL"


def test_incorrect_answers_rejected(answer, registry):
    assert evaluate(good(answer, target_id="P10"), registry, SECRET)["result"] == "INCORRECT"
    assert evaluate(good(answer, base_id="P01"), registry, SECRET)["result"] == "INCORRECT"


def test_alternative_application_goes_to_manual_review(answer, registry):
    ev = evaluate(good(answer, application="Some other phylogenetics platform"), registry, SECRET)
    assert ev["result"] == "MANUAL_REVIEW" and ev["application_status"] == "MANUAL_REVIEW"


def test_accepted_alternative_after_review(answer):
    reviewed = dict(answer, accepted_alternative_applications=["Example Tree Platform"])
    reg = build_flag_registry(reviewed, SECRET)
    assert evaluate(good(answer, application="example tree platform"), reg, SECRET)["result"] == "CORRECT"


def test_product_name_alone_is_not_enough(service, answer):
    r = service.submit("T01", good(answer, principle="Nextstrain"))
    assert not r["accepted"] and any("principle" in e for e in r["errors"])
    r = service.submit("T01", good(answer, application_evidence="trust me"))
    assert not r["accepted"]
    assert not service.store.has_final("T01"), "a rejected form must not consume the one shot"


def test_one_shot_and_no_early_feedback(service, answer):
    r = service.submit("T01", good(answer))
    assert r["accepted"] and r["locked"]
    assert "CORRECT" not in json.dumps(r) and "flag" not in r
    with pytest.raises(PermissionError):
        service.submit("T01", good(answer, application="Something else"))
    st = service.participant_status("T01", at=dt.datetime(2029, 1, 1, tzinfo=UTC))
    assert st["result"] == "hidden until the deadline"
    st = service.participant_status("T01", at=dt.datetime(2030, 6, 1, tzinfo=UTC))
    assert st["result"] == "CORRECT" and st["flag"].startswith("UL{")


def test_deadline_blocks_submission(tmp_path, registry, answer):
    svc = FinalSubmissionService(SubmissionStore(tmp_path), registry, deadline="2020-01-01T00:00:00+00:00", secret=SECRET)
    with pytest.raises(PermissionError):
        svc.submit("T02", good(answer))


def test_flags_are_team_bound(service, answer, tmp_path):
    service.submit("T01", good(answer))
    service.submit("T02", good(answer))
    f = service.store.final_submissions()
    assert f["T01"]["flag"] != f["T02"]["flag"]


def test_registry_contains_no_plaintext_answers(registry, answer):
    blob = json.dumps(registry).lower()
    assert "nextstrain" not in blob
    assert answer["target_participant_id"].lower() not in blob
    assert SECRET not in json.dumps(registry)


def test_tokens_depend_on_secret(answer):
    assert build_flag_registry(answer, SECRET)["target_token"] != build_flag_registry(answer, SECRET + "x")["target_token"]
    assert token(SECRET, "paper", "P03") != token(SECRET, "application", "P03")


def test_wrong_secret_detected(tmp_path, registry, answer):
    svc = FinalSubmissionService(SubmissionStore(tmp_path), registry, deadline=None, secret="another-secret-value-123")
    with pytest.raises(SecretMissing):
        svc.submit("T03", good(answer))


def test_missing_secret_detected(monkeypatch):
    monkeypatch.delenv("FLAG_HMAC_SECRET", raising=False)
    with pytest.raises(SecretMissing):
        get_secret()
    monkeypatch.setenv("FLAG_HMAC_SECRET", "change-me")
    with pytest.raises(SecretMissing):
        get_secret()


def test_secret_never_exposed_to_client_files():
    # no participant-facing file or module may contain the secret variable's value or read the env var
    for p in list(paths.PARTICIPANT_DIR.rglob("*.json")):
        assert "FLAG_HMAC_SECRET" not in p.read_text(encoding="utf-8")
    view = paths.ROOT / "challenge" / "participant_view.py"
    if view.exists():
        assert "FLAG_HMAC_SECRET" not in view.read_text(encoding="utf-8")
        assert "os.environ" not in view.read_text(encoding="utf-8")
