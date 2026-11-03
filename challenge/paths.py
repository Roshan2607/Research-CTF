"""Central data locations, split into the three data layers.

1. Organiser master data  -> ORGANISER_DIR, ANSWER_KEY_DIR (never served to participants)
2. Participant data       -> PARTICIPANT_DIR (the only directory the participant app reads)
3. Submission data        -> SUBMISSIONS_DIR (runtime, git-ignored)
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CONFIG_PATH = ROOT / "config" / "challenge_config.json"

ORGANISER_DIR = DATA_DIR / "organiser"
ANSWER_KEY_DIR = DATA_DIR / "answer_key"
PARTICIPANT_DIR = DATA_DIR / "participant"
CARDS_DIR = PARTICIPANT_DIR / "cards"
SUBMISSIONS_DIR = DATA_DIR / "submissions"
SAMPLES_DIR = DATA_DIR / "samples"
KAGGLE_DIR = ROOT / "kaggle"

MASTER_GRAPH = ORGANISER_DIR / "master_graph.json"
HINTS = ORGANISER_DIR / "hints.json"
SOURCE_MANIFEST = DATA_DIR / "source_manifest.json"

CANONICAL_PATH = ANSWER_KEY_DIR / "canonical_path.json"
ALTERNATIVE_PATHS = ANSWER_KEY_DIR / "alternative_paths.json"
DECOYS = ANSWER_KEY_DIR / "decoys.json"
INJECTIONS = ANSWER_KEY_DIR / "injection_annotations.json"
FINAL_ANSWER = ANSWER_KEY_DIR / "final_answer.json"
SCORING_POLICY = ANSWER_KEY_DIR / "scoring_policy.json"
SCORING_REFERENCE = ANSWER_KEY_DIR / "scoring_reference.json"
FLAG_REGISTRY = ANSWER_KEY_DIR / "flag_registry.json"
KAGGLE_SOLUTION = ANSWER_KEY_DIR / "kaggle_solution.csv"

PARTICIPANT_PAPERS = PARTICIPANT_DIR / "participant_papers.json"
PARTICIPANT_VOCAB = PARTICIPANT_DIR / "relationship_vocabulary.json"
PARTICIPANT_CHALLENGE = PARTICIPANT_DIR / "challenge_info.json"

PROTECTED_DIRS = (ORGANISER_DIR, ANSWER_KEY_DIR)


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_config() -> dict:
    return read_json(CONFIG_PATH)
