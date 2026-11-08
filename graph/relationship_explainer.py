"""Stage 3 - serendipitous, explainable relationship discovery.

Conceptual basis: Hyvönen (2025), *Serendipitous Knowledge Discovery on the Web of
Wisdom Based on Searching and Explaining Interesting Relations in Knowledge Graphs*,
J. Web Semantics - explainable relational search: find interesting, possibly
unexpected relations between entities and explain them. This module adapts that
idea to research papers. It is NOT an autonomous scientific-transfer or
product-discovery system.

Given two papers (or a paper and every other paper), it searches the concept
graph for connecting patterns:

* ``shared_principle``: A -USES_METHOD-> M1 -EMBODIES-> P <-EMBODIES- M2 <-USES_METHOD- B
* ``shared_method``:    A -USES_METHOD-> M <-USES_METHOD- B
* ``shared_problem``:   A -ADDRESSES-> X <-ADDRESSES- B
* ``paper_chain``:      paths from Stages 1/2 (supplied by the caller)

Each explanation is scored for *interestingness* (higher when the papers are in
different domains, have no direct edge, and connect through a rare - low-degree -
concept) and carries the evidence records of every edge it uses.

Status rules (an AI/algorithm-generated relation is never auto-verified):

* ``VERIFIED``    - a VERIFIED direct master-graph edge already states the relation.
* ``AI_PROPOSED`` - otherwise. It is a speculative, *explained* relation, and it is
  ``defensible`` only when every supporting edge is VERIFIED. Promotion needs a
  human via ``graph.validation.promote_edge``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import networkx as nx

from .path_discovery import CandidatePath


@dataclass
class RelationExplanation:
    a: str
    b: str
    pattern: str
    via: list[str]
    relation_type: str
    explanation: str
    interestingness: float
    cross_domain: bool
    direct_edge: bool
    status: str
    defensible: bool
    principle: str | None = None
    evidence: list[dict] = field(default_factory=list)
    supporting_edge_ids: list[str] = field(default_factory=list)


def _edges(g, u, rel):
    return [(t, d) for _, t, k, d in g.out_edges(u, keys=True, data=True) if k == rel and d.get("status") == "VERIFIED"]


def _label(g, n):
    d = g.nodes[n]
    if d.get("type") == "PAPER":
        return f"{d.get('participant_id')} ({d['authors'][0].split()[-1]} {d['year']})"
    return d.get("label", n)


def _direct(g, a, b) -> list[tuple[str, dict]]:
    out = []
    for u, v in ((a, b), (b, a)):
        if g.has_edge(u, v):
            for k, d in g.get_edge_data(u, v).items():
                if d.get("status") == "VERIFIED":
                    out.append((k, d))
    return out


def _rarity(g, concept) -> float:
    deg = g.in_degree(concept) + g.out_degree(concept)
    return 1.0 / math.log(2 + deg)


def explain_pair(g: nx.MultiDiGraph, a: str, b: str, chains: list[CandidatePath] | None = None) -> list[RelationExplanation]:
    out: list[RelationExplanation] = []
    da, db = g.nodes[a].get("domain"), g.nodes[b].get("domain")
    cross = da != db
    direct = _direct(g, a, b)
    direct_types = {k for k, _ in direct}

    def make(pattern, via, rel, text, edges_used, principle=None):
        evid = [ev for _, d in edges_used for ev in d.get("evidence", [])]
        ids = [d.get("id") for _, d in edges_used]
        rarity = max((_rarity(g, v) for v in via if g.nodes[v].get("type") != "PAPER"), default=0.5)
        score = (1.0 if cross else 0.4) * (0.6 if direct else 1.0) * rarity * (1 + 0.1 * min(len(evid), 5))
        status = "VERIFIED" if rel in direct_types else "AI_PROPOSED"
        defensible = all(d.get("status") == "VERIFIED" for _, d in edges_used) and len(evid) >= 2
        out.append(RelationExplanation(a, b, pattern, via, rel, text, round(score, 4), cross, bool(direct), status, defensible, principle, evid, ids))

    # shared principle via methods (or directly embodied)
    def principles(p):
        res = {}
        for m, d in _edges(g, p, "USES_METHOD"):
            if g.nodes[m].get("type") != "METHOD":
                continue
            for pr, d2 in _edges(g, m, "EMBODIES_PRINCIPLE"):
                res.setdefault(pr, []).append((m, d, d2))
        for pr, d in _edges(g, p, "EMBODIES_PRINCIPLE"):
            res.setdefault(pr, []).append((None, None, d))
        return res

    pa, pb = principles(a), principles(b)
    for pr in sorted(set(pa) & set(pb)):
        ma, da_, da2 = pa[pr][0]
        mb, db_, db2 = pb[pr][0]
        used = [(None, x) for x in (da_, da2, db_, db2) if x is not None]
        via = [x for x in (ma, pr, mb) if x]
        text = (
            f"{_label(g, a)} and {_label(g, b)} both rely on the principle — {g.nodes[pr]['label']} "
            f"[{_label(g, a).split()[0]} via '{g.nodes[ma]['label'] if ma else 'its overall approach'}'; "
            f"{_label(g, b).split()[0]} via '{g.nodes[mb]['label'] if mb else 'its overall approach'}']"
        )
        make("shared_principle", via, "SHARES_PRINCIPLE", text, used, principle=pr)

    ma = {m: d for m, d in _edges(g, a, "USES_METHOD") if g.nodes[m].get("type") == "METHOD"}
    mb = {m: d for m, d in _edges(g, b, "USES_METHOD") if g.nodes[m].get("type") == "METHOD"}
    for m in sorted(set(ma) & set(mb)):
        make("shared_method", [m], "SHARES_PRINCIPLE",
             f"Both {_label(g, a)} and {_label(g, b)} use the method '{g.nodes[m]['label']}'.", [(None, ma[m]), (None, mb[m])])

    xa = {x: d for x, d in _edges(g, a, "ADDRESSES")}
    xb = {x: d for x, d in _edges(g, b, "ADDRESSES")}
    for x in sorted(set(xa) & set(xb)):
        make("shared_problem", [x], "ANALOGOUS_PROBLEM",
             f"{_label(g, a)} and {_label(g, b)} address the same abstract problem: {g.nodes[x]['label']}.", [(None, xa[x]), (None, xb[x])])

    for cp in chains or []:
        if cp.nodes[0] == a and cp.nodes[-1] == b:
            used = []
            for t in cp.transitions:
                for eid in t.edge_ids:
                    for u, v, k, d in g.edges(keys=True, data=True):
                        if d.get("id") == eid:
                            used.append((k, d))
            hops = " -> ".join(_label(g, n) for n in cp.nodes)
            make("paper_chain", cp.nodes[1:-1], "SHARES_PRINCIPLE", f"Evidence chain through the literature: {hops}.", used)
    out.sort(key=lambda r: (-r.interestingness, r.pattern))
    return out


def interesting_relations(g: nx.MultiDiGraph, a: str, top: int = 10, cross_domain_only: bool = True) -> list[RelationExplanation]:
    """Rank the most interesting explained relations from paper ``a`` to every other paper."""
    res = []
    for b, d in g.nodes(data=True):
        if b == a or d.get("type") != "PAPER":
            continue
        if cross_domain_only and d.get("domain") == g.nodes[a].get("domain"):
            continue
        res.extend(explain_pair(g, a, b))
    res.sort(key=lambda r: (-r.interestingness, r.b))
    return res[:top]


def as_proposed_edge(r: RelationExplanation, g: nx.MultiDiGraph) -> dict:
    """Turn an explanation into an edge record that can enter the review queue (never VERIFIED)."""
    return {
        "source": r.a,
        "target": r.b,
        "type": r.relation_type,
        "explanation": r.explanation,
        "evidence": r.evidence,
        "status": "AI_PROPOSED" if r.status != "VERIFIED" else "VERIFIED",
        "proposed_by": "ai",
        "reviewer_notes": f"Stage 3 pattern={r.pattern}; via={r.via}; defensible={r.defensible}",
    }
