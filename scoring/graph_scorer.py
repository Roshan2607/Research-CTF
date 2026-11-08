"""Local graph-reconstruction scorer (source of truth; Kaggle metric mirrors it).

Workflow::

    parsed = parse_submission(csv_text, valid_ids, infos)   # validation, no answer key needed
    scorer = GraphScorer.from_answer_key()                   # server-side only
    result = scorer.score(parsed.edges)                      # organiser detail
    public = result.participant_view("public")               # aggregate numbers only

The participant-facing view contains three numbers (weighted F1, weighted
precision, recall) for one split. It never contains per-edge outcomes, counts by
class, or the reference set.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

import pandas as pd

from challenge import paths
from graph.schema import RELATIONS, SUBMITTABLE_RELATIONS, TEMPORAL_RELATIONS, edge_key

from .reference import PaperInfo, Triple, classify_universe, is_valid_candidate, paper_infos, usage_of
from .weighted_metrics import Counts, Metrics, compute

REQUIRED_COLUMNS = ("source_id", "target_id", "relationship_type")
OPTIONAL_COLUMNS = ("evidence_reference",)


@dataclass
class ParsedSubmission:
    edges: list[Triple] = field(default_factory=list)
    evidence: dict[Triple, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _read_frame(data) -> pd.DataFrame:
    if isinstance(data, pd.DataFrame):
        return data.copy()
    if isinstance(data, bytes):
        data = data.decode("utf-8-sig", errors="replace")
    if isinstance(data, str):
        if not data.strip():
            return pd.DataFrame(columns=list(REQUIRED_COLUMNS))
        return pd.read_csv(io.StringIO(data), dtype=str, keep_default_na=False)
    raise TypeError("submission must be CSV text, bytes or a DataFrame")


def parse_submission(data, infos: dict[str, PaperInfo], max_rows: int = 300, allow_any_pair: bool = False) -> ParsedSubmission:
    """Validate a participant edge list. Does not use the answer key."""
    out = ParsedSubmission()
    try:
        df = _read_frame(data)
    except (pd.errors.ParserError, UnicodeDecodeError, csv.Error, ValueError) as exc:
        out.errors.append(f"Malformed CSV: {exc}")
        return out
    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        out.errors.append(f"Missing required column(s): {', '.join(missing)}. Expected: {', '.join(REQUIRED_COLUMNS)}")
        return out
    extra = [c for c in df.columns if c not in REQUIRED_COLUMNS + OPTIONAL_COLUMNS]
    if extra:
        out.warnings.append(f"Ignored unknown column(s): {', '.join(extra)}")
    if len(df) > max_rows:
        out.errors.append(f"Too many rows ({len(df)}); the limit is {max_rows}.")
        return out
    seen: dict[Triple, int] = {}
    for i, row in enumerate(df.fillna("").to_dict("records"), start=2):  # line numbers incl. header
        s = str(row.get("source_id", "")).strip().upper()
        t = str(row.get("target_id", "")).strip().upper()
        rel = str(row.get("relationship_type", "")).strip().upper().replace(" ", "_")
        ev = str(row.get("evidence_reference", "") or "").strip()
        if not s and not t and not rel:
            continue  # blank line
        row_errs = []
        if s not in infos:
            row_errs.append(f"unknown source_id {s!r}")
        if t not in infos:
            row_errs.append(f"unknown target_id {t!r}")
        if rel not in RELATIONS:
            row_errs.append(f"invalid relationship_type {rel!r}")
        elif rel not in SUBMITTABLE_RELATIONS:
            row_errs.append(f"{rel} cannot be submitted in a graph submission (paper-to-paper relationships only)")
        if not row_errs:
            if s == t:
                row_errs.append("a paper cannot relate to itself")
        if not allow_any_pair and not row_errs and rel in TEMPORAL_RELATIONS and not is_valid_candidate(s, t, rel, infos):
            row_errs.append(f"invalid direction: {s} ({infos[s].year}) cannot {rel} {t} (first public {infos[t].first_public_year}). Directed relations go from the newer / using paper to the older / used paper.")
        if row_errs:
            out.errors.append(f"line {i}: " + "; ".join(row_errs))
            continue
        key = edge_key(s, t, rel)
        if key in seen:
            out.warnings.append(f"line {i}: duplicate of line {seen[key]} ({key[0]} {key[2]} {key[1]}); counted once")
            if ev and not out.evidence.get(key):
                out.evidence[key] = ev
            continue
        seen[key] = i
        out.edges.append(key)
        if ev:
            out.evidence[key] = ev
    return out


@dataclass
class ScoreResult:
    counts: dict[str, Counts]
    metrics: dict[str, Metrics]
    per_edge_class: dict[Triple, str]
    n_submitted: int

    def participant_view(self, split: str = "public") -> dict:
        m = self.metrics[split]
        return {
            "split": split,
            "weighted_f1": round(m.weighted_f1, 4),
            "weighted_precision": round(m.weighted_precision, 4),
            "recall": round(m.recall, 4),
            "edges_scored": self.n_submitted,
        }

    def organiser_view(self) -> dict:
        return {
            split: {**self.metrics[split].as_dict(), **self.counts[split].__dict__}
            for split in self.metrics
        }


class GraphScorer:
    """Scores submitted edges against the organiser's classified candidate universe."""

    def __init__(self, classes: dict[Triple, str], config: dict, infos: dict[str, PaperInfo]):
        self.classes = classes
        self.config = config
        self.infos = infos
        self.weights = config["fp_weights"]
        self.usage = {t: usage_of(t, config) for t in classes}
        self.reference = {t for t, c in classes.items() if c == "reference"}

    @classmethod
    def from_answer_key(cls, accepted_additions: list[Triple] | None = None, config: dict | None = None) -> "GraphScorer":
        records = paths.read_json(paths.MASTER_GRAPH)
        config = config or paths.load_config()
        classes = classify_universe(
            records,
            paths.read_json(paths.SCORING_POLICY),
            paths.read_json(paths.DECOYS),
            paths.read_json(paths.INJECTIONS),
            config,
            accepted_additions,
        )
        return cls(classes, config, paper_infos(records))

    def classify(self, t: Triple) -> str:
        return self.classes.get(edge_key(*t), "ordinary")

    def score(self, edges: list[Triple]) -> ScoreResult:
        submitted = {edge_key(*e) for e in edges}
        per_edge = {e: self.classify(e) for e in submitted}
        counts, metrics = {}, {}
        for split in ("public", "private", "all"):
            want = None if split == "all" else split.capitalize()
            in_split = lambda t: want is None or self.usage.get(t, "Private") == want  # noqa: E731
            sub = [e for e in submitted if in_split(e)]
            ref = [t for t in self.reference if in_split(t)]
            tp = sum(1 for e in sub if per_edge[e] == "reference")
            c = Counts(
                tp=tp,
                fn=len(ref) - tp,
                fp_ordinary=sum(1 for e in sub if per_edge[e] == "ordinary"),
                fp_decoy=sum(1 for e in sub if per_edge[e] == "decoy_induced"),
                fp_injection=sum(1 for e in sub if per_edge[e] == "injection_induced"),
                neutral=sum(1 for e in sub if per_edge[e] == "neutral"),
            )
            counts[split] = c
            metrics[split] = compute(c, self.weights)
        return ScoreResult(counts, metrics, per_edge, len(submitted))


def score_csv(data, accepted_additions=None, allow_any_pair: bool = False) -> tuple[ParsedSubmission, ScoreResult | None]:
    """Convenience: parse + score a CSV with the live answer key (organiser / CLI use)."""
    scorer = GraphScorer.from_answer_key(accepted_additions)
    parsed = parse_submission(data, scorer.infos, scorer.config["graph_submission"]["max_rows"], allow_any_pair=allow_any_pair)
    if not parsed.ok:
        return parsed, None
    return parsed, scorer.score(parsed.edges)


if __name__ == "__main__":  # pragma: no cover
    import json
    import sys

    p, r = score_csv(open(sys.argv[1], encoding="utf-8").read())
    print("errors:", p.errors, "warnings:", p.warnings)
    if r:
        print(json.dumps(r.organiser_view(), indent=2))
