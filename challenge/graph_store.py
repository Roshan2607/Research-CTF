"""Persistent team knowledge graph data model.

Maintains one cumulative, persistent knowledge graph per team across CTF levels.
Supports:
- Node and edge structure validation
- Multi-level progression and graph extension
- Team ownership association
- Level-specific genuinely immutable submitted graph snapshots
- Seamless CSV and structured dictionary serialization
"""
from __future__ import annotations

import copy
import csv
import io
import re
import types
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from graph.schema import SUBMITTABLE_RELATIONS


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class GraphEdge:
    source_id: str
    target_id: str
    relationship_type: str
    evidence_reference: str = ""
    added_at_level: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relationship_type": self.relationship_type,
            "evidence_reference": self.evidence_reference,
            "added_at_level": self.added_at_level,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GraphEdge":
        return cls(
            source_id=str(data.get("source_id", "")).strip().upper(),
            target_id=str(data.get("target_id", "")).strip().upper(),
            relationship_type=str(data.get("relationship_type", "")).strip().upper().replace(" ", "_"),
            evidence_reference=str(data.get("evidence_reference", "")).strip(),
            added_at_level=int(data.get("added_at_level", 1)),
        )


@dataclass(frozen=True)
class LevelGraphSnapshot:
    """Genuinely immutable snapshot of a team's submitted graph for a locked level."""
    level: int
    submitted_at: str
    edges: tuple[Any, ...]  # tuple of mapping proxies
    nodes: tuple[str, ...]
    csv_text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "submitted_at": self.submitted_at,
            "edges": [dict(e) for e in self.edges],
            "nodes": list(self.nodes),
            "csv_text": self.csv_text,
        }

    @classmethod
    def create(
        cls,
        level: int,
        submitted_at: str,
        edges: list[dict[str, Any]],
        nodes: list[str],
        csv_text: str,
    ) -> "LevelGraphSnapshot":
        # Wrap each edge in an immutable MappingProxyType to prevent modification
        frozen_edges = tuple(types.MappingProxyType(dict(e)) for e in edges)
        frozen_nodes = tuple(str(n) for n in nodes)
        return cls(
            level=int(level),
            submitted_at=str(submitted_at),
            edges=frozen_edges,
            nodes=frozen_nodes,
            csv_text=str(csv_text),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LevelGraphSnapshot":
        return cls.create(
            level=int(data["level"]),
            submitted_at=str(data.get("submitted_at", "")),
            edges=list(data.get("edges", [])),
            nodes=list(data.get("nodes", [])),
            csv_text=str(data.get("csv_text", "")),
        )


class TeamKnowledgeGraph:
    """Represents a single team's cumulative knowledge graph."""

    def __init__(self, team_id: str, data: dict[str, Any] | None = None):
        self.team_id = str(team_id or "").strip().upper()
        self.edges: list[GraphEdge] = []
        self._snapshots: dict[int, LevelGraphSnapshot] = {}

        if data:
            self._load_from_dict(data)

    def _load_from_dict(self, data: dict[str, Any]) -> None:
        raw_edges = data.get("edges", [])
        self.edges = [GraphEdge.from_dict(e) for e in raw_edges]
        raw_snapshots = data.get("snapshots", {})
        self._snapshots = {}
        for lvl_str, snap_dict in raw_snapshots.items():
            lvl = int(lvl_str)
            self._snapshots[lvl] = LevelGraphSnapshot.from_dict(snap_dict)

    @property
    def snapshots(self) -> dict[int, LevelGraphSnapshot]:
        """Return a defensive copy of snapshots dict containing frozen snapshots."""
        return dict(self._snapshots)

    def to_dict(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "edges": [e.to_dict() for e in self.edges],
            "snapshots": {str(k): v.to_dict() for k, v in self._snapshots.items()},
        }

    def get_nodes(self) -> list[str]:
        nodes = set()
        for e in self.edges:
            nodes.add(e.source_id)
            nodes.add(e.target_id)
        return sorted(nodes)

    def get_edge_tuples(self) -> list[tuple[str, str, str]]:
        return [(e.source_id, e.target_id, e.relationship_type) for e in self.edges]

    def to_csv(self) -> str:
        out = io.StringIO()
        writer = csv.DictWriter(
            out,
            fieldnames=["source_id", "target_id", "relationship_type", "evidence_reference"],
            lineterminator="\n",
        )
        writer.writeheader()
        for e in self.edges:
            writer.writerow({
                "source_id": e.source_id,
                "target_id": e.target_id,
                "relationship_type": e.relationship_type,
                "evidence_reference": e.evidence_reference,
            })
        return out.getvalue()

    def set_edges_from_list(
        self,
        edge_dicts: list[dict[str, Any]],
        current_level: int,
        locked_levels: Iterable[int] = (),
    ) -> None:
        """Replace the live edges with ``edge_dicts``.

        The live graph stays editable until the final lock (earlier levels are preserved as immutable
        snapshots instead). An edge that survives keeps the level it was first added at; new edges are
        tagged with ``current_level``. ``locked_levels`` is accepted for backward compatibility.
        """
        existing = {(e.source_id, e.target_id, e.relationship_type): e for e in self.edges}
        new_edges: list[GraphEdge] = []
        seen: set[tuple[str, str, str]] = set()
        for d in edge_dicts:
            edge = GraphEdge.from_dict(d)
            key = (edge.source_id, edge.target_id, edge.relationship_type)
            if key in seen:
                continue
            seen.add(key)
            prev = existing.get(key)
            new_edges.append(
                GraphEdge(
                    source_id=edge.source_id,
                    target_id=edge.target_id,
                    relationship_type=edge.relationship_type,
                    evidence_reference=edge.evidence_reference,
                    added_at_level=prev.added_at_level if prev else current_level,
                )
            )
        self.edges = new_edges

    def snapshot_level(self, level: int, submitted_at: str | None = None, csv_text: str | None = None) -> LevelGraphSnapshot:
        """Create an immutable snapshot of the graph at the moment of level lock."""
        if level in self._snapshots:
            raise PermissionError(f"Level {level} graph is already locked and cannot be resubmitted.")

        snap_csv = csv_text if csv_text is not None else self.to_csv()
        nodes = self.get_nodes()
        edges_copy = [e.to_dict() for e in self.edges]
        snapshot = LevelGraphSnapshot.create(
            level=level,
            submitted_at=submitted_at or now_utc_iso(),
            edges=edges_copy,
            nodes=nodes,
            csv_text=snap_csv,
        )
        self._snapshots[level] = snapshot
        return snapshot

    def get_snapshot(self, level: int) -> LevelGraphSnapshot | None:
        """Return the immutable frozen snapshot for a level."""
        return self._snapshots.get(level)


def validate_graph_structure(
    edges: list[dict[str, Any]],
    allowed_papers: Iterable[str],
    allowed_relations: Iterable[str] | None = None,
    require_evidence: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate graph node and edge structures against released papers and relations.

    Enforces:
    - Known / released papers only
    - Valid relationship types
    - Rejection of self-loops (source_id == target_id)
    - Rejection of duplicate edges
    - Evidence reference validation when require_evidence=True
    """
    clean: list[dict[str, Any]] = []
    errors: list[str] = []
    allowed_p = {p.strip().upper() for p in allowed_papers if p}
    rel_set = set(allowed_relations) if allowed_relations is not None else set(SUBMITTABLE_RELATIONS)
    allowed_r = {r.strip().upper().replace(" ", "_") for r in rel_set if r}
    seen = set()

    for idx, e in enumerate(edges, start=1):
        s = str(e.get("source_id", "")).strip().upper()
        t = str(e.get("target_id", "")).strip().upper()
        rel = str(e.get("relationship_type", "")).strip().upper().replace(" ", "_")
        ev = str(e.get("evidence_reference", "")).strip()

        row_errs = []
        if not s or s not in allowed_p:
            row_errs.append(f"invalid or unreleased source_id {s!r}")
        if not t or t not in allowed_p:
            row_errs.append(f"invalid or unreleased target_id {t!r}")
        if s and t and s == t:
            row_errs.append("a paper cannot relate to itself (self-loop)")
        if not rel or rel not in allowed_r:
            row_errs.append(f"invalid relationship_type {rel!r}")
        if require_evidence and not ev:
            row_errs.append("missing or empty evidence_reference (a citation or page/section reference is required)")

        key = (s, t, rel)
        if s and t and rel and key in seen:
            row_errs.append(f"duplicate edge ({s} {rel} {t})")
        else:
            seen.add(key)

        if row_errs:
            errors.append(f"Edge #{idx} ({s}->{t}): " + "; ".join(row_errs))
            continue

        clean.append({
            "source_id": s,
            "target_id": t,
            "relationship_type": rel,
            "evidence_reference": ev,
            "added_at_level": int(e.get("added_at_level", 1)),
        })

    return clean, errors


def parse_and_validate_csv(
    csv_text: str,
    allowed_papers: Iterable[str],
    allowed_relations: Iterable[str] | None = None,
    allow_empty: bool = True,
    require_evidence: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse CSV text and validate all edge rows."""
    import pandas as pd

    text = str(csv_text or "").strip()
    if not text:
        if allow_empty:
            return [], []
        return [], ["Graph CSV cannot be empty."]

    try:
        df = pd.read_csv(io.StringIO(text), dtype=str).fillna("")
    except Exception as e:
        return [], [f"Malformed CSV: {e}"]

    col_map = {}
    for col in df.columns:
        c = str(col).strip().lower()
        if c in ("source_id", "source", "src"):
            col_map[col] = "source_id"
        elif c in ("target_id", "target", "dst"):
            col_map[col] = "target_id"
        elif c in ("relationship_type", "relationship", "relation", "rel"):
            col_map[col] = "relationship_type"
        elif c in ("evidence_reference", "evidence", "proof"):
            col_map[col] = "evidence_reference"
    df = df.rename(columns=col_map)

    required = ["source_id", "target_id", "relationship_type"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return [], [f"Missing required columns: {', '.join(missing)}"]

    if "evidence_reference" not in df.columns:
        df["evidence_reference"] = ""

    raw_edges = []
    for _, r in df.iterrows():
        s = str(r["source_id"]).strip()
        t = str(r["target_id"]).strip()
        rel = str(r["relationship_type"]).strip()
        ev = str(r["evidence_reference"]).strip()
        if not s and not t and not rel:
            continue  # ignore blank lines
        raw_edges.append({
            "source_id": s,
            "target_id": t,
            "relationship_type": rel,
            "evidence_reference": ev,
        })

    if not raw_edges:
        if allow_empty:
            return [], []
        return [], ["Graph CSV contains no relationship edges."]

    return validate_graph_structure(raw_edges, allowed_papers, allowed_relations, require_evidence=require_evidence)
