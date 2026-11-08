"""Organiser-side discovery pipeline: Stage 0 -> 1 & 2 -> 3 -> 4.

    Stage 0  builder.build_graph            structured, provenance-carrying records -> NetworkX
    Stage 1  path_discovery.discover_paths   conventional ranked paths (PoG-inspired pruning)
    Stage 2  alternative_paths.diverse_paths diverse alternatives (EoG-inspired exploration)
    Stage 3  relationship_explainer          explained cross-domain relations (Hyvönen-inspired)
    Stage 4  application_discovery           evidence-backed application report (only if Stage 3 is defensible)

Stages 1 and 2 both feed Stage 3 (their paths become ``paper_chain`` explanations).
Used by the organiser console and scripts/demo_walkthrough.py. Never imported by
the participant app.
"""
from __future__ import annotations

from dataclasses import dataclass

from .alternative_paths import DiversePath, diverse_paths
from .application_discovery import ApplicationReport, NotDefensibleError, build_report
from .builder import build_graph, load_master_records
from .path_discovery import CandidatePath, discover_paths
from .relationship_explainer import RelationExplanation, explain_pair
from .validation import errors, validate_records


@dataclass
class PipelineResult:
    stage1: list[CandidatePath]
    stage2: list[DiversePath]
    stage3: list[RelationExplanation]
    stage4: list[ApplicationReport]
    stage4_skipped_reason: str | None = None


def run_pipeline(start: str, end: str, final_answer: dict | None = None, k_alternatives: int = 4) -> PipelineResult:
    records = load_master_records()
    errs = errors(validate_records(records))
    if errs:
        raise ValueError(f"master graph invalid: {errs[:3]}")
    g = build_graph(records)  # all statuses loaded; stages only traverse VERIFIED edges
    s1 = discover_paths(g, start, end)
    s2 = diverse_paths(g, start, end, k=k_alternatives)
    chains = s1[:3] + [d.path for d in s2]
    s3 = explain_pair(g, start, end, chains)
    s4: list[ApplicationReport] = []
    reason = None
    candidates = [r for r in s3 if r.defensible and r.principle]
    if candidates:
        try:
            s4 = build_report(g, candidates[0], final_answer)
        except NotDefensibleError as exc:  # pragma: no cover - guarded above
            reason = str(exc)
    else:
        reason = "No defensible, principle-naming relation found in Stage 3; Stage 4 not run."
    return PipelineResult(s1, s2, s3, s4, reason)
