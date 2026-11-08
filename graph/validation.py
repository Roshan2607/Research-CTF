"""Validation of the master graph records and of individual relationship claims.

``validate_records`` returns a list of :class:`Issue`; an empty list means the
graph is consistent with the schema. Checks:

* node IDs unique; node types valid; papers carry all required metadata;
* relationship types valid and their (source type, target type) signature allowed;
* both endpoints exist; edge direction preserved (no silent flipping of directed types);
* every edge has at least one complete evidence record (provenance);
* verification status valid; AI-proposed edges are never VERIFIED without a
  named human verifier;
* duplicate edges (same canonical source/target/type) are reported;
* temporal sanity for directed paper->paper claims (a paper cannot cite a work
  that was not yet public).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .schema import (
    EVIDENCE_REQUIRED_FIELDS,
    PAPER_REQUIRED_FIELDS,
    RELATIONS,
    TEMPORAL_RELATIONS,
    NodeType,
    Status,
    edge_key,
)

NODE_TYPES = {t.value for t in NodeType}
STATUSES = {s.value for s in Status}


@dataclass(frozen=True)
class Issue:
    severity: str  # "error" | "warning"
    where: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return f"[{self.severity}] {self.where}: {self.message}"


def check_relation(rel: str, src_node: dict | None, dst_node: dict | None) -> list[str]:
    """Return problems with a single typed relationship between two node records."""
    problems: list[str] = []
    spec = RELATIONS.get(rel)
    if spec is None:
        return [f"unknown relationship type {rel!r}"]
    if src_node is None or dst_node is None:
        return ["unknown source or target node"]
    sig = (NodeType(src_node["type"]), NodeType(dst_node["type"]))
    if sig not in spec.signatures:
        allowed = ", ".join(f"{a.value}->{b.value}" for a, b in spec.signatures)
        problems.append(f"{rel} not allowed for {sig[0].value}->{sig[1].value} (allowed: {allowed})")
    if src_node.get("id") == dst_node.get("id"):
        problems.append("self-loop: a node cannot relate to itself")
    if (
        rel in TEMPORAL_RELATIONS
        and src_node["type"] == "PAPER"
        and dst_node["type"] == "PAPER"
        and src_node.get("year") is not None
        and dst_node.get("first_public_year", dst_node.get("year")) is not None
        and src_node["year"] < dst_node.get("first_public_year", dst_node.get("year"))
    ):
        problems.append(
            f"invalid direction: {src_node.get('participant_id', src_node['id'])} ({src_node['year']}) cannot {rel} "
            f"{dst_node.get('participant_id', dst_node['id'])} (first public {dst_node.get('first_public_year', dst_node.get('year'))})"
        )
    return problems


def validate_records(records: dict) -> list[Issue]:
    issues: list[Issue] = []
    nodes = records.get("nodes", [])
    edges = records.get("edges", [])
    ids = Counter(n.get("id") for n in nodes)
    for nid, c in ids.items():
        if c > 1:
            issues.append(Issue("error", f"node {nid}", f"duplicate node id ({c} times)"))
    by_id = {n["id"]: n for n in nodes if "id" in n}
    pids = Counter(n.get("participant_id") for n in nodes if n.get("type") == "PAPER")
    for pid, c in pids.items():
        if c > 1 or pid is None:
            issues.append(Issue("error", f"participant id {pid}", "missing or duplicated participant id"))
    for n in nodes:
        if n.get("type") not in NODE_TYPES:
            issues.append(Issue("error", f"node {n.get('id')}", f"invalid node type {n.get('type')!r}"))
            continue
        if n["type"] == "PAPER":
            for f in PAPER_REQUIRED_FIELDS:
                if n.get(f) in (None, "", []):
                    issues.append(Issue("error", f"paper {n['id']}", f"missing required field {f!r}"))
        elif not n.get("label"):
            issues.append(Issue("warning", f"node {n['id']}", "concept node has no label"))
    edge_ids = Counter(e.get("id") for e in edges)
    for eid, c in edge_ids.items():
        if c > 1:
            issues.append(Issue("error", f"edge {eid}", "duplicate edge id"))
    seen: dict[tuple, str] = {}
    for e in edges:
        where = f"edge {e.get('id')} {e.get('source')}-{e.get('type')}->{e.get('target')}"
        if e.get("status") not in STATUSES:
            issues.append(Issue("error", where, f"invalid status {e.get('status')!r}"))
        for p in check_relation(e.get("type"), by_id.get(e.get("source")), by_id.get(e.get("target"))):
            issues.append(Issue("error", where, p))
        evid = e.get("evidence") or []
        if not evid:
            issues.append(Issue("error", where, "no provenance / evidence record"))
        for i, rec in enumerate(evid):
            for f in EVIDENCE_REQUIRED_FIELDS:
                if not rec.get(f):
                    issues.append(Issue("error", where, f"evidence[{i}] missing {f!r}"))
        if not e.get("explanation"):
            issues.append(Issue("error", where, "missing explanation"))
        if e.get("proposed_by") == "ai" and e.get("status") == Status.VERIFIED.value and not e.get("verified_by"):
            issues.append(Issue("error", where, "AI-proposed edge marked VERIFIED without a human verifier"))
        if e.get("type") in RELATIONS:
            key = edge_key(e["source"], e["target"], e["type"])
            if key in seen:
                issues.append(Issue("error", where, f"duplicate of edge {seen[key]}"))
            else:
                seen[key] = e.get("id")
    return issues


def errors(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity == "error"]


def promote_edge(edge: dict, reviewer: str, notes: str = "") -> dict:
    """Return a copy of an edge promoted to VERIFIED by a named human reviewer.

    This is the ONLY sanctioned way to verify an AI-proposed or participant-proposed edge.
    """
    if not reviewer or not reviewer.strip():
        raise ValueError("a named human reviewer is required to verify an edge")
    if not edge.get("evidence"):
        raise ValueError("cannot verify an edge without evidence")
    out = dict(edge)
    out["status"] = Status.VERIFIED.value
    out["verified_by"] = reviewer.strip()
    out["reviewer_notes"] = (edge.get("reviewer_notes", "") + " " + notes).strip()
    return out
