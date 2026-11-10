"""Queue worker: claims pending edges, calls the judge with a hard timeout, records verdicts.

The judge call runs on a helper thread so ``run_once`` can enforce ``call_timeout`` even if the
underlying client hangs. A timeout, an exception or a missing verdict only returns the edges to the
queue (and defers them after ``max_attempts``); nothing here can affect a team's gate or F1.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass

from .judge import Judge
from .store import JudgeStore

log = logging.getLogger(__name__)


@dataclass
class RunStats:
    claimed: int = 0
    judged: int = 0
    released: int = 0
    timed_out: bool = False
    errored: bool = False
    fatal: bool = False  # authentication/permission failure: retrying cannot help


def is_fatal(exc: BaseException) -> bool:
    """401/403-style errors (bad or revoked key). Works for the openai and anthropic SDK exceptions."""
    status = getattr(exc, "status_code", None)
    if status in (401, 403) or type(exc).__name__ in ("AuthenticationError", "PermissionDeniedError"):
        return True
    msg = str(exc).lower()  # an exhausted quota arrives as a 429, but retrying cannot fix it
    return any(k in msg for k in ("insufficient_quota", "no credits remaining",
                                   "subscription_sharing_usage_limit_exceeded", "subscription_sharing_usage_unavailable",
                                   "not signed in"))


class JudgeWorker:
    def __init__(self, store: JudgeStore, judge: Judge, batch_size: int = 10, call_timeout: float = 20.0,
                 max_attempts: int = 2, poll_interval: float = 0.5):
        self.store, self.judge = store, judge
        self.batch_size, self.call_timeout = batch_size, call_timeout
        self.max_attempts, self.poll_interval = max_attempts, poll_interval
        # Lease must outlive a call, so a slow-but-alive call is not reclaimed by another worker.
        self.lease = call_timeout * 3
        self.fatal: str | None = None
        self._last_logged: dict[str, float] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # More than one thread so a hung call (which cannot be cancelled once running) does not block the next.
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="judge-call")

    def run_once(self) -> RunStats:
        stats = RunStats()
        batch = self.store.claim_batch(self.batch_size, self.lease)
        stats.claimed = len(batch)
        if not batch:
            return stats
        future = self._pool.submit(self.judge.judge_batch, batch)
        try:
            verdicts = future.result(timeout=self.call_timeout)
        except FutureTimeout:
            future.cancel()
            stats.timed_out = True
            verdicts = {}
            log.warning("judge call timed out after %.1fs (%d edges)", self.call_timeout, len(batch))
        except Exception as exc:  # noqa: BLE001 - any judge failure just means "try again later"
            stats.errored = True
            verdicts = {}
            if is_fatal(exc):
                self.fatal = f"{type(exc).__name__}: {str(exc)[:200]}"
                stats.fatal = True
            self._log_failure(exc, len(batch))
        unjudged = []
        attempts_allowed = 10**9 if stats.fatal else self.max_attempts  # a bad key must not burn edge attempts
        for e in batch:
            v = verdicts.get(e.edge_hash)
            if v is None:
                unjudged.append(e.edge_hash)
            else:
                self.store.record(e.edge_hash, v.verdict, v.reason, self.judge.model)
                stats.judged += 1
        if unjudged:
            self.store.release(unjudged, attempts_allowed)
            stats.released = len(unjudged)
        return stats

    def _log_failure(self, exc: BaseException, n_edges: int) -> None:
        """One concise line per error type per 30 s, no traceback, so a bad key cannot flood the console."""
        name = type(exc).__name__
        now = time.monotonic()
        if now - self._last_logged.get(name, -1e9) >= 30:
            self._last_logged[name] = now
            log.error("judge call failed (%d edges): %s: %s", n_edges, name, str(exc)[:200])

    def drain(self, max_runs: int = 1000) -> RunStats:
        """Run until the queue is empty (tests, post-event pass). Returns summed stats."""
        total = RunStats()
        for _ in range(max_runs):
            s = self.run_once()
            if s.claimed == 0 or s.fatal:
                total.fatal |= s.fatal
                break
            total.claimed += s.claimed
            total.judged += s.judged
            total.released += s.released
            total.timed_out |= s.timed_out
            total.errored |= s.errored
        return total

    # ------------------------------------------------------------------ background thread
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="judge-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                s = self.run_once()
                if s.fatal:
                    log.error("judge stopped: %s (edges stay pending; fix the key and restart)", self.fatal)
                    return
                if s.claimed == 0:
                    self._stop.wait(self.poll_interval)
            except Exception:  # noqa: BLE001 - keep the worker alive
                log.exception("worker loop error")
                self._stop.wait(self.poll_interval)
