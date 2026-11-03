"""Stage 2 - diversity-oriented alternative-path exploration.

Conceptual basis: Explore-on-Graph (Yan et al., ICLR 2026) encourages LLM agents
to explore diverse reasoning paths on knowledge graphs, with path-refined reward
modelling. This module adapts only the *diversity* idea, with no reinforcement
learning and no training:

1. **Penalised re-search.** After each accepted path, the weights of the edges it
   used are multiplied by ``reuse_penalty`` and Stage 1 is re-run, so the search is
   pushed away from the conventional route instead of re-finding it.
2. **Maximal-marginal-relevance selection.** Candidates are chosen greedily by
   ``lambda * quality - (1 - lambda) * max_similarity_to_selected``, where similarity
   is the Jaccard overlap of intermediate papers and of evidence edges.
3. **Domain-diversity bonus.** Paths that cross more distinct disciplines get a
   small bonus, because a cross-disciplinary route is the point of the workshop.

Input:  master graph, start/end papers, number of paths wanted.
Output: list of (CandidatePath, diagnostics) in selection order.
"""
from __future__ import annotations

from dataclasses import dataclass

import networkx as nx

from .builder import paper_projection
from .path_discovery import CandidatePath, discover_paths


@dataclass
class DiversePath:
    path: CandidatePath
    quality: float
    max_similarity: float
    domains: int
    mmr: float


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a or b) else 0.0


def path_similarity(p: CandidatePath, q: CandidatePath) -> float:
    inter_p, inter_q = set(p.nodes[1:-1]), set(q.nodes[1:-1])
    node_sim = _jaccard(inter_p, inter_q) if (inter_p or inter_q) else 1.0
    return 0.5 * node_sim + 0.5 * _jaccard(p.edge_ids(), q.edge_ids())


def domain_count(g: nx.MultiDiGraph, p: CandidatePath) -> int:
    return len({g.nodes[n].get("domain") for n in p.nodes})


def diverse_paths(
    g: nx.MultiDiGraph,
    start: str,
    end: str,
    k: int = 4,
    lam: float = 0.6,
    reuse_penalty: float = 0.5,
    rounds: int = 6,
    domain_bonus: float = 0.03,
    max_depth: int = 4,
) -> list[DiversePath]:
    pg = paper_projection(g)
    weights: dict[str, float] = {}
    pool: dict[tuple, CandidatePath] = {}
    for _ in range(rounds):
        found = discover_paths(g, start, end, max_depth=max_depth, edge_weights=weights, pg=pg)
        for cp in found:
            pool.setdefault(tuple(cp.nodes), cp)
        if not found:
            break
        for eid in found[0].edge_ids():
            weights[eid] = weights.get(eid, 1.0) * reuse_penalty
    # re-score the pool without penalties so quality is comparable
    base = {tuple(c.nodes): c for c in discover_paths(g, start, end, max_depth=max_depth, beam_width=200, pg=pg)}
    candidates = [base.get(key, cp) for key, cp in pool.items()]
    selected: list[DiversePath] = []
    while candidates and len(selected) < k:
        best, best_val = None, None
        for c in candidates:
            sim = max((path_similarity(c, s.path) for s in selected), default=0.0)
            dom = domain_count(g, c)
            val = lam * c.score - (1 - lam) * sim + domain_bonus * dom
            if best_val is None or val > best_val or (val == best_val and c.nodes < best.path.nodes):
                best = DiversePath(c, c.score, sim, dom, val)
                best_val = val
        selected.append(best)
        candidates = [c for c in candidates if c.nodes != best.path.nodes]
    return selected
