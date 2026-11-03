"""Organiser: build every derived challenge artefact from the master data.

Steps (each is idempotent):

1. validate the master graph (abort on any error);
2. check the answer key is consistent with the graph (canonical/alternative paths exist,
   decoy and injection edges are not reference edges, hidden pair absent from graph);
3. write the participant-safe package (data/participant/*.json);
4. write the classified scoring reference (data/answer_key/scoring_reference.json);
5. write Kaggle files (kaggle/candidate_edges.csv, kaggle/sample_submission.csv and
   the private data/answer_key/kaggle_solution.csv);
6. write the HMAC flag registry (needs FLAG_HMAC_SECRET; skipped with a warning otherwise);
7. render participant challenge cards (PDF wrappers with the synthetic annotation layer).

Usage:  python scripts/build_challenge.py [--skip-cards]
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from challenge import paths  # noqa: E402
from challenge.participant_data import build_participant_package, write_participant_package  # noqa: E402
from graph.builder import build_graph  # noqa: E402
from graph.validation import errors, validate_records  # noqa: E402
from scoring.reference import build_reference_table  # noqa: E402


def check_answer_key(records: dict) -> list[str]:
    probs: list[str] = []
    g = build_graph(records, include_statuses={"VERIFIED"})
    canon = paths.read_json(paths.CANONICAL_PATH)
    alts = paths.read_json(paths.ALTERNATIVE_PATHS)
    for label, spec in [("canonical", canon)] + [(a["id"], a) for a in alts["paths"]]:
        edges = spec.get("supporting_edges") or [e for tr in spec["transitions"] for e in tr["supporting_edges"]]
        for s, t, rel in edges:
            from graph.schema import canonical_pair

            cs, ct = canonical_pair(s, t, rel)
            if not g.has_edge(cs, ct, key=rel):
                probs.append(f"{label}: supporting edge {s} {rel} {t} is not a VERIFIED master-graph edge")
        hops = spec["path"]
        for a, b in zip(hops, hops[1:]):
            if not (g.has_edge(a, b) or g.has_edge(b, a)):
                probs.append(f"{label}: no verified edge between {a} and {b}")
    fa = paths.read_json(paths.FINAL_ANSWER)
    hid = {fa["hidden_connection"]["source"], fa["hidden_connection"]["target"]}
    for e in records["edges"]:
        if {e["source"], e["target"]} == hid:
            probs.append(f"hidden base-target pair appears as master-graph edge {e['id']}")
    if canon["base"]["participant_id"] != fa["base_participant_id"] or canon["target"]["participant_id"] != fa["target_participant_id"]:
        probs.append("canonical_path.json and final_answer.json disagree on base/target")
    return probs


def write_kaggle(rows: list[dict]) -> None:
    paths.KAGGLE_DIR.mkdir(exist_ok=True)
    with (paths.KAGGLE_DIR / "candidate_edges.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "source_id", "target_id", "relationship_type"])
        for r in rows:
            w.writerow([r["id"], r["source_id"], r["target_id"], r["relationship_type"]])
    with (paths.KAGGLE_DIR / "sample_submission.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "predicted"])
        for r in rows:
            w.writerow([r["id"], 0])
    with paths.KAGGLE_SOLUTION.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "label", "fp_weight", "Usage"])
        for r in rows:
            w.writerow([r["id"], r["label"], r["fp_weight"], r["Usage"]])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-cards", action="store_true")
    args = ap.parse_args(argv)
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:  # pragma: no cover
        pass

    records = paths.read_json(paths.MASTER_GRAPH)
    errs = errors(validate_records(records))
    if errs:
        for e in errs:
            print("GRAPH ERROR:", e)
        return 1
    print(f"[1] master graph valid: {len(records['nodes'])} nodes, {len(records['edges'])} edges")

    probs = check_answer_key(records)
    if probs:
        for p in probs:
            print("ANSWER KEY ERROR:", p)
        return 1
    print("[2] answer key consistent with master graph")

    config = paths.load_config()
    fa = paths.read_json(paths.FINAL_ANSWER)
    write_participant_package(build_participant_package(records, fa, config))
    print("[3] participant package written to", paths.PARTICIPANT_DIR.relative_to(ROOT))

    from challenge.submission_store import SubmissionStore

    accepted = SubmissionStore().accepted_additions()
    rows = build_reference_table(
        records,
        paths.read_json(paths.SCORING_POLICY),
        paths.read_json(paths.DECOYS),
        paths.read_json(paths.INJECTIONS),
        config,
        accepted,
    )
    paths.write_json(paths.SCORING_REFERENCE, {"_comment": "ORGANISER ONLY - generated by scripts/build_challenge.py", "rows": rows})
    n_ref = sum(r["label"] for r in rows)
    print(f"[4] scoring reference: {len(rows)} candidate edges, {n_ref} reference ({len(accepted)} accepted additions)")

    write_kaggle(rows)
    print("[5] Kaggle files written (kaggle/candidate_edges.csv, kaggle/sample_submission.csv, private solution)")

    try:
        from scoring.flag_validator import build_flag_registry
    except ImportError:
        build_flag_registry = None
    if build_flag_registry is None:
        print("[6] flag validator not available yet - skipped")
    elif not os.environ.get("FLAG_HMAC_SECRET") or os.environ.get("FLAG_HMAC_SECRET") == "change-me":
        print("[6] WARNING: FLAG_HMAC_SECRET not set - flag registry NOT written. Set it in .env and re-run.")
    else:
        paths.write_json(paths.FLAG_REGISTRY, build_flag_registry(fa, os.environ["FLAG_HMAC_SECRET"]))
        print("[6] HMAC flag registry written")

    if args.skip_cards:
        print("[7] cards skipped")
    else:
        try:
            from challenge.cards import render_all_cards
        except ImportError:
            render_all_cards = None
        if render_all_cards is None:
            print("[7] card renderer not available yet - skipped")
        else:
            out = render_all_cards()
            print(f"[7] rendered {len(out)} challenge cards to {paths.CARDS_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
