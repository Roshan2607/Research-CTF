"""Judging queue: dedupe/cache, atomic claims, timeouts, crash recovery, 35-team burst."""
import threading
import time

import pytest

from judging import JudgeStore, JudgeWorker, StubJudge, Verdict
from judging.store import DEFERRED, PENDING, VERDICTS


@pytest.fixture
def store(tmp_path):
    s = JudgeStore(tmp_path / "judging.sqlite3")
    yield s
    s.close()


def edges(n, evidence="quote"):
    return [(f"P{i:02d}", f"P{i + 1:02d}", "SHARES_PRINCIPLE", evidence) for i in range(1, n + 1)]


def test_enqueue_returns_immediately_and_marks_pending(store):
    sid, hashes = store.enqueue("t1", 1, "csv", edges(3))
    assert len(hashes) == 3 and store.counts() == {PENDING: 3}
    assert {r["status"] for r in store.submission_status(sid)} == {PENDING}


def test_identical_edges_across_teams_are_judged_once(store):
    store.enqueue("t1", 1, "csv", edges(4))
    store.enqueue("t2", 1, "csv", edges(4))
    assert store.counts() == {PENDING: 4}
    judge = StubJudge()
    JudgeWorker(store, judge).drain()
    assert judge.calls == 1  # 4 unique edges, one batch
    # a later duplicate is already cached: nothing new is queued
    sid, _ = store.enqueue("t3", 2, "csv", edges(4))
    assert PENDING not in store.counts()
    assert all(r["status"] in VERDICTS for r in store.submission_status(sid))


def test_symmetric_edge_hashes_same_either_way_round(store):
    _, h1 = store.enqueue("t1", 1, "c", [("P02", "P11", "SHARES_PRINCIPLE", "q")])
    _, h2 = store.enqueue("t2", 1, "c", [("p11", "p02", "shares_principle", "  Q ")])
    assert h1 == h2 and store.counts() == {PENDING: 1}


def test_directed_edges_keep_direction(store):
    _, h1 = store.enqueue("t1", 1, "c", [("P02", "P11", "CITES", "q")])
    _, h2 = store.enqueue("t2", 1, "c", [("P11", "P02", "CITES", "q")])
    assert h1 != h2


def test_claim_is_atomic_across_threads(store):
    store.enqueue("t1", 1, "c", edges(40))
    claimed, lock = [], threading.Lock()

    def grab():
        while True:
            b = store.claim_batch(5)
            if not b:
                return
            with lock:
                claimed.extend(e.edge_hash for e in b)

    ts = [threading.Thread(target=grab) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(claimed) == 40 and len(set(claimed)) == 40


def test_expired_lease_is_reclaimed_after_a_crash(store):
    store.enqueue("t1", 1, "c", edges(2))
    assert len(store.claim_batch(10)) == 2
    assert store.claim_batch(10, lease_seconds=60) == []  # still leased
    time.sleep(0.05)
    assert len(store.claim_batch(10, lease_seconds=0.01)) == 2  # "worker died": lease expired


def test_judge_exception_retries_then_succeeds(store):
    store.enqueue("t1", 1, "c", edges(3))
    w = JudgeWorker(store, StubJudge(fail_first=1), max_attempts=3)
    first = w.run_once()
    assert first.errored and first.released == 3 and store.counts() == {PENDING: 3}
    w.drain()
    assert set(store.counts()) <= set(VERDICTS)


def test_persistent_failure_defers_instead_of_blocking(store):
    store.enqueue("t1", 1, "c", edges(2))
    w = JudgeWorker(store, StubJudge(fail_first=99), max_attempts=2)
    w.drain()
    assert store.counts() == {DEFERRED: 2}
    assert store.requeue_deferred() == 2 and store.counts() == {PENDING: 2}


def test_timeout_does_not_block_and_releases_edges(store):
    store.enqueue("t1", 1, "c", edges(2))
    w = JudgeWorker(store, StubJudge(delay=0.6), call_timeout=0.1, max_attempts=1)
    t0 = time.time()
    s = w.run_once()
    assert s.timed_out and time.time() - t0 < 0.4
    assert store.counts() == {DEFERRED: 2}


class PartialJudge:
    model = "partial"

    def judge_batch(self, batch):
        return {batch[0].edge_hash: Verdict("supported", "ok"), batch[1].edge_hash: Verdict("nonsense", "x")}


def test_missing_and_invalid_verdicts_are_handled(store):
    store.enqueue("t1", 1, "c", edges(3))
    w = JudgeWorker(store, PartialJudge(), max_attempts=1)
    w.run_once()
    counts = store.counts()
    assert counts.get("supported") == 1 and counts.get("abstain") == 1 and counts.get(DEFERRED) == 1


def test_audit_trail_records_model_and_reason(store):
    _, hashes = store.enqueue("t1", 1, "c", edges(1))
    JudgeWorker(store, StubJudge()).drain()
    j = store.judgments_for(hashes[0])
    assert len(j) == 1 and j[0]["model"] == "stub" and j[0]["reason"]


def test_burst_of_35_teams_submits_concurrently_and_all_get_judged(store):
    """35 teams submit at once with overlapping edges; submit never waits for the judge."""
    shared = edges(6)
    start = threading.Barrier(35)
    submit_times = []

    def team(i):
        start.wait()
        t0 = time.time()
        store.enqueue(f"T{i:02d}", 1, "csv", shared + [(f"P{i % 14 + 1:02d}", "P15", "CITES", f"own {i}")])
        submit_times.append(time.time() - t0)

    ts = [threading.Thread(target=team, args=(i,)) for i in range(35)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert max(submit_times) < 2.0
    unique = sum(store.counts().values())
    judge = StubJudge(delay=0.02)
    w = JudgeWorker(store, judge, batch_size=10)
    w.drain()
    assert PENDING not in store.counts() and "in_progress" not in store.counts()
    assert sum(store.counts().values()) == unique
    assert judge.calls == -(-unique // 10)  # one call per batch of 10 unique edges, not per team/edge


def test_background_thread_processes_queue(store):
    w = JudgeWorker(store, StubJudge(), poll_interval=0.05)
    w.start()
    try:
        store.enqueue("t1", 1, "c", edges(5))
        deadline = time.time() + 5
        while PENDING in store.counts() and time.time() < deadline:
            time.sleep(0.05)
        assert PENDING not in store.counts()
    finally:
        w.stop()


class AuthFailJudge:
    model = "auth-fail"

    def judge_batch(self, batch):
        err = RuntimeError("Incorrect API key provided")
        err.status_code = 401
        raise err


def test_bad_key_stops_the_worker_and_leaves_edges_pending(store):
    store.enqueue("t1", 1, "c", edges(25))
    w = JudgeWorker(store, AuthFailJudge(), batch_size=10, max_attempts=2)
    s = w.drain()
    assert s.fatal and "Incorrect API key" in w.fatal
    assert store.counts() == {PENDING: 25}  # nothing deferred or burned; a fixed key can resume
