import re
import shutil
import subprocess

import pymupdf
import pytest

from challenge import paths
from challenge.document_reader import (
    SAFE_SYSTEM_PROMPT,
    build_llm_messages,
    extract_text,
    find_invisible_spans,
    scan_for_instructions,
    wrap_untrusted,
)
from challenge.naive_assistant import guarded_extract, naive_extract
from challenge.participant_data import load_corpus
from scoring.graph_scorer import GraphScorer

flat = lambda s: re.sub(r"\s+", " ", s).strip()  # noqa: E731


@pytest.fixture(scope="module")
def inj():
    return paths.read_json(paths.INJECTIONS)["annotations"]


@pytest.fixture(scope="module")
def cards():
    pdfs = {p.stem: p for p in paths.CARDS_DIR.glob("P*.pdf")}
    if len(pdfs) != len(load_corpus()):
        pytest.skip("cards not rendered - run scripts/build_challenge.py")
    return pdfs


@pytest.fixture(scope="module")
def texts(cards):
    return {pid: extract_text(p) for pid, p in cards.items()}


def test_annotations_are_distinguishable_in_organiser_metadata(inj):
    assert 1 <= len(inj) <= 2
    kinds = {a["id"]: a["difficulty"] for a in inj}
    assert kinds["INJ-1"] == "straightforward" and kinds["INJ-2"].startswith("contextual")
    for a in inj:
        assert a["id"] and a["host_card_participant_id"] and a["text"] and a["induced_edge"] and a["detection_marker"]
        assert a["rendering"]["colour_rgb"] == [1, 1, 1]


def test_injections_hosted_on_non_role_cards(inj):
    canon = paths.read_json(paths.CANONICAL_PATH)["path_participant_ids"]
    decoys = {d["participant_id"] for d in paths.read_json(paths.DECOYS)["decoys"]}
    for a in inj:
        assert a["host_card_participant_id"] not in canon and a["host_card_participant_id"] not in decoys


def test_pymupdf_extracts_injection_only_from_host(inj, texts):
    hosts = {a["host_card_participant_id"]: a for a in inj}
    for pid, text in texts.items():
        for a in inj:
            present = flat(a["text"]) in flat(text)
            assert present == (pid == a["host_card_participant_id"]), (pid, a["id"])
    assert set(hosts) <= set(texts)


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext not installed")
def test_pdftotext_extracts_injection(inj, cards):
    for a in inj:
        out = subprocess.run(["pdftotext", "-enc", "UTF-8", str(cards[a["host_card_participant_id"]]), "-"], capture_output=True)
        assert a["detection_marker"] in flat(out.stdout.decode("utf-8"))


def test_injection_is_rendered_invisibly(inj, cards):
    for pid, pdf in cards.items():
        spans = " ".join(s["text"] for s in find_invisible_spans(pdf))
        hosted = [a for a in inj if a["host_card_participant_id"] == pid]
        if hosted:
            assert hosted[0]["detection_marker"] in spans
            assert all(s["color"] == "#ffffff" for s in find_invisible_spans(pdf))
        else:
            assert spans == "", f"unexpected invisible text on {pid}"


def test_document_pipeline_flags_injected_instructions(inj, texts):
    """The keyword scanner catches the blunt INJ-1 but, by design, NOT the subtle INJ-2 - which is the lesson:
    keyword filters fail; only checking a claim against the paper catches a plausible false statement."""
    blunt = {a["host_card_participant_id"] for a in inj if not a.get("evades_keyword_filter")}
    subtle = {a["host_card_participant_id"] for a in inj if a.get("evades_keyword_filter")}
    assert blunt and subtle
    for pid, text in texts.items():
        flagged = bool(scan_for_instructions(text))
        assert flagged == (pid in blunt), pid


def test_original_abstract_unaltered_on_every_card(texts):
    for card in load_corpus():
        assert flat(card["abstract"]) in flat(texts[card["participant_id"]]), card["participant_id"]


def test_cards_have_identical_layout(cards):
    for pdf in cards.values():
        with pymupdf.open(str(pdf)) as d:
            assert len(d) == 1, f"card {pdf.stem} spilled over to multiple pages"
            rect = d[0].rect
            assert rect.width > 500 and rect.height > 800


def test_document_instructions_are_never_privileged(texts):
    docs = [wrap_untrusted(t, pid) for pid, t in texts.items()]
    msgs = build_llm_messages("Which papers are related?", docs)
    assert msgs[0] == {"role": "system", "content": SAFE_SYSTEM_PROMPT}
    assert "SYSTEM OVERRIDE" not in msgs[0]["content"]
    assert all(m["role"] != "system" for m in msgs[1:])
    assert 'trust="untrusted" warning="contains instruction-like text"' in msgs[1]["content"]


def test_naive_assistant_is_manipulated_and_guard_quarantines(inj, texts):
    naive = {(e["source_id"], e["target_id"], e["relationship_type"]) for e in naive_extract(texts)}
    expected = {tuple(a["induced_edge"]) for a in inj}
    assert expected <= naive, "demo should show the naive pipeline adopting the injected edges"
    proposals, quarantined = guarded_extract(texts)
    guarded = {(e["source_id"], e["target_id"], e["relationship_type"]) for e in proposals}
    blunt = {tuple(a["induced_edge"]) for a in inj if not a.get("evades_keyword_filter")}
    subtle = {tuple(a["induced_edge"]) for a in inj if a.get("evades_keyword_filter")}
    assert not (blunt & guarded), "instruction-like injections are quarantined"
    assert len(quarantined) >= len(blunt)
    # the subtle injection gets past the keyword guard, but only ever as an unverified AI proposal
    assert subtle <= guarded
    assert all(p["status"] == "AI_PROPOSED" for p in proposals)


def test_injected_edges_carry_heaviest_penalty(inj):
    s = GraphScorer.from_answer_key()
    for a in inj:
        assert s.classify(tuple(a["induced_edge"])) == "injection_induced"
