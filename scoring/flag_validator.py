"""Submission 2 - one-shot research discovery flag.

Security model
--------------
* The organiser's plain answer lives in ``data/answer_key/final_answer.json``.
  ``build_flag_registry`` turns it into ``flag_registry.json``, which holds only
  HMAC-SHA256 tokens computed with the server-side secret ``FLAG_HMAC_SECRET``.
  A public SHA-256 of a short answer such as a product name could be brute-forced
  from a word list; an HMAC cannot be checked without the secret.
* The participant-serving validator reads only the registry plus the secret from
  the environment. The secret is never written to disk by this code, never put in
  a response, and never sent to the browser.
* Each team gets exactly one accepted final submission. It is timestamped, locked,
  and its correctness is NOT revealed until the deadline has passed.
* A correct team earns a team-bound flag ``UL{...}`` (an HMAC over team, target and
  application), stored server-side for the organiser's results table.
* Any application that is not a canonical alias goes to MANUAL_REVIEW, never to
  automatic rejection.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os
import re
import unicodedata

from challenge.submission_store import SubmissionStore, iso, now_utc

MIN_PRINCIPLE_CHARS = 40
FIELDS = ("base_id", "target_id", "principle", "application", "paper_evidence", "application_evidence", "limitations")


class SecretMissing(RuntimeError):
    pass


def get_secret() -> str:
    s = os.environ.get("FLAG_HMAC_SECRET", "")
    if not s or s == "change-me" or len(s) < 16:
        raise SecretMissing("FLAG_HMAC_SECRET is not configured (set a random value of at least 16 characters in .env)")
    return s


# ------------------------------------------------------------------ normalisation
def normalise_application(name: str) -> str:
    """'  NextStrain.org ', 'Nextstrain (Augur/Auspice)' -> 'nextstrainorg', 'nextstrainaugurauspice'."""
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower().strip()
    s = re.sub(r"^(the|a|an)\s+", "", s)
    s = re.sub(r"https?://|www\.", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def normalise_pid(pid: str) -> str:
    m = re.fullmatch(r"\s*[Pp]\s*0*(\d{1,2})\s*", pid or "")
    return f"P{int(m.group(1)):02d}" if m else (pid or "").strip().upper()


def token(secret: str, kind: str, value: str) -> str:
    return hmac.new(secret.encode(), f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()


def _matches(secret: str, kind: str, value: str, tokens: list[str]) -> bool:
    t = token(secret, kind, value)
    found = False
    for candidate in tokens:  # constant-time comparisons, no early exit
        found |= hmac.compare_digest(t, candidate)
    return found


# ------------------------------------------------------------------ registry (organiser build step)
def build_flag_registry(final_answer: dict, secret: str) -> dict:
    app = final_answer["application"]
    aliases = sorted({normalise_application(app["canonical"])} | {normalise_application(a) for a in app["normalised_aliases"]})
    alts = sorted({normalise_application(a) for a in final_answer.get("accepted_alternative_applications", [])})
    return {
        "_comment": "ORGANISER ONLY. HMAC-SHA256 tokens keyed by FLAG_HMAC_SECRET; contains no plaintext answers.",
        "version": 1,
        "algorithm": "HMAC-SHA256",
        "key_check": token(secret, "key-check", "uncharted-literature"),
        "base_token": token(secret, "paper", normalise_pid(final_answer["base_participant_id"])),
        "target_token": token(secret, "paper", normalise_pid(final_answer["target_participant_id"])),
        "application_tokens": [token(secret, "application", a) for a in aliases],
        "accepted_alternative_tokens": [token(secret, "application", a) for a in alts],
        "advisory_keyword_groups": {k: v for k, v in final_answer["principle_keyword_groups"].items() if not k.startswith("_")},
    }


def check_key(registry: dict, secret: str) -> None:
    if not hmac.compare_digest(registry["key_check"], token(secret, "key-check", "uncharted-literature")):
        raise SecretMissing("FLAG_HMAC_SECRET does not match the secret used to build flag_registry.json - rebuild the registry")


# ------------------------------------------------------------------ validation
def validate_form(sub: dict) -> list[str]:
    errs = []
    for f in FIELDS:
        if not str(sub.get(f, "")).strip():
            errs.append(f"'{f}' is required")
    if len(str(sub.get("principle", "")).strip()) < MIN_PRINCIPLE_CHARS:
        errs.append(f"Explain the shared principle in at least {MIN_PRINCIPLE_CHARS} characters (a product name alone is not enough).")
    if sub.get("application_evidence") and not re.search(r"https?://|doi\.org|10\.\d{4,}/", str(sub["application_evidence"])):
        errs.append("application_evidence must include at least one link or DOI to a credible source")
    if sub.get("paper_evidence") and not re.search(r"\bP\d{2}\b", str(sub["paper_evidence"]).upper()):
        errs.append("paper_evidence must reference corpus papers by ID (e.g. P07) with page/section")
    return errs


def advisory_principle_score(text: str, groups: dict[str, list[str]]) -> int:
    low = (text or "").lower()
    return sum(1 for words in groups.values() if any(w in low for w in words))


def evaluate(sub: dict, registry: dict, secret: str) -> dict:
    """Organiser-side evaluation of one submission (never returned to participants before the deadline)."""
    target_ok = _matches(secret, "paper", normalise_pid(sub["target_id"]), [registry["target_token"]])
    base_ok = _matches(secret, "paper", normalise_pid(sub["base_id"]), [registry["base_token"]])
    app_norm = normalise_application(sub["application"])
    if _matches(secret, "application", app_norm, registry["application_tokens"]):
        app_status = "CANONICAL"
    elif _matches(secret, "application", app_norm, registry.get("accepted_alternative_tokens", [])):
        app_status = "ACCEPTED_ALTERNATIVE"
    else:
        app_status = "MANUAL_REVIEW"
    if target_ok and base_ok and app_status in ("CANONICAL", "ACCEPTED_ALTERNATIVE"):
        result = "CORRECT"
    elif target_ok and base_ok:
        result = "MANUAL_REVIEW"
    else:
        result = "INCORRECT"
    return {
        "result": result,
        "target_correct": target_ok,
        "base_correct": base_ok,
        "application_status": app_status,
        "application_normalised": app_norm,
        "principle_advisory_score": advisory_principle_score(sub["principle"], registry["advisory_keyword_groups"]),
        "principle_advisory_max": len(registry["advisory_keyword_groups"]),
    }


def team_flag(secret: str, team_id: str, target: str, app_norm: str) -> str:
    return "UL{" + token(secret, "flag", f"{team_id}|{normalise_pid(target)}|{app_norm}")[:24] + "}"


class FinalSubmissionService:
    def __init__(self, store: SubmissionStore, registry: dict, deadline: str | None, secret: str | None = None):
        self.store = store
        self.registry = registry
        self.deadline = dt.datetime.fromisoformat(deadline) if deadline else None
        self._secret = secret  # resolved lazily from the environment if None

    @property
    def secret(self) -> str:
        s = self._secret or get_secret()
        check_key(self.registry, s)
        return s

    def deadline_passed(self, at: dt.datetime | None = None) -> bool:
        return bool(self.deadline and (at or now_utc()) > self.deadline)

    def submit(self, team_id: str, sub: dict, at: dt.datetime | None = None) -> dict:
        """Validate and lock a team's single final submission. Returns a participant-safe receipt."""
        at = at or now_utc()
        if self.store.has_final(team_id):
            raise PermissionError("Your team has already made its final submission. It is locked and cannot be changed.")
        if self.deadline_passed(at):
            raise PermissionError("The final submission deadline has passed.")
        errs = validate_form(sub)
        if errs:
            return {"accepted": False, "errors": errs}
        clean = {f: str(sub[f]).strip() for f in FIELDS}
        clean["base_id"], clean["target_id"] = normalise_pid(clean["base_id"]), normalise_pid(clean["target_id"])
        secret = self.secret
        ev = evaluate(clean, self.registry, secret)
        flag = team_flag(secret, team_id, clean["target_id"], ev["application_normalised"]) if ev["result"] == "CORRECT" else None
        receipt_id = hashlib.sha256(f"{team_id}|{iso(at)}|{sorted(clean.items())}".encode()).hexdigest()[:12]
        record = {"team_id": team_id, "submitted_at": iso(at), "receipt_id": receipt_id, "submission": clean,
                  "evaluation": ev, "flag": flag, "locked": True}
        self.store.lock_final(team_id, record)
        return {"accepted": True, "locked": True, "submitted_at": record["submitted_at"], "receipt_id": receipt_id,
                "message": "Final submission received and locked. Results are released after the deadline."}

    def participant_status(self, team_id: str, at: dt.datetime | None = None) -> dict:
        rec = self.store.final_submissions().get(team_id)
        if not rec:
            return {"submitted": False}
        out = {"submitted": True, "submitted_at": rec["submitted_at"], "receipt_id": rec["receipt_id"]}
        if self.deadline_passed(at):
            review = rec.get("organiser_review", {})
            out["result"] = review.get("final_result", rec["evaluation"]["result"])
            out["flag"] = rec["flag"] if out["result"] == "CORRECT" else None
        else:
            out["result"] = "hidden until the deadline"
        return out


