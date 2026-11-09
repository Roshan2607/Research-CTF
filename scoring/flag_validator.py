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


MAX_ANSWER_WORDS = 8


def _tokens(s: str) -> list[str]:
    out = []
    for tok in normalise_flag(s).split():
        m = re.fullmatch(r"p0*(\d{1,2})", tok)
        if m:  # paper IDs: p8, p08, P008 -> p08
            tok = f"p{int(m.group(1)):02d}"
        elif len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]  # crude plural folding: receivers -> receiver
        out.append(tok)
    return out


def _alias_hit(tokens: list[str], alias: str) -> bool:
    a = _tokens(alias)
    if not a:
        return False
    if len(a) == 1:
        return a[0] in tokens
    # multi-word alias: its words must appear as a contiguous phrase
    return any(tokens[i:i + len(a)] == a for i in range(len(tokens) - len(a) + 1))


def answer_matches(answer: str, aliases: list[str], max_words: int = MAX_ANSWER_WORDS) -> bool:
    """Keyword-group match: accept a short answer that contains one accepted alias as a word or phrase.

    Tolerates plurals, surrounding words and paper-ID formatting (p8 / P08); rejects keyword stuffing
    (answers longer than ``max_words`` words).
    """
    tokens = _tokens(answer)
    if not tokens or len(tokens) > max_words:
        return False
    return any(_alias_hit(tokens, a) for a in aliases if a)


def matches_any(answer: str, aliases: list[str]) -> bool:
    tokens = _tokens(answer)
    return bool(tokens) and any(_alias_hit(tokens, a) for a in aliases if a)


def cooldown_for(n_wrong: int, cooldown_seconds: int, schedule: list[int] | None) -> int:
    """Cooldown after the n-th wrong attempt. cooldown_seconds == 0 disables cooldowns entirely."""
    if cooldown_seconds <= 0 or n_wrong <= 0:
        return 0
    if schedule:
        return int(schedule[min(n_wrong, len(schedule)) - 1])
    return int(cooldown_seconds)


