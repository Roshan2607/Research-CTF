"""Stage 1 - conventional path discovery between papers.

Conceptual basis: Paths-over-Graph (Tan et al., WWW 2025) explores candidate
reasoning paths through a knowledge graph and prunes irrelevant or weak ones.
This module adapts only that idea. It is NOT a reproduction of PoG (no LLM-guided
question decomposition, no LLM path pruning).

Algorithm (deterministic, explainable):

* Graph: undirected projection over PAPER nodes using VERIFIED paper-to-paper
  edges only (a reader can follow a citation in either direction).
* Transition quality: the best claim-kind weight among the parallel edges between
  two papers (methodological > conceptual > interpretive > bibliographic), plus a
  small bonus when several independent kinds of evidence agree.
* Relevance pruning: an intermediate paper must share at least one problem,
  method or principle with the start or end paper (concept overlap in the master
  graph); otherwise the branch is pruned as off-topic.
* Beam search to ``max_depth`` transitions, keeping the ``beam_width`` best
  partial paths per depth. Path score = mean transition quality x length decay.

Input:  master graph (NetworkX), start and end paper IDs.
Output: ranked :class:`CandidatePath` objects with per-transition evidence edge IDs.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from .builder import paper_projection

CLAIM_WEIGHTS = {"methodological": 1.0, "conceptual": 0.9, "interpretive": 0.8, "bibliographic": 0.5}
MULTI_EVIDENCE_BONUS = 0.1
LENGTH_DECAY = 0.9


@dataclass
class Transition:
    source: str
    target: str
    relations: list[str]
    edge_ids: list[str]
    quality: float


@dataclass
class CandidatePath:
    nodes: list[str]
    transitions: list[Transition] = field(default_factory=list)
    score: float = 0.0

    @property
    def length(self) -> int:
        return len(self.nodes) - 1

    def edge_ids(self) -> set[str]:
        return {eid for t in self.transitions for eid in t.edge_ids}

    def describe(self, g: nx.MultiDiGraph | None = None) -> str:
        label = (lambda n: g.nodes[n].get("participant_id", n)) if g is not None else (lambda n: n)
        hops = []
        for t in self.transitions:
            hops.append(f"{label(t.source)} -[{'/'.join(sorted(set(t.relations)))}]- {label(t.target)}")
        return f"score={self.score:.3f}: " + "  ".join(hops)


def concept_profile(g: nx.MultiDiGraph, paper: str) -> set[str]:
    """Problems, methods and principles (via methods) attached to a paper."""
    prof: set[str] = set()
    for _, t, k, d in g.out_edges(paper, keys=True, data=True):
        if d.get("status") != "VERIFIED":
            continue
        if k in ("ADDRESSES", "USES_METHOD", "EMBODIES_PRINCIPLE") and g.nodes[t].get("type") != "PAPER":
            prof.add(t)
            if k == "USES_METHOD":
                for _, p, k2, d2 in g.out_edges(t, keys=True, data=True):
                    if k2 == "EMBODIES_PRINCIPLE" and d2.get("status") == "VERIFIED":
                        prof.add(p)
    return prof


def transition_quality(pg: nx.MultiGraph, a: str, b: str, edge_weights: dict[str, float] | None = None) -> Transition | None:
    data = pg.get_edge_data(a, b)
    if not data:
        return None
    kinds, rels, ids = set(), [], []
    best = 0.0
    for d in data.values():
        w = CLAIM_WEIGHTS.get(d.get("claim_kind"), 0.3)
        if edge_weights and d.get("id") in edge_weights:
            w *= edge_weights[d["id"]]
        best = max(best, w)
        kinds.add(d.get("claim_kind"))
        rels.append(d["rel"])
        ids.append(d.get("id"))
    q = min(1.0, best + MULTI_EVIDENCE_BONUS * (len(kinds) - 1))
    return Transition(a, b, rels, ids, q)


def _score(transitions: list[Transition]) -> float:
    if not transitions:
        return 0.0
    mean_q = sum(t.quality for t in transitions) / len(transitions)
    return mean_q * (LENGTH_DECAY ** (len(transitions) - 1))


def discover_paths(
    g: nx.MultiDiGraph,
    start: str,
    end: str,
    max_depth: int = 4,
    beam_width: int = 25,
    relevance_pruning: bool = True,
    edge_weights: dict[str, float] | None = None,
    pg: nx.MultiGraph | None = None,
) -> list[CandidatePath]:
    """Beam search for paper-to-paper paths from ``start`` to ``end``."""
    pg = pg if pg is not None else paper_projection(g)
    if start not in pg or end not in pg:
        raise KeyError("start/end must be paper nodes")
    anchor = concept_profile(g, start) | concept_profile(g, end)
    profiles = {n: concept_profile(g, n) for n in pg.nodes}

    def relevant(n: str) -> bool:
        return n == end or not relevance_pruning or bool(profiles[n] & anchor)

    beam = [CandidatePath([start])]
    found: list[CandidatePath] = []
    for _depth in range(max_depth):
        expansions: list[CandidatePath] = []
        for cp in beam:
            last = cp.nodes[-1]
            for nb in pg.neighbors(last):
                if nb in cp.nodes or not relevant(nb):
                    continue
                tr = transition_quality(pg, last, nb, edge_weights)
                if tr is None:
                    continue
                new = CandidatePath(cp.nodes + [nb], cp.transitions + [tr])
                new.score = _score(new.transitions)
                (found if nb == end else expansions).append(new)
        expansions.sort(key=lambda c: (-c.score, c.nodes))
        beam = expansions[:beam_width]
        if not beam:
            break
    found.sort(key=lambda c: (-c.score, c.length, c.nodes))
    return found


def reachable_papers(g: nx.MultiDiGraph, start: str, max_depth: int = 3) -> dict[str, int]:
    """Exploration from a base paper when the destination is unknown: paper -> hop distance."""
    pg = paper_projection(g)
    return dict(nx.single_source_shortest_path_length(pg, start, cutoff=max_depth))


def path_exists(g: nx.MultiDiGraph, nodes: list[str]) -> bool:
    pg = paper_projection(g)
    return all(pg.has_edge(a, b) for a, b in zip(nodes, nodes[1:]))
