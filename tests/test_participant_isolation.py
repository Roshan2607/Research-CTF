"""The participant layer must not reveal roles, the path, the target, decoys or injections."""
import ast
import json
import re
from pathlib import Path

import pytest

from challenge import participant_data, paths
from graph.schema import ORGANISER_ROLE_LABELS

ROOT = paths.ROOT


@pytest.fixture(scope="module")
def participant_blob():
    texts = []
    for p in paths.PARTICIPANT_DIR.glob("*.json"):
        texts.append(p.read_text(encoding="utf-8"))
    return "\n".join(texts)


@pytest.fixture(scope="module")
def answer():
    return paths.read_json(paths.FINAL_ANSWER)


def test_participant_files_exist():
    assert paths.PARTICIPANT_PAPERS.exists() and paths.PARTICIPANT_VOCAB.exists() and paths.PARTICIPANT_CHALLENGE.exists()


def test_no_organiser_role_labels(participant_blob):
    # Organiser labels are UPPER_CASE tokens; match them as whole words, case-sensitively,
    # so ordinary words ("transcriptional targets", the column "target_id") are not flagged.
    for label in ORGANISER_ROLE_LABELS + ("BASE",):
        assert not re.search(rf"\b{label}\b", participant_blob), label
    for word in ("decoy", "intermediate", "canonical", "injection", "answer key", "target paper"):
        assert word not in participant_blob.lower(), word


def test_no_internal_ids_or_concept_nodes(participant_blob):
    assert "PAPER_" not in participant_blob
    for prefix in ("PROB_", "METH_", "PRIN_", "DOM_", "APP_"):
        assert prefix not in participant_blob


def test_target_and_application_not_identified(participant_blob, answer):
    info = participant_data.load_challenge_info()
    assert answer["target_participant_id"] not in json.dumps(info)
    assert "nextstrain" not in participant_blob.lower()
    assert "leaf-only" not in participant_blob.lower()


def test_cards_are_uniform():
    cards = participant_data.load_corpus()
    keys = {tuple(sorted(c)) for c in cards}
    assert len(keys) == 1, "all paper cards must have exactly the same fields"
    assert set(cards[0]) - {"domain", "access", "citation", "abstract_attribution", "reading_prompts"} == set(
        participant_data.PARTICIPANT_PAPER_FIELDS
    )
    assert len({json.dumps(c["reading_prompts"]) for c in cards}) == 1


def test_no_organiser_annotations_leak():
    cards = participant_data.load_corpus()
    for c in cards:
        for forbidden in ("key_problem", "methods", "findings", "limitations", "evidence_refs", "access_note", "internal_id"):
            assert forbidden not in c


def test_abstracts_match_source_manifest():
    manifest = {p["doi"]: p["abstract"] for p in paths.read_json(paths.SOURCE_MANIFEST)["papers"]}
    for c in participant_data.load_corpus():
        assert c["abstract"] == manifest[c["doi"]], c["participant_id"]


def test_participant_ids_are_not_role_ordered(answer):
    ids = participant_data.valid_participant_ids()
    assert ids == sorted(ids)
    assert answer["base_participant_id"] != "P01" and answer["target_participant_id"] not in (ids[0], ids[-1])


def test_participant_loader_refuses_protected_paths():
    with pytest.raises(PermissionError):
        participant_data._participant_file(paths.FINAL_ANSWER)
    with pytest.raises(PermissionError):
        participant_data._participant_file(paths.MASTER_GRAPH)
    with pytest.raises(ValueError):
        participant_data.card_pdf_path("../answer_key/final_answer")


def test_answer_key_not_under_participant_dir():
    for p in paths.PARTICIPANT_DIR.rglob("*"):
        assert "answer_key" not in p.parts and "organiser" not in p.parts


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def test_participant_view_never_touches_answer_key_directly():
    view = ROOT / "challenge" / "participant_view.py"
    if not view.exists():
        pytest.skip("participant view not built yet")
    src = view.read_text(encoding="utf-8")
    for name in ("FINAL_ANSWER", "CANONICAL_PATH", "ALTERNATIVE_PATHS", "DECOYS", "INJECTIONS", "MASTER_GRAPH",
                 "SCORING_REFERENCE", "KAGGLE_SOLUTION", "organiser_view", "answer_key"):
        assert name not in src, f"participant view references {name}"
    imported = _imports(view)
    assert "challenge.organiser_view" not in imported and "graph.builder" not in imported


def test_participant_app_entrypoint_is_separate_from_organiser():
    app = ROOT / "app.py"
    if not app.exists():
        pytest.skip("app not built yet")
    imported = _imports(app)
    assert not any("organiser" in m for m in imported)


def test_vocabulary_examples_are_outside_corpus():
    vocab = participant_data.load_vocabulary()
    text = json.dumps(vocab["relationship_types"])
    assert not re.search(r"\bP\d\d\b", text)
