"""SQLite store for novel-edge judging (queue + cache + audit trail).

The submit handler only calls :meth:`JudgeStore.enqueue`; a separate worker claims
pending edges, calls the judge and records verdicts. Nothing here is read by the
progression gate or the live F1, so a slow or broken judge can never block a team.

Edges are deduplicated by a hash of (normalised edge + normalised evidence), so
identical edges from different teams are judged once and always get the same verdict.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from graph.schema import edge_key

# Edge lifecycle.
PENDING = "pending"
IN_PROGRESS = "in_progress"
DEFERRED = "deferred"  # gave up after max attempts; re-run later / in the post-event pass
VERDICTS = ("supported", "plausible", "unsupported", "abstain")
TERMINAL = frozenset(VERDICTS)

SCHEMA = """
CREATE TABLE IF NOT EXISTS submissions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id     TEXT NOT NULL,
    level       INTEGER NOT NULL,
    raw_csv     TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS edges (
    edge_hash   TEXT PRIMARY KEY,
    source_id   TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    rel_type    TEXT NOT NULL,
    evidence    TEXT NOT NULL,
    status      TEXT NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0,
    claimed_at  REAL,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_edges_status ON edges(status, created_at);
CREATE TABLE IF NOT EXISTS submission_edges (
    submission_id INTEGER NOT NULL REFERENCES submissions(id),
    edge_hash     TEXT NOT NULL REFERENCES edges(edge_hash),
    PRIMARY KEY (submission_id, edge_hash)
);
CREATE TABLE IF NOT EXISTS judgments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    edge_hash   TEXT NOT NULL REFERENCES edges(edge_hash),
    verdict     TEXT NOT NULL,
    reason      TEXT NOT NULL,
    model       TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_judgments_edge ON judgments(edge_hash);
"""


@dataclass(frozen=True)
class EdgeRow:
    edge_hash: str
    source_id: str
    target_id: str
    rel_type: str
    evidence: str
    attempts: int = 0


def normalise_evidence(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def hash_edge(source: str, target: str, rel: str, evidence: str) -> tuple[str, tuple[str, str, str]]:
    """Return (cache key, canonical edge). Symmetric relations hash identically either way round."""
    key = edge_key(source.strip().upper(), target.strip().upper(), rel.strip().upper())
    digest = hashlib.sha256("|".join((*key, normalise_evidence(evidence))).encode()).hexdigest()
    return digest, key


class JudgeStore:
    """Thread-safe SQLite store. One connection per thread, WAL mode, short transactions."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._local = threading.local()
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn().executescript(SCHEMA)  # executescript manages its own transaction

    # ------------------------------------------------------------------ connection plumbing
    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=15, isolation_level=None)  # autocommit; we BEGIN explicitly
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA busy_timeout=15000")
            self._local.conn = c
        return c

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        c = self._conn()
        c.execute("BEGIN IMMEDIATE")  # take the write lock up front so claim/record cannot interleave
        try:
            yield c
        except BaseException:
            c.execute("ROLLBACK")
            raise
        else:
            c.execute("COMMIT")

    def close(self) -> None:
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None

    # ------------------------------------------------------------------ submit side
    def enqueue(self, team_id: str, level: int, raw_csv: str, edges: Iterable[Sequence[str]]) -> tuple[int, list[str]]:
        """Record a submission and queue its novel edges. Never calls the judge.

        ``edges`` are (source, target, rel_type, evidence) tuples. Already-known edges are
        linked to the submission but not re-queued, which is what makes the cache work.
        Returns (submission_id, edge hashes).
        """
        now = time.time()
        hashes: list[str] = []
        with self._tx() as c:
            sid = c.execute(
                "INSERT INTO submissions(team_id, level, raw_csv, created_at) VALUES (?,?,?,?)",
                (team_id.strip().upper(), int(level), raw_csv, now),
            ).lastrowid
            for s, t, r, ev in edges:
                h, (cs, ct, cr) = hash_edge(s, t, r, ev)
                c.execute(
                    "INSERT OR IGNORE INTO edges(edge_hash, source_id, target_id, rel_type, evidence, status,"
                    " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                    (h, cs, ct, cr, ev or "", PENDING, now, now),
                )
                c.execute("INSERT OR IGNORE INTO submission_edges(submission_id, edge_hash) VALUES (?,?)", (sid, h))
                hashes.append(h)
        return sid, hashes

    # ------------------------------------------------------------------ worker side
    def claim_batch(self, limit: int = 10, lease_seconds: float = 60.0) -> list[EdgeRow]:
        """Atomically claim up to ``limit`` pending edges. Expired leases are reclaimed (crash recovery)."""
        now = time.time()
        with self._tx() as c:
            rows = c.execute(
                "SELECT edge_hash FROM edges WHERE status=? OR (status=? AND claimed_at < ?)"
                " ORDER BY created_at LIMIT ?",
                (PENDING, IN_PROGRESS, now - lease_seconds, limit),
            ).fetchall()
            hashes = [r["edge_hash"] for r in rows]
            if hashes:
                marks = ",".join("?" * len(hashes))
                c.execute(
                    f"UPDATE edges SET status=?, claimed_at=?, updated_at=?, attempts=attempts+1"
                    f" WHERE edge_hash IN ({marks})",
                    (IN_PROGRESS, now, now, *hashes),
                )
            out = c.execute(
                f"SELECT * FROM edges WHERE edge_hash IN ({','.join('?' * len(hashes))}) ORDER BY created_at",
                hashes,
            ).fetchall() if hashes else []
        return [EdgeRow(r["edge_hash"], r["source_id"], r["target_id"], r["rel_type"], r["evidence"], r["attempts"])
                for r in out]

    def record(self, edge_hash: str, verdict: str, reason: str, model: str) -> None:
        if verdict not in VERDICTS:
            verdict, reason = "abstain", f"invalid verdict from judge ({reason[:80]})"
        now = time.time()
        with self._tx() as c:
            c.execute("INSERT INTO judgments(edge_hash, verdict, reason, model, created_at) VALUES (?,?,?,?,?)",
                      (edge_hash, verdict, reason, model, now))
            c.execute("UPDATE edges SET status=?, claimed_at=NULL, updated_at=? WHERE edge_hash=?",
                      (verdict, now, edge_hash))

    def release(self, hashes: Iterable[str], max_attempts: int = 2) -> None:
        """Return unjudged edges to the queue, or defer them once they have used their attempts."""
        now = time.time()
        with self._tx() as c:
            for h in hashes:
                c.execute(
                    "UPDATE edges SET status=CASE WHEN attempts>=? THEN ? ELSE ? END, claimed_at=NULL, updated_at=?"
                    " WHERE edge_hash=? AND status=?",
                    (max_attempts, DEFERRED, PENDING, now, h, IN_PROGRESS),
                )

    def requeue_deferred(self) -> int:
        """Post-event / manual: give deferred edges a fresh set of attempts."""
        with self._tx() as c:
            cur = c.execute("UPDATE edges SET status=?, attempts=0, updated_at=? WHERE status=?",
                            (PENDING, time.time(), DEFERRED))
            return cur.rowcount

    # ------------------------------------------------------------------ read side
    def submission_status(self, submission_id: int) -> list[dict]:
        rows = self._conn().execute(
            "SELECT e.edge_hash, e.source_id, e.target_id, e.rel_type, e.status,"
            " (SELECT reason FROM judgments j WHERE j.edge_hash=e.edge_hash ORDER BY j.id DESC LIMIT 1) AS reason"
            " FROM submission_edges se JOIN edges e USING(edge_hash) WHERE se.submission_id=?"
            " ORDER BY e.source_id, e.target_id, e.rel_type",
            (submission_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def counts(self) -> dict[str, int]:
        rows = self._conn().execute("SELECT status, COUNT(*) n FROM edges GROUP BY status").fetchall()
        return {r["status"]: r["n"] for r in rows}

    def judgments_for(self, edge_hash: str) -> list[dict]:
        rows = self._conn().execute("SELECT * FROM judgments WHERE edge_hash=? ORDER BY id", (edge_hash,)).fetchall()
        return [dict(r) for r in rows]
