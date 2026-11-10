"""Judge interface and a deterministic stub.

A real judge (LLM) will implement :class:`Judge`. It receives a batch of edges and returns one
:class:`Verdict` per edge hash. It may omit edges (they are retried) or raise (the whole batch is
retried); it must never be given any authority beyond choosing a label.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Protocol, Sequence

from .store import VERDICTS, EdgeRow


@dataclass(frozen=True)
class Verdict:
    verdict: str  # one of store.VERDICTS
    reason: str = ""


class Judge(Protocol):
    model: str

    def judge_batch(self, edges: Sequence[EdgeRow]) -> dict[str, Verdict]: ...


class StubJudge:
    """Deterministic fake: the verdict depends only on the edge hash, so tests are reproducible.

    ``delay`` simulates API latency; ``fail_first`` makes the first N calls raise (to test retries).
    """

    model = "stub"

    def __init__(self, delay: float = 0.0, fail_first: int = 0):
        self.delay = delay
        self.fail_first = fail_first
        self.calls = 0

    def judge_batch(self, edges: Sequence[EdgeRow]) -> dict[str, Verdict]:
        self.calls += 1
        if self.calls <= self.fail_first:
            raise RuntimeError("simulated judge failure")
        if self.delay:
            time.sleep(self.delay)
        out = {}
        for e in edges:
            n = int(hashlib.sha256(e.edge_hash.encode()).hexdigest(), 16) % len(VERDICTS)
            out[e.edge_hash] = Verdict(VERDICTS[n], "stub verdict")
        return out
