"""Submission data layer (runtime, git-ignored): teams, graph submissions, review
queue, accepted additions, hint releases and final one-shot submissions.

Storage is plain JSON / JSONL under ``data/submissions`` with atomic writes and a
process-wide lock (Streamlit serves all sessions from one process). Good enough
for a single-machine workshop of ~30 teams; documented as a limitation.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import secrets
import threading
from pathlib import Path

from . import paths

_LOCK = threading.RLock()


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(t: dt.datetime) -> str:
    return t.isoformat(timespec="seconds")


class SubmissionStore:
    def __init__(self, base: Path | None = None):
        self.base = Path(base or paths.SUBMISSIONS_DIR)
        self.base.mkdir(parents=True, exist_ok=True)
        self.teams_path = self.base / "teams.json"
        self.graph_log = self.base / "graph_submissions.jsonl"
        self.review_path = self.base / "review_queue.json"
        self.accepted_path = self.base / "accepted_additions.json"
        self.final_path = self.base / "final_submissions.json"
        self.hints_path = self.base / "hint_state.json"

    # ------------------------------------------------------------------ helpers
    def _read(self, p: Path, default):
        if not p.exists():
            return default
        return json.loads(p.read_text(encoding="utf-8"))

    def _write(self, p: Path, obj) -> None:
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(p)

    # ------------------------------------------------------------------ teams
    def create_team(self, name: str, members: list[str] | None = None) -> dict:
        name = name.strip()
        if not name:
            raise ValueError("team name required")
        with _LOCK:
            teams = self._read(self.teams_path, {})
            if any(t["name"].lower() == name.lower() for t in teams.values()):
                raise ValueError(f"team {name!r} already exists")
            team_id = f"T{len(teams) + 1:02d}"
            code = "-".join(secrets.token_hex(2).upper() for _ in range(2))
            teams[team_id] = {
                "team_id": team_id,
                "name": name,
                "members": members or [],
                "code_sha256": hashlib.sha256(code.encode()).hexdigest(),
                "created_at": iso(now_utc()),
            }
            self._write(self.teams_path, teams)
        return {"team_id": team_id, "name": name, "code": code}

    def teams(self) -> dict:
        return self._read(self.teams_path, {})

    def authenticate(self, code: str) -> dict | None:
        h = hashlib.sha256(code.strip().upper().encode()).hexdigest()
        for t in self.teams().values():
            if secrets.compare_digest(t["code_sha256"], h):
                return {"team_id": t["team_id"], "name": t["name"]}
        return None

    # ------------------------------------------------------------------ graph submissions
    def graph_submissions(self, team_id: str | None = None) -> list[dict]:
        if not self.graph_log.exists():
            return []
        rows = [json.loads(l) for l in self.graph_log.read_text(encoding="utf-8").splitlines() if l.strip()]
        return [r for r in rows if team_id is None or r["team_id"] == team_id]

    def can_submit_graph(self, team_id: str, config: dict, at: dt.datetime | None = None) -> tuple[bool, str]:
        at = at or now_utc()
        gs = config["graph_submission"]
        subs = [s for s in self.graph_submissions(team_id) if s["status"] == "scored"]
        if len(subs) >= gs["max_submissions_per_team"]:
            return False, f"Submission limit reached ({gs['max_submissions_per_team']})."
        if subs:
            last = dt.datetime.fromisoformat(subs[-1]["submitted_at"])
            wait = gs["min_seconds_between_submissions"] - (at - last).total_seconds()
            if wait > 0:
                return False, f"Please wait {int(wait) + 1} s before submitting again."
        deadline = config.get("final_submission", {}).get("deadline")
        if deadline and at > dt.datetime.fromisoformat(deadline):
            return False, "The submission deadline has passed."
        return True, ""

    def record_graph_submission(self, team_id: str, edges, evidence: dict, result, at: dt.datetime | None = None) -> dict:
        """Persist a scored submission. ``result`` is a scoring.graph_scorer.ScoreResult."""
        at = at or now_utc()
        rec = {
            "team_id": team_id,
            "submitted_at": iso(at),
            "status": "scored",
            "n_edges": len(edges),
            "edges": [list(e) for e in edges],
            "evidence": {"|".join(k): v for k, v in evidence.items()},
            "scores": result.organiser_view(),
        }
        with _LOCK:
            with self.graph_log.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            # review queue: false-positive edges that came with evidence
            queue = self._read(self.review_path, [])
            known = {(q["team_id"], q["edge"]) for q in queue}
            for e, cls in result.per_edge_class.items():
                key = "|".join(e)
                if cls in ("ordinary", "decoy_induced", "injection_induced") and evidence.get(e) and (team_id, key) not in known:
                    queue.append(
                        {
                            "team_id": team_id,
                            "edge": key,
                            "evidence_reference": evidence[e],
                            "organiser_class": cls,
                            "status": "PENDING",
                            "submitted_at": iso(at),
                        }
                    )
            self._write(self.review_path, queue)
        return rec

    def best_scores(self, split: str = "public", deadline: str | None = None) -> list[dict]:
        """Best valid score per team (before the deadline), for the leaderboard."""
        best: dict[str, dict] = {}
        dl = dt.datetime.fromisoformat(deadline) if deadline else None
        for s in self.graph_submissions():
            if s["status"] != "scored":
                continue
            if dl and dt.datetime.fromisoformat(s["submitted_at"]) > dl:
                continue
            f1 = s["scores"][split]["weighted_f1"]
            if s["team_id"] not in best or f1 > best[s["team_id"]]["weighted_f1"]:
                best[s["team_id"]] = {"team_id": s["team_id"], "weighted_f1": f1, "submitted_at": s["submitted_at"]}
        names = {k: v["name"] for k, v in self.teams().items()}
        rows = [{**b, "team": names.get(b["team_id"], b["team_id"])} for b in best.values()]
        return sorted(rows, key=lambda r: (-r["weighted_f1"], r["submitted_at"]))

    # ------------------------------------------------------------------ review queue
    def review_queue(self) -> list[dict]:
        return self._read(self.review_path, [])

    def decide_review(self, index: int, decision: str, reviewer: str, notes: str = "") -> dict:
        if decision not in ("ACCEPTED", "REJECTED"):
            raise ValueError("decision must be ACCEPTED or REJECTED")
        if not reviewer.strip():
            raise ValueError("reviewer name required")
        with _LOCK:
            queue = self.review_queue()
            item = queue[index]
            item.update(status=decision, reviewer=reviewer.strip(), reviewer_notes=notes, decided_at=iso(now_utc()))
            self._write(self.review_path, queue)
            if decision == "ACCEPTED":
                acc = self._read(self.accepted_path, [])
                edge = item["edge"].split("|")
                if edge not in acc:
                    acc.append(edge)
                    self._write(self.accepted_path, acc)
        return item

    def accepted_additions(self) -> list[tuple[str, str, str]]:
        return [tuple(e) for e in self._read(self.accepted_path, [])]

    # ------------------------------------------------------------------ hints
    def released_hints(self) -> list[int]:
        return self._read(self.hints_path, {"released": []})["released"]

    def release_hint(self, hint_id: int) -> None:
        with _LOCK:
            st = self._read(self.hints_path, {"released": [], "log": []})
            if hint_id not in st["released"]:
                st["released"].append(hint_id)
                st.setdefault("log", []).append({"hint": hint_id, "at": iso(now_utc())})
                self._write(self.hints_path, st)

    # ------------------------------------------------------------------ final one-shot submissions
    def final_submissions(self) -> dict:
        return self._read(self.final_path, {})

    def has_final(self, team_id: str) -> bool:
        return team_id in self.final_submissions()

    def lock_final(self, team_id: str, record: dict) -> dict:
        """Store a team's single final submission; raises if one already exists."""
        with _LOCK:
            finals = self.final_submissions()
            if team_id in finals:
                raise PermissionError("This team has already made its final submission. It is locked.")
            finals[team_id] = record
            self._write(self.final_path, finals)
        return record

    def update_final_review(self, team_id: str, **fields) -> dict:
        with _LOCK:
            finals = self.final_submissions()
            finals[team_id].setdefault("organiser_review", {}).update(fields)
            self._write(self.final_path, finals)
            return finals[team_id]
