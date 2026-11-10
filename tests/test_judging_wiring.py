"""Level-lock wiring: novel-edge selection, opt-in queueing, and 'judging can never block a lock'."""
import pytest

import event_core as core
from judging import service


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("JUDGING_DB", str(tmp_path / "judging.sqlite3"))
    monkeypatch.delenv("JUDGE_PROVIDER", raising=False)  # never start a real worker in tests
    monkeypatch.setattr(core, "STATE", tmp_path / "event_state.json")
    service.reset()
    yield
    service.reset()


def _by_class(scorer, cls, released, n=1):
    out = [t for t, c in scorer.classes.items() if c == cls and t[0] in released and t[1] in released]
    assert len(out) >= n, f"need {n} {cls} edges in scope"
    return sorted(out)[:n]


def _csv(edges, ev="evidence text"):
    return "source_id,target_id,relationship_type,evidence_reference\n" + "".join(
        f"{s},{t},{r},{ev}\n" for s, t, r in edges)


def test_only_ordinary_and_neutral_edges_are_novel():
    released = set(core.released_papers(2, core.CLUSTER))
    sc = core._main_scorer()
    ordinary = _by_class(sc, "ordinary", released)[0]
    neutral = _by_class(sc, "neutral", released)[0]
    ref = _by_class(sc, "reference", released)[0]
    decoy = _by_class(sc, "decoy_induced", released)[0]
    rows = [{"source_id": s, "target_id": t, "relationship_type": r, "evidence_reference": "e"}
            for s, t, r in (ordinary, neutral, ref, decoy)]
    got = {(s, t, r) for s, t, r, _ in service.novel_edges(rows, released, sc)}
    assert got == {ordinary, neutral}


def test_novel_edges_are_capped_per_level():
    released = set(core.released_papers(4, core.CLUSTER))
    sc = core._main_scorer()
    many = _by_class(sc, "ordinary", released, n=service.MAX_NOVEL_PER_LEVEL + 5)
    rows = [{"source_id": s, "target_id": t, "relationship_type": r, "evidence_reference": "e"} for s, t, r in many]
    assert len(service.novel_edges(rows, released, sc)) == service.MAX_NOVEL_PER_LEVEL


def test_disabled_by_default_queues_nothing(monkeypatch):
    monkeypatch.delenv("JUDGING_ENABLED", raising=False)
    released = core.released_papers(2, core.CLUSTER)
    e = _by_class(core._main_scorer(), "ordinary", set(released))
    assert service.queue_novel_edges("T1", 2, _csv(e), core.CLUSTER, released) is None
    assert service.status_for_team("T1", 2) == []


def test_enabled_queues_novel_edges_as_pending(monkeypatch):
    monkeypatch.setenv("JUDGING_ENABLED", "1")
    released = core.released_papers(2, core.CLUSTER)
    sc = core._main_scorer()
    edges = _by_class(sc, "ordinary", set(released), n=2) + _by_class(sc, "reference", set(released))
    sid = service.queue_novel_edges("t1", 2, _csv(edges), core.CLUSTER, released)
    assert sid is not None
    status = service.status_for_team("T1", 2)
    assert len(status) == 2 and {r["status"] for r in status} == {"pending"}  # reference edge not queued


def test_demo_level_and_other_clusters_are_ignored(monkeypatch):
    monkeypatch.setenv("JUDGING_ENABLED", "1")
    released = core.released_papers(2, core.CLUSTER)
    e = _by_class(core._main_scorer(), "ordinary", set(released))
    assert service.queue_novel_edges("T1", 0, _csv(e), core.CLUSTER, released) is None
    assert service.queue_novel_edges("T1", 2, _csv(e), "Level 0 Demo", released) is None


def test_finalise_calls_the_hook_after_locking(monkeypatch):
    calls = []
    monkeypatch.setattr(core, "_finalise_locked", lambda *a, **k: {"team_id": "T1", "level": 2, "csv": "c"})
    monkeypatch.setattr(service, "queue_novel_edges", lambda *a: calls.append(a))
    rec = core.finalise("T1", 2, "c", explanation="x")
    assert rec["level"] == 2 and calls and calls[0][:3] == ("T1", 2, "c")


def test_a_failing_judging_hook_cannot_block_the_lock(monkeypatch):
    monkeypatch.setattr(core, "_finalise_locked", lambda *a, **k: {"team_id": "T1", "level": 2, "csv": "c"})

    def boom(*a):
        raise RuntimeError("judging exploded")

    monkeypatch.setattr(service, "queue_novel_edges", boom)
    assert core.finalise("T1", 2, "c", explanation="x")["team_id"] == "T1"


def test_ensure_worker_starts_a_pool_with_configured_size(monkeypatch):
    import judging.chatgpt_judge as cj
    from judging import StubJudge

    monkeypatch.setenv("JUDGE_PROVIDER", "chatgpt")
    monkeypatch.setenv("JUDGE_WORKERS", "7")
    monkeypatch.setenv("JUDGE_BATCH", "3")
    monkeypatch.setattr(cj, "ChatGPTJudge", lambda: StubJudge())
    service.get_store()
    service.ensure_worker()
    service.ensure_worker()  # idempotent
    assert len(service._workers) == 7 and {w.batch_size for w in service._workers} == {3}


def test_ensure_worker_defaults_and_bad_env_values(monkeypatch):
    import judging.chatgpt_judge as cj
    from judging import StubJudge

    monkeypatch.setenv("JUDGE_PROVIDER", "chatgpt")
    monkeypatch.setenv("JUDGE_WORKERS", "lots")
    monkeypatch.delenv("JUDGE_BATCH", raising=False)
    monkeypatch.setattr(cj, "ChatGPTJudge", lambda: StubJudge())
    service.get_store()
    service.ensure_worker()
    assert len(service._workers) == service.DEFAULT_WORKERS
    assert all(w.batch_size == service.DEFAULT_BATCH for w in service._workers)
