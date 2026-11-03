"""Convert a participant edge list into Kaggle's row-aligned submission format.

    python -m scoring.kaggle_format my_edges.csv kaggle_submission.csv

Input:  CSV with source_id, target_id, relationship_type[, evidence_reference]
Output: CSV with id, predicted (1 for submitted edges, 0 otherwise) over every id in
        kaggle/candidate_edges.csv. Uses only public files - no answer key.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from graph.schema import edge_key

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "kaggle" / "candidate_edges.csv"


def load_candidates(path: Path | None = None) -> pd.DataFrame:
    return pd.read_csv(path or CANDIDATES, dtype=str)


def edges_to_kaggle(edges: list[tuple[str, str, str]], candidates: pd.DataFrame | None = None) -> tuple[pd.DataFrame, list]:
    cand = candidates if candidates is not None else load_candidates()
    index = {(r.source_id, r.target_id, r.relationship_type): r.id for r in cand.itertuples()}
    wanted = {edge_key(*e) for e in edges}
    unknown = sorted(e for e in wanted if e not in index)
    ids = {index[e] for e in wanted if e in index}
    out = pd.DataFrame({"id": cand["id"], "predicted": cand["id"].isin(ids).astype(int)})
    return out, unknown


def kaggle_to_edges(sub: pd.DataFrame, candidates: pd.DataFrame | None = None) -> list[tuple[str, str, str]]:
    cand = candidates if candidates is not None else load_candidates()
    on = set(sub.loc[sub["predicted"].astype(int) == 1, "id"])
    return [(r.source_id, r.target_id, r.relationship_type) for r in cand.itertuples() if r.id in on]


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 2:
        print(__doc__)
        return 2
    from challenge.participant_data import participant_infos
    from scoring.graph_scorer import parse_submission

    cand = load_candidates()
    infos = participant_infos()  # direction/ID validation uses only public metadata
    parsed = parse_submission(Path(argv[0]).read_text(encoding="utf-8"), infos)
    for w in parsed.warnings:
        print("warning:", w)
    if not parsed.ok:
        for e in parsed.errors:
            print("error:", e)
        return 1
    out, unknown = edges_to_kaggle(parsed.edges, cand)
    for u in unknown:
        print("warning: not in the candidate universe (ignored):", u)
    out.to_csv(argv[1], index=False, lineterminator="\n")
    print(f"wrote {argv[1]}: {int(out['predicted'].sum())} edges marked")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
