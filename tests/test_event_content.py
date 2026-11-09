"""Checks on the LIVE event content (data/event_content.csv) against the calibration design.

Engine behaviour is tested against a fixed fixture in test_event_workflow.py / test_section_a_backend.py;
this file guards the real challenge: verified papers only, role-aware release, scoreable levels,
uneven decoys, injections released alongside their targets, and questions that do not give answers away.
"""
import json

import pytest

import event_core as core
from challenge import paths

LIVE = core.ROOT / "data" / "event_content.csv"


@pytest.fixture(autouse=True)
def _live_content(monkeypatch):
    monkeypatch.setattr(core, "CONTENT", LIVE)
    monkeypatch.delenv("UL_EVENT_CONTENT", raising=False)


@pytest.fixture(scope="module")
def corpus():
    return {p["participant_id"]: p for p in json.loads(paths.PARTICIPANT_PAPERS.read_text(encoding="utf-8"))["papers"]}


def comp_levels():
    return [lv for lv in core.levels_for_cluster(core.CLUSTER) if lv["id"] >= 1]


def test_only_verified_content_is_configured(corpus):
    assert core.clusters() == [core.CLUSTER]
    demo = core.load_demo_level0()
    assert demo.get("synthetic") is True
    demo_ids = {p["id"] for p in demo["papers"]}
    for p in demo["papers"]:
        assert p["excerpt"].startswith("SYNTHETIC DEMO TEXT")
    for r in core._content():
        assert (core.ROOT / r["challenge_card_path"]).exists(), r["challenge_card_path"]
        if r["level"] == "0":
            assert r["paper_id"] in demo_ids and r["paper_title"].startswith("[Synthetic demo]")
        else:
            assert r["paper_id"] in corpus, f"{r['paper_id']} is not in the verified corpus"
            assert r["paper_title"] == corpus[r["paper_id"]]["title"]


def test_every_paper_released_exactly_once(corpus):
    released = [p for lv in comp_levels() for p in lv["paper_ids"]]
    assert sorted(released) == sorted(corpus), "each verified paper is released exactly once across L1-L4"
    assert [len(lv["paper_ids"]) for lv in comp_levels()] == [4, 5, 4, 2]


def test_release_is_role_aware_not_id_order():
    canon = paths.read_json(paths.CANONICAL_PATH)
    base, target = canon["base"]["participant_id"], canon["target"]["participant_id"]
    levels = comp_levels()
    assert base in levels[0]["paper_ids"], "teams must see their starting paper at Level 1"
    assert target in levels[-1]["paper_ids"] and len(levels[-1]["paper_ids"]) >= 2, "target arrives last, not alone"
    assert levels[0]["paper_ids"] != ["P01", "P02"]


def test_every_level_has_scoreable_reference_edges():
    ref = [(r["source_id"], r["target_id"]) for r in paths.read_json(paths.SCORING_REFERENCE)["rows"] if r["edge_class"] == "reference"]
    cumulative, seen = [], set()
    for lv in comp_levels():
        seen |= set(lv["paper_ids"])
        cumulative.append(sum(1 for s, t in ref if s in seen and t in seen))
    assert cumulative == [5, 16, 26, 41], cumulative


def test_decoys_spread_unevenly():
    decoys = {d["participant_id"] for d in paths.read_json(paths.DECOYS)["decoys"]}
    per_level = [len(decoys & set(lv["paper_ids"])) for lv in comp_levels()]
    assert sum(per_level) == len(decoys)
    assert len(set(per_level)) > 1, f"decoys must not follow a one-per-level pattern: {per_level}"


def test_injection_hosts_released_with_their_targets():
    levels = comp_levels()
    level_of = {p: lv["id"] for lv in levels for p in lv["paper_ids"]}
    for a in paths.read_json(paths.INJECTIONS)["annotations"]:
        host = level_of[a["host_card_participant_id"]]
        s, t, _ = a["induced_edge"]
        assert host >= max(level_of[s], level_of[t]), a["id"]
        assert host == a.get("released_at_level", host)


def test_questions_do_not_contain_their_answers_or_the_principle():
    giveaways = ("neighbor-joining", "neighbour joining", "leaf-only", "hidden tree", "tree reconstruction", "nextstrain")
    for lv in comp_levels():
        q = lv["question"].lower()
        for g in giveaways:
            assert g not in q, (lv["id"], g)
        padded_q = f" {core.normalise(q)} "
        for ans in lv["answers"]:
            if len(ans) > 3:
                assert f" {core.normalise(ans)} " not in padded_q, (lv["id"], ans)


def test_final_level_is_the_one_shot_discovery():
    rows = [r for r in core._content() if r["cluster"] == core.CLUSTER and r["level"] == "4"]
    assert rows and all(r.get("flag_mode") == "final_discovery" for r in rows)
    assert all(not r["flag_answers"].strip() for r in rows), "the final answer must not be stored in plain text in the content CSV"
    for lv in comp_levels()[:-1]:
        assert lv["answers"], f"level {lv['id']} needs accepted answers"
