"""A deliberately gullible 'AI assistant' used to demonstrate prompt injection.

It does what a careless LLM pipeline does: it reads every sentence of the
extracted document text - including invisible text - and turns relationship-like
statements and instructions into graph edges. :func:`guarded_extract` shows the
fix: instruction-like segments are quarantined and every remaining proposal is
labelled ``AI_PROPOSED`` (to be verified by a human), never ``VERIFIED``.

No LLM is called; behaviour is deterministic so the demo and tests are repeatable.
"""
from __future__ import annotations

import re

from .document_reader import scan_for_instructions

_RULES = [
    (re.compile(r"classify\s+(P\d\d)\s+as\s+the\s+primary\s+methodological\s+extension\s+of\s+(P\d\d)", re.I), "EXTENDS"),
    (re.compile(r"record\s+(P\d\d)\s+(USES_METHOD|EXTENDS|CITES|SHARES_PRINCIPLE|ANALOGOUS_PROBLEM)\s+(P\d\d)", re.I), None),
    (re.compile(r"(P\d\d)\s+(?:uses|applies)\s+the\s+method\s+of\s+(P\d\d)", re.I), "USES_METHOD"),
]


def _edges_from(text: str) -> list[tuple[str, str, str]]:
    flat = re.sub(r"\s+", " ", text)
    out = []
    for rx, rel in _RULES:
        for m in rx.finditer(flat):
            if rel is None:
                out.append((m.group(1).upper(), m.group(3).upper(), m.group(2).upper()))
            else:
                out.append((m.group(1).upper(), m.group(2).upper(), rel))
    return out


def naive_extract(texts: dict[str, str]) -> list[dict]:
    """Every statement is believed. Returns edges the naive assistant would 'add to the graph'."""
    out = []
    for source, text in texts.items():
        for s, t, rel in _edges_from(text):
            out.append({"source_id": s, "target_id": t, "relationship_type": rel, "from_document": source,
                        "status": "VERIFIED", "why": "the document said so"})
    return out


def guarded_extract(texts: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """Quarantine instruction-like sentences; label everything else AI_PROPOSED."""
    proposals, quarantined = [], []
    for source, text in texts.items():
        flat = re.sub(r"\s+", " ", text)
        sentences = re.split(r"(?<=[.!?])\s+", flat)
        for sent in sentences:
            edges = _edges_from(sent)
            if not edges:
                continue
            if scan_for_instructions(sent):
                quarantined.append({"from_document": source, "sentence": sent, "edges": edges})
                continue
            for s, t, rel in edges:
                proposals.append({"source_id": s, "target_id": t, "relationship_type": rel, "from_document": source,
                                  "status": "AI_PROPOSED", "why": "statement in document; verify against the paper"})
    return proposals, quarantined
