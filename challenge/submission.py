"""Participant backend facade - the ONLY bridge between the participant UI and protected data.

Everything returned by :class:`ParticipantBackend` is participant-safe by
construction: aggregate scores for the public split, validation messages that
use only public metadata, released hints, and final-submission receipts that do
not reveal correctness before the deadline. Answer-key material is loaded
inside this module (server-side) and never returned.
"""
from __future__ import annotations

import os
from functools import lru_cache

from . import hints as hints_mod
from . import paths
from .participant_data import participant_infos
from .submission_store import SubmissionStore

ALLOWED_SCORE_KEYS = {"split", "weighted_f1", "weighted_precision", "recall", "edges_scored"}


class ParticipantBackend:
    def __init__(self, store: SubmissionStore | None = None, config: dict | None = None):
        self.store = store or SubmissionStore()
        self.config = config or paths.load_config()

    # ----------------------------------------------------------- auth
    def login(self, code: str) -> dict | None:
        return self.store.authenticate(code) if code and code.strip() else None

    # ----------------------------------------------------------- Submission 1
    def validate(self, csv_text: str) -> dict:
        from scoring.graph_scorer import parse_submission

        p = parse_submission(csv_text, participant_infos(), self.config["graph_submission"]["max_rows"])
        return {"ok": p.ok, "errors": p.errors, "warnings": p.warnings, "n_edges": len(p.edges)}

    def submit_graph(self, team_id: str, csv_text: str) -> dict:
        from scoring.graph_scorer import GraphScorer, parse_submission

        ok, why = self.store.can_submit_graph(team_id, self.config)
        if not ok:
            return {"accepted": False, "errors": [why], "warnings": []}
        parsed = parse_submission(csv_text, participant_infos(), self.config["graph_submission"]["max_rows"])
        if not parsed.ok:
            return {"accepted": False, "errors": parsed.errors, "warnings": parsed.warnings,
                    "note": "Rejected submissions do not count towards your limit."}
        if not parsed.edges:
            return {"accepted": False, "errors": ["Your graph is empty - add at least one relationship."], "warnings": []}
        scorer = GraphScorer.from_answer_key(self.store.accepted_additions(), self.config)
        result = scorer.score(parsed.edges)
        self.store.record_graph_submission(team_id, parsed.edges, parsed.evidence, result)
        view = result.participant_view(self.config["graph_submission"]["leaderboard_split"])
        assert set(view) <= ALLOWED_SCORE_KEYS
        return {"accepted": True, "score": view, "warnings": parsed.warnings}

    def history(self, team_id: str) -> list[dict]:
        split = self.config["graph_submission"]["leaderboard_split"]
        out = []
        for s in self.store.graph_submissions(team_id):
            m = s["scores"][split]
            out.append({"submitted_at": s["submitted_at"], "edges": s["n_edges"],
                        "weighted_f1": round(m["weighted_f1"], 4),
                        "weighted_precision": round(m["weighted_precision"], 4), "recall": round(m["recall"], 4)})
        return out

    def remaining_submissions(self, team_id: str) -> int:
        used = len([s for s in self.store.graph_submissions(team_id) if s["status"] == "scored"])
        return max(0, self.config["graph_submission"]["max_submissions_per_team"] - used)

    def leaderboard(self) -> list[dict]:
        split = self.config["graph_submission"]["leaderboard_split"]
        rows = self.store.best_scores(split, self.config["final_submission"].get("deadline"))
        return [{"rank": i + 1, "team": r["team"], "best_weighted_f1": round(r["weighted_f1"], 4)} for i, r in enumerate(rows)]

    # ----------------------------------------------------------- hints
    def released_hints(self) -> list[dict]:
        return hints_mod.released_hints(self.store)

    # ----------------------------------------------------------- Submission 2
    def _final_service(self):
        from scoring.flag_validator import FinalSubmissionService

        deadline = os.environ.get("FINAL_DEADLINE") or self.config["final_submission"]["deadline"]
        return FinalSubmissionService(self.store, _registry(), deadline)

    def submit_final(self, team_id: str, form: dict) -> dict:
        from scoring.flag_validator import SecretMissing

        try:
            return self._final_service().submit(team_id, form)
        except PermissionError as exc:
            return {"accepted": False, "errors": [str(exc)]}
        except (SecretMissing, FileNotFoundError):
            return {"accepted": False, "errors": ["The flag service is not configured. Please tell an organiser."]}

    def final_status(self, team_id: str) -> dict:
        from scoring.flag_validator import SecretMissing

        try:
            return self._final_service().participant_status(team_id)
        except (SecretMissing, FileNotFoundError):
            return {"submitted": self.store.has_final(team_id), "result": "hidden until the deadline"}


@lru_cache(maxsize=1)
def _registry() -> dict:
    return paths.read_json(paths.FLAG_REGISTRY)
