"""Progressive hints. The hint texts are organiser data; only RELEASED hints leave the server."""
from __future__ import annotations

from . import paths
from .submission_store import SubmissionStore


def all_hints() -> list[dict]:
    """Organiser use only."""
    return paths.read_json(paths.HINTS)["hints"]


def released_hints(store: SubmissionStore | None = None) -> list[dict]:
    store = store or SubmissionStore()
    released = set(store.released_hints())
    return [{"id": h["id"], "text": h["text"]} for h in all_hints() if h["id"] in released]
