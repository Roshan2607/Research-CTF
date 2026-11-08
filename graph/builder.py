"""Stage 0 - build the scholarly knowledge graph (NetworkX) from structured records.

Input:  ``data/organiser/master_graph.json`` (nodes + typed edges with provenance).
Output: a :class:`networkx.MultiDiGraph` where

* node attributes are the stored record (``type``, ``title``/``label``, ...);
* each edge has ``key == relationship type`` and carries ``id``, ``status``,
  ``explanation``, ``evidence``, ``reviewer_notes``;
* symmetric relationships are stored once in canonical order and flagged
  ``symmetric=True`` - traversal helpers treat them as bidirectional.

The builder never invents edges. It only loads records that already carry
provenance; validation (``graph.validation``) is run before the graph is used.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import networkx as nx

from .schema import RELATIONS, SYMMETRIC_RELATIONS, NodeType, Status, canonical_pair

ROOT = Path(__file__).resolve().parents[1]
MASTER_GRAPH_PATH = ROOT / "data" / "organiser" / "master_graph.json"


def load_master_records(path: Path | None = None) -> dict:
    path = path or MASTER_GRAPH_PATH
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_graph(records: dict | None = None, include_statuses: Iterable[str] | None = None) -> nx.MultiDiGraph:
    """Build the master graph.

    ``include_statuses`` limits which edges are loaded (default: all). Use
    ``{"VERIFIED"}`` for the evidence-backed graph used by path discovery.
    """
    records = records if records is not None else load_master_records()
    allowed = set(include_statuses) if include_statuses is not None else None
    g = nx.MultiDiGraph(name="Uncharted Literature master graph")
    for node in records["nodes"]:
        g.add_node(node["id"], **node)
    for e in records["edges"]:
        if allowed is not None and e["status"] not in allowed:
            continue
        s, t = canonical_pair(e["source"], e["target"], e["type"])
        attrs = {k: v for k, v in e.items() if k not in ("source", "target", "type")}
        attrs["symmetric"] = e["type"] in SYMMETRIC_RELATIONS
        attrs["claim_kind"] = RELATIONS[e["type"]].claim_kind.value if e["type"] in RELATIONS else None
        g.add_edge(s, t, key=e["type"], **attrs)
    return g


def verified_graph(records: dict | None = None) -> nx.MultiDiGraph:
    return build_graph(records, include_statuses={Status.VERIFIED.value})


def papers(g: nx.MultiDiGraph) -> list[str]:
    return [n for n, d in g.nodes(data=True) if d.get("type") == NodeType.PAPER.value]


def paper_projection(g: nx.MultiDiGraph, statuses: Iterable[str] = ("VERIFIED",)) -> nx.MultiGraph:
    """Undirected multigraph over PAPER nodes only (paper-to-paper edges).

    Used for navigation / path discovery: a reader can move from a paper to a
    cited, citing, extended or analogous paper in either direction.
    """
    allowed = set(statuses)
    pg = nx.MultiGraph()
    for n in papers(g):
        pg.add_node(n, **g.nodes[n])
    for s, t, k, d in g.edges(keys=True, data=True):
        if d.get("status") not in allowed:
            continue
        if g.nodes[s].get("type") == "PAPER" and g.nodes[t].get("type") == "PAPER":
            pg.add_edge(s, t, key=f"{k}:{s}->{t}", rel=k, src=s, dst=t, **{x: y for x, y in d.items() if x not in ("rel",)})
    return pg


def concept_projection(g: nx.MultiDiGraph, statuses: Iterable[str] = ("VERIFIED",)) -> nx.Graph:
    """Undirected simple graph over all nodes, used for explainable relational search."""
    allowed = set(statuses)
    cg = nx.Graph()
    for n, d in g.nodes(data=True):
        cg.add_node(n, **d)
    for s, t, k, d in g.edges(keys=True, data=True):
        if d.get("status") not in allowed:
            continue
        if cg.has_edge(s, t):
            cg[s][t]["rels"].append(k)
            cg[s][t]["edge_ids"].append(d.get("id"))
        else:
            cg.add_edge(s, t, rels=[k], edge_ids=[d.get("id")])
    return cg


def pid_maps(g: nx.MultiDiGraph) -> tuple[dict[str, str], dict[str, str]]:
    """(internal_id -> participant_id, participant_id -> internal_id) for papers."""
    to_pid = {n: g.nodes[n]["participant_id"] for n in papers(g)}
    return to_pid, {v: k for k, v in to_pid.items()}


def edges_by_id(records: dict) -> dict[str, dict]:
    return {e["id"]: e for e in records["edges"]}
