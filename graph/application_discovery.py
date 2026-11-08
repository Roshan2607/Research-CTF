"""Stage 4 - real-world application discovery (runs only after Stage 3).

Given a *defensible* explained relation (Stage 3) that names a shared principle,
look up applications in the master graph that OPERATIONALISE that principle and
assemble a four-part, evidence-backed report:

1. the shared principle;
2. how the research papers demonstrate or use it (with evidence);
3. how the application implements it (with evidence);
4. limitations / differences between the research and the product, including an
   explicit statement about historical lineage (never assumed).

The application records themselves come from organiser research (official
documentation, peer-reviewed system papers). Live web search for new candidate
applications is out of scope for this proof-of-concept: :class:`ApplicationSearch`
defines the interface and :class:`NoExternalSearch` is the stub in use.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import networkx as nx

from .relationship_explainer import RelationExplanation


class NotDefensibleError(ValueError):
    pass


@dataclass
class ApplicationReport:
    principle: str
    principle_statement: str
    research_usage: list[dict]
    application: str
    application_label: str
    implementation: list[dict]
    limitations: list[str]
    lineage_claim: str = "none"
    sources: list[str] = field(default_factory=list)


class ApplicationSearch(Protocol):
    def candidates(self, principle_statement: str) -> list[dict]:  # pragma: no cover - interface
        """Return candidate applications as {'name', 'url', 'claim'} for organiser review (AI_PROPOSED)."""


class NoExternalSearch:
    """Stub: no external search in the PoC. Documented limitation."""

    def candidates(self, principle_statement: str) -> list[dict]:
        return []


def applications_for_principle(g: nx.MultiDiGraph, principle: str) -> list[str]:
    return sorted(
        u for u, v, k, d in g.edges(keys=True, data=True)
        if v == principle and k == "OPERATIONALISES" and d.get("status") == "VERIFIED"
    )


def research_usage(g: nx.MultiDiGraph, principle: str) -> list[dict]:
    rows = []
    for paper, pd_ in g.nodes(data=True):
        if pd_.get("type") != "PAPER":
            continue
        for _, m, k, d in g.out_edges(paper, keys=True, data=True):
            if k != "USES_METHOD" or d.get("status") != "VERIFIED" or g.nodes[m].get("type") != "METHOD":
                continue
            if g.has_edge(m, principle, key="EMBODIES_PRINCIPLE"):
                emb = g.get_edge_data(m, principle)["EMBODIES_PRINCIPLE"]
                rows.append(
                    {
                        "paper": paper,
                        "participant_id": pd_["participant_id"],
                        "method": g.nodes[m]["label"],
                        "how": emb["explanation"],
                        "evidence": emb.get("evidence", []),
                        "reviewer_notes": emb.get("reviewer_notes", ""),
                    }
                )
    return sorted(rows, key=lambda r: r["participant_id"])


def build_report(
    g: nx.MultiDiGraph,
    relation: RelationExplanation,
    final_answer: dict | None = None,
    search: ApplicationSearch | None = None,
) -> list[ApplicationReport]:
    if not relation.defensible or not relation.principle:
        raise NotDefensibleError(
            "Stage 4 requires a defensible relation (all supporting edges VERIFIED, >=2 evidence records) that names a principle."
        )
    pr = relation.principle
    reports = []
    usage = research_usage(g, pr)
    for app in applications_for_principle(g, pr):
        impl = []
        for _, tgt, k, d in g.out_edges(app, keys=True, data=True):
            if d.get("status") == "VERIFIED" and k in ("OPERATIONALISES", "APPLICATION_OF"):
                impl.append({"relation": k, "to": g.nodes[tgt].get("label", tgt), "how": d["explanation"], "evidence": d.get("evidence", []),
                             "notes": d.get("reviewer_notes", "")})
        limits = [i["notes"] for i in impl if i["notes"]]
        lineage = "none"
        if final_answer and final_answer.get("application", {}).get("operationalises") == pr:
            limits = final_answer["application"].get("limitations_and_differences", limits)
            lineage = final_answer["application"].get("lineage_claim", "none")
        limits = list(dict.fromkeys(limits + [u["reviewer_notes"] for u in usage if u["reviewer_notes"]]))
        reports.append(
            ApplicationReport(
                principle=pr,
                principle_statement=g.nodes[pr]["label"],
                research_usage=usage,
                application=app,
                application_label=g.nodes[app]["label"],
                implementation=impl,
                limitations=limits,
                lineage_claim=lineage,
                sources=g.nodes[app].get("evidence_urls", []),
            )
        )
    for cand in (search or NoExternalSearch()).candidates(g.nodes[pr]["label"]):
        reports.append(ApplicationReport(pr, g.nodes[pr]["label"], usage, cand["name"], cand["name"] + " (AI_PROPOSED, unreviewed)",
                                         [{"relation": "OPERATIONALISES", "how": cand.get("claim", ""), "evidence": [{"doi_or_url": cand.get("url")}]}],
                                         ["Unreviewed external candidate"], "unknown"))
    return reports
