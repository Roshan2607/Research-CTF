"""Glue between the level-lock path and the judging queue.

``queue_novel_edges`` is called after a level is locked. It never raises and never blocks on the judge:
any failure is logged and swallowed, so judging can never prevent a team from locking a level.

Judging is OFF unless ``JUDGING_ENABLED=1``. ``JUDGE_PROVIDER`` (``chatgpt`` | ``openai`` | ``anthropic``) selects the
worker's judge; with no provider the queue still fills and can be drained later (post-event pass).
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from challenge import paths

from .store import JudgeStore

log = logging.getLogger(__name__)

MAX_NOVEL_PER_LEVEL = 10  # per team and level; keeps volume (and cost) bounded and discourages spraying edges
_NOVEL_CLASSES = ("ordinary", "neutral")  # known-bad decoy / injection edges are not worth judging

DEFAULT_WORKERS = 28  # measured: 28 workers x batch 5 -> all 35 teams verdict-complete in <=17.5s (see load tests)
DEFAULT_BATCH = 5

_store: JudgeStore | None = None
_workers: list = []
_lock = threading.Lock()


def enabled() -> bool:
    return os.environ.get("JUDGING_ENABLED", "").strip() == "1"


def db_path() -> Path:
    return Path(os.environ.get("JUDGING_DB") or (paths.SUBMISSIONS_DIR / "judging.sqlite3"))


def get_store() -> JudgeStore:
    global _store
    with _lock:
        if _store is None or _store.path != str(db_path()):
            _store = JudgeStore(db_path())
        return _store


def reset() -> None:
    """Tests: drop cached store/worker."""
    global _store
    with _lock:
        for w in _workers:
            w.stop()
        _workers.clear()
        if _store is not None:
            _store.close()
        _store = None


def novel_edges(rows: list[dict], released: set[str], scorer) -> list[tuple[str, str, str, str]]:
    """Submitted edges the reference does not contain: candidates for the creativity judge."""
    from graph.schema import edge_key

    seen, out = set(), []
    for r in rows:
        s, t, rel = r["source_id"], r["target_id"], r["relationship_type"]
        if s not in released or t not in released:
            continue
        key = edge_key(s, t, rel)
        if key in seen:
            continue
        seen.add(key)
        if scorer.classify(key) in _NOVEL_CLASSES:
            out.append((s, t, rel, r.get("evidence_reference", "")))
    return out[:MAX_NOVEL_PER_LEVEL]


def queue_novel_edges(team_id: str, level: int, csv_text: str, cluster: str, released: list[str]) -> int | None:
    """Queue this submission's novel edges. Returns the submission id, or None if disabled / failed."""
    if not enabled() or level < 1:
        return None
    try:
        import event_core as core
        from challenge.graph_store import parse_and_validate_csv

        if cluster != core.CLUSTER:
            return None
        rows, errs = parse_and_validate_csv(csv_text, allowed_papers=released, allow_empty=True)
        if errs or not rows:
            return None
        edges = novel_edges(rows, set(released), core._main_scorer())
        if not edges:
            return None
        sid, _ = get_store().enqueue(team_id, level, csv_text, edges)
        ensure_worker()
        return sid
    except Exception:  # noqa: BLE001 - judging must never block a level lock
        log.exception("could not queue novel edges for %s level %s", team_id, level)
        return None


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, "") or default))
    except ValueError:
        return default


def ensure_worker() -> None:
    """Start the background worker pool once, if a provider is configured.

    One worker thread handles one judge call at a time (~5-11 s), so a burst needs many in parallel:
    ``JUDGE_WORKERS`` (default 24) workers claiming batches of ``JUDGE_BATCH`` (default 5) edges.
    """
    provider = os.environ.get("JUDGE_PROVIDER", "").strip().lower()
    if not provider:
        return
    with _lock:
        if _workers:
            return
        from .worker import JudgeWorker

        if provider == "chatgpt":
            from .chatgpt_judge import ChatGPTJudge as J
        elif provider == "openai":
            from .openai_judge import OpenAIJudge as J
        elif provider in ("grok", "xai"):
            from .openai_judge import GrokJudge as J
        elif provider == "anthropic":
            from .llm_judge import AnthropicJudge as J
        else:
            log.error("unknown JUDGE_PROVIDER %r; judging workers not started", provider)
            return
        try:
            store = _store or JudgeStore(db_path())
            judge = J()  # one judge shared by all workers (thread-safe: a fresh client per call)
            pool = [JudgeWorker(store, judge, batch_size=_int_env("JUDGE_BATCH", DEFAULT_BATCH))
                    for _ in range(_int_env("JUDGE_WORKERS", DEFAULT_WORKERS))]
        except Exception:  # noqa: BLE001 - e.g. SDK missing or not signed in
            log.exception("could not start judge workers; edges stay pending")
            return
        for w in pool:
            w.start()
        _workers.extend(pool)


def status_for_team(team_id: str, level: int) -> list[dict]:
    """Verdicts for a team's most recent submission at a level, [] if none or disabled."""
    if not enabled():
        return []
    try:
        store = get_store()
        row = store._conn().execute(
            "SELECT id FROM submissions WHERE team_id=? AND level=? ORDER BY id DESC LIMIT 1",
            (team_id.strip().upper(), int(level)),
        ).fetchone()
        return store.submission_status(row["id"]) if row else []
    except Exception:  # noqa: BLE001
        log.exception("could not read judging status")
        return []