class LevelFlagValidator:
    """Server-side flag validator enforcing cooldowns, attempt counting, and penalty logic.

    Rules (configurable in config/challenge_config.json -> rules):
    1. Unlimited flag attempts before the level is locked; feedback is immediate.
    2. Answers are matched by keyword groups (accepted aliases), not exact strings. A hedged answer that
       also contains a decoy lure is rejected and recorded as a decoy signal for the debrief.
    3. The first ``free_wrong_attempts`` wrong attempts are free; each further wrong attempt costs
       ``penalty_per_attempt`` flag points, capped at ``max_penalty`` per level.
    4. A cooldown applies after EVERY wrong attempt, following ``cooldown_schedule`` (e.g. 10 s, 10 s, then 30 s).
    5. Attempts during an active cooldown are rejected without counting or penalty.
    6. Correct attempts never incur penalties and never reveal the accepted answer list.
    """

    def __init__(
        self,
        cooldown_seconds: int = 30,
        free_wrong_attempts: int = 5,
        flag_points_per_level: float = 10,
        penalty_per_attempt: float = 1.0,
        cooldown_schedule: list[int] | None = None,
        max_penalty: float | None = None,
    ):
        self.cooldown_seconds = int(cooldown_seconds)
        self.free_wrong_attempts = int(free_wrong_attempts)
        self.flag_points_per_level = float(flag_points_per_level)
        self.penalty_per_attempt = float(penalty_per_attempt)
        self.cooldown_schedule = list(cooldown_schedule) if cooldown_schedule else None
        self.max_penalty = float(max_penalty) if max_penalty is not None else float(flag_points_per_level)

    def _penalty(self, n_wrong: int) -> float:
        raw = max(0, n_wrong - self.free_wrong_attempts) * self.penalty_per_attempt
        return round(min(raw, self.max_penalty), 2)

    def _remaining_cooldown(self, wrong: list[dict], server_now: dt.datetime) -> int:
        if not wrong:
            return 0
        cd = cooldown_for(len(wrong), self.cooldown_seconds, self.cooldown_schedule)
        if cd <= 0:
            return 0
        try:
            last_time = dt.datetime.fromisoformat(wrong[-1]["at"])
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=dt.timezone.utc)
        except (ValueError, TypeError, KeyError):
            return 0
        elapsed = (server_now - last_time).total_seconds()
        return int(cd - elapsed) + 1 if elapsed < cd else 0

    def evaluate_attempt(
        self,
        team_id: str,
        level: int,
        answer: str,
        expected_answers: list[str],
        attempt_history: list[dict],
        is_locked: bool = False,
        now: dt.datetime | None = None,
        decoy_answers: list[str] | None = None,
    ) -> dict:
        """Evaluate a participant's flag attempt with cooldown and penalty enforcement."""
        if is_locked:
            return {"correct": False, "locked": True, "message": "This level is already locked.",
                    "cooldown_remaining": 0, "record_attempt": False}

        clean_answer = str(answer or "").strip()
        if not clean_answer:
            return {"correct": False, "message": "Enter a flag answer before submitting an attempt.",
                    "cooldown_remaining": 0, "record_attempt": False}

        server_now = now or dt.datetime.now(dt.timezone.utc)
        wrong_attempts = [a for a in attempt_history if not a.get("correct") and a.get("counted", True)]
        remaining = self._remaining_cooldown(wrong_attempts, server_now)
        if remaining > 0:
            return {"correct": False, "cooldown": True, "cooldown_remaining": remaining,
                    "message": f"Cooldown active. Please wait {remaining}s before trying again.",
                    "record_attempt": False}

        decoy_signal = bool(decoy_answers) and matches_any(clean_answer, decoy_answers)
        correct = answer_matches(clean_answer, expected_answers) and not decoy_signal
        record = {"at": server_now.isoformat(timespec="seconds"), "answer": clean_answer,
                  "correct": correct, "counted": True}
        if decoy_signal:
            record["decoy_signal"] = True

        if correct:
            n_wrong = len(wrong_attempts)
            penalty = self._penalty(n_wrong)
            earned = round(max(0.0, self.flag_points_per_level - penalty), 2)
            msg = f"Correct flag! Earned {earned:g}/{self.flag_points_per_level:g} flag points."
            if penalty > 0:
                msg += f" (-{penalty:g} pt penalty from {n_wrong} wrong attempts)."
            return {"correct": True, "cooldown": False, "message": msg, "earned_points": earned,
                    "penalty_points": penalty, "cooldown_remaining": 0, "record_attempt": True,
                    "attempt_record": record}

        n_wrong = len(wrong_attempts) + 1
        cd = cooldown_for(n_wrong, self.cooldown_seconds, self.cooldown_schedule)
        cd_text = f"{cd}s cooldown applies. " if cd else ""
        if n_wrong <= self.free_wrong_attempts:
            msg = f"Incorrect flag. {cd_text}({self.free_wrong_attempts - n_wrong} free wrong attempts remaining)."
        else:
            msg = (f"Incorrect flag. {cd_text}(Penalty so far: -{self._penalty(n_wrong):g} flag point(s), "
                   f"capped at {self.max_penalty:g}).")
        return {"correct": False, "cooldown": False, "message": msg, "cooldown_remaining": cd,
                "wrong_count": n_wrong, "record_attempt": True, "attempt_record": record}

    def compute_status(self, attempt_history: list[dict], now: dt.datetime | None = None,
                       hint_cost: float = 0.0) -> dict:
        """Status, penalty, points (after any hint cost) and remaining cooldown for a team/level."""
        server_now = now or dt.datetime.now(dt.timezone.utc)
        counted = [a for a in attempt_history if a.get("counted", True)]
        correct = any(x.get("correct") for x in counted)
        first_correct = next((i for i, x in enumerate(counted) if x.get("correct")), None)
        before_correct = counted if first_correct is None else counted[:first_correct]
        wrong_before = [x for x in before_correct if not x.get("correct")]
        all_wrong = [x for x in counted if not x.get("correct")]
        penalty = self._penalty(len(wrong_before))
        earned = round(max(0.0, self.flag_points_per_level - penalty - float(hint_cost)), 2) if correct else 0
        return {
            "correct": correct,
            "attempts": len(counted),
            "wrong_attempts": len(all_wrong),
            "penalty_points": penalty,
            "hint_cost": float(hint_cost),
            "flag_points": earned,
            "cooldown_remaining": 0 if correct else self._remaining_cooldown(all_wrong, server_now),
            "decoy_signals": sum(1 for x in counted if x.get("decoy_signal")),
            "history": counted,
            "last": counted[-1] if counted else None,
        }