# ------------------------------------------------------------------ Section A: Multi-Level Flag Validator
def normalise_flag(s: str) -> str:
    """Safely normalize flag candidate text without leaking internal format."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


class LevelFlagValidator:
    """Server-side flag validator enforcing cooldowns, attempt counting, and penalty logic.

    Rules:
    1. Unlimited flag attempts are permitted before final submission.
    2. Correct and incorrect attempts return immediate feedback.
    3. The first five incorrect attempts per team per level are free.
    4. Starting from the 6th incorrect attempt, each incorrect attempt deducts 1 flag point.
    5. A 30-second cooldown applies after EVERY incorrect attempt, including the first five.
    6. Attempts are logged separately for each team and level.
    7. Correct attempts never incur penalties.
    8. Cooldowns and attempt counts are strictly enforced on the backend.
    9. Attempts during an active cooldown are rejected without incrementing wrong counts or applying penalties.
    10. A correct flag never reveals server-side answer keys or alternative answer lists.
    """

    def __init__(
        self,
        cooldown_seconds: int = 30,
        free_wrong_attempts: int = 5,
        flag_points_per_level: int = 10,
        penalty_per_attempt: float = 1.0,
    ):
        self.cooldown_seconds = int(cooldown_seconds)
        self.free_wrong_attempts = int(free_wrong_attempts)
        self.flag_points_per_level = int(flag_points_per_level)
        self.penalty_per_attempt = float(penalty_per_attempt)

    def evaluate_attempt(
        self,
        team_id: str,
        level: int,
        answer: str,
        expected_answers: list[str],
        attempt_history: list[dict],
        is_locked: bool = False,
        now: dt.datetime | None = None,
    ) -> dict:
        """Evaluate a participant's flag attempt with cooldown and penalty enforcement."""
        if is_locked:
            return {
                "correct": False,
                "locked": True,
                "message": "This level is already locked.",
                "cooldown_remaining": 0,
                "record_attempt": False,
            }

        clean_answer = str(answer or "").strip()
        if not clean_answer:
            return {
                "correct": False,
                "message": "Enter a flag answer before submitting an attempt.",
                "cooldown_remaining": 0,
                "record_attempt": False,
            }

        server_now = now or dt.datetime.now(dt.timezone.utc)
        wrong_attempts = [a for a in attempt_history if not a.get("correct") and a.get("counted", True)]

        # Check cooldown from last valid wrong attempt
        if wrong_attempts and self.cooldown_seconds > 0:
            last_wrong = wrong_attempts[-1]
            try:
                last_time = dt.datetime.fromisoformat(last_wrong["at"])
                if last_time.tzinfo is None:
                    last_time = last_time.replace(tzinfo=dt.timezone.utc)
                elapsed = (server_now - last_time).total_seconds()
                if elapsed < self.cooldown_seconds:
                    remaining = int(self.cooldown_seconds - elapsed) + 1
                    # Rule 9: Reject attempt without incrementing count or penalty
                    return {
                        "correct": False,
                        "cooldown": True,
                        "cooldown_remaining": remaining,
                        "message": f"Cooldown active. Please wait {remaining}s before trying again.",
                        "record_attempt": False,
                    }
            except (ValueError, TypeError, KeyError):
                pass

        # Check correctness against normalized server answers
        norm_input = normalise_flag(clean_answer)
        norm_expected = {normalise_flag(x) for x in expected_answers if x}
        correct = norm_input in norm_expected

        iso_time = server_now.isoformat(timespec="seconds")
        if correct:
            n_wrong = len(wrong_attempts)
            penalty = max(0, n_wrong - self.free_wrong_attempts) * self.penalty_per_attempt
            earned = max(0, int(self.flag_points_per_level - penalty))
            msg = f"Correct flag! Earned {earned}/{self.flag_points_per_level} flag points."
            if penalty > 0:
                msg += f" (-{int(penalty)} pt penalty from {n_wrong} wrong attempts)."
            return {
                "correct": True,
                "cooldown": False,
                "message": msg,
                "earned_points": earned,
                "penalty_points": int(penalty),
                "cooldown_remaining": 0,
                "record_attempt": True,
                "attempt_record": {
                    "at": iso_time,
                    "answer": clean_answer,
                    "correct": True,
                    "counted": True,
                },
            }
        else:
            n_wrong = len(wrong_attempts) + 1
            if n_wrong <= self.free_wrong_attempts:
                free_left = self.free_wrong_attempts - n_wrong
                msg = f"Incorrect flag. 30s cooldown applies. ({free_left} free wrong attempts remaining)."
            else:
                penalty = int((n_wrong - self.free_wrong_attempts) * self.penalty_per_attempt)
                msg = f"Incorrect flag. 30s cooldown applies. (Penalty: -{penalty} flag point(s) from 6th wrong attempt)."
            return {
                "correct": False,
                "cooldown": False,
                "message": msg,
                "cooldown_remaining": self.cooldown_seconds,
                "wrong_count": n_wrong,
                "record_attempt": True,
                "attempt_record": {
                    "at": iso_time,
                    "answer": clean_answer,
                    "correct": False,
                    "counted": True,
                },
            }

    def compute_status(self, attempt_history: list[dict], now: dt.datetime | None = None) -> dict:
        """Compute status, penalty points, points, and remaining cooldown for a team/level."""
        server_now = now or dt.datetime.now(dt.timezone.utc)
        counted = [a for a in attempt_history if a.get("counted", True)]
        correct = any(x.get("correct") for x in counted)
        wrong = [x for x in counted if not x.get("correct")]
        wrong_count = len(wrong)
        penalty = int(max(0, wrong_count - self.free_wrong_attempts) * self.penalty_per_attempt)
        earned = max(0, int(self.flag_points_per_level - penalty)) if correct else 0

        cooldown_remaining = 0
        if wrong and self.cooldown_seconds > 0:
            try:
                last_time = dt.datetime.fromisoformat(wrong[-1]["at"])
                if last_time.tzinfo is None:
                    last_time = last_time.replace(tzinfo=dt.timezone.utc)
                elapsed = (server_now - last_time).total_seconds()
                if elapsed < self.cooldown_seconds:
                    cooldown_remaining = int(self.cooldown_seconds - elapsed) + 1
            except (ValueError, TypeError, KeyError):
                pass

        return {
            "correct": correct,
            "attempts": len(counted),
            "wrong_attempts": wrong_count,
            "penalty_points": penalty,
            "flag_points": earned,
            "cooldown_remaining": cooldown_remaining,
            "history": counted,
            "last": counted[-1] if counted else None,
        }

