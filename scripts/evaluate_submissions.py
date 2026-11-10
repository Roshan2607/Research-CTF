"""Submission Evaluation & Dynamic Discovery Tool for Research-CTF.

Implements the official scoring formula:
    Graph Points = Max Level Points * (Correct Edges Found / Total Reference Edges)
                   - Injection Penalty - Decoy Penalty + Discovery Bounty

Features:
- Single submission evaluation (flag + graph CSV).
- Google Form response batch grading (exports leaderboard and summary).
- Dynamic Graph Discovery Bounty: rewards teams finding novel legitimate connections
  and dynamically accepts them into the reference set.
- Detection and auditing of AI prompt injection trap hits (INJ-1, INJ-2).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Add project root to sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import event_core as core
from challenge import paths
from graph.schema import edge_key
from scoring.graph_scorer import GraphScorer, parse_submission


@dataclass
class EvaluationDetail:
    team_id: str
    level: int
    flag_submitted: str
    flag_correct: bool
    flag_points: float
    max_flag_points: float
    correct_edges: list[tuple[str, str, str]] = field(default_factory=list)
    total_reference_count: int = 0
    base_graph_points: float = 0.0
    injection_hits: list[dict[str, Any]] = field(default_factory=list)
    injection_penalty: float = 0.0
    decoy_hits: list[tuple[str, str, str]] = field(default_factory=list)
    decoy_penalty: float = 0.0
    discovery_bounty_edges: list[tuple[str, str, str]] = field(default_factory=list)
    discovery_bounty_points: float = 0.0
    final_graph_points: float = 0.0
    max_graph_points: float = 0.0
    total_score: float = 0.0
    max_total_score: float = 0.0
    novel_candidate_edges: list[dict[str, str]] = field(default_factory=list)
    explanation: str = ""

    def summary_row(self) -> dict[str, Any]:
        return {
            "Team ID": self.team_id,
            "Level": self.level,
            "Flag Solved": "YES" if self.flag_correct else "NO",
            "Flag Points": round(self.flag_points, 1),
            "Correct Edges": f"{len(self.correct_edges)}/{self.total_reference_count}",
            "Base Graph Pts": round(self.base_graph_points, 1),
            "Injection Trap Hits": len(self.injection_hits),
            "Injection Penalty": round(self.injection_penalty, 1),
            "Decoy Penalty": round(self.decoy_penalty, 1),
            "Discovery Bounty": round(self.discovery_bounty_points, 1),
            "Final Graph Pts": round(self.final_graph_points, 1),
            "Total Score": round(self.total_score, 1),
            "Max Available": round(self.max_total_score, 1),
        }


def load_accepted_additions(file_or_list: str | list | None) -> list[tuple[str, str, str]]:
    if not file_or_list:
        return []
    edges = []
    if isinstance(file_or_list, list):
        for item in file_or_list:
            if isinstance(item, (list, tuple)) and len(item) == 3:
                s, t, rel = str(item[0]).strip().upper(), str(item[1]).strip().upper(), str(item[2]).strip().upper()
                edges.append(edge_key(s, t, rel))
        return edges
    path = Path(file_or_list)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return load_accepted_additions(data)
        elif isinstance(data, dict) and "accepted_additions" in data:
            return load_accepted_additions(data["accepted_additions"])
    return []


def evaluate_submission(
    team_id: str,
    level: int,
    flag_answer: str,
    graph_csv: str,
    explanation: str = "",
    cluster: str = core.CLUSTER,
    accepted_additions: list[tuple[str, str, str]] | None = None,
    injection_penalty_pts: float = 300.0,
    decoy_penalty_pts: float = 100.0,
    discovery_bounty_pts: float = 250.0,
) -> EvaluationDetail:
    """Evaluates a single level submission using the official formula:

    Graph Points = Max Level Points * (Correct Edges / Total Reference)
                   - Injection Penalty - Decoy Penalty + Discovery Bounty
    """
    lvl_pts = core.level_points(level)
    max_fp = float(lvl_pts["flag"])
    max_gp = float(lvl_pts["graph"])
    total_max = float(lvl_pts["total"])

    # 1. Flag Evaluation
    cleaned_flag = str(flag_answer or "").strip()
    flag_correct = False
    flag_points = 0.0

    if level == 0:
        flag_correct = bool(cleaned_flag)
        flag_points = 0.0  # Warm-up is unscored
    elif cleaned_flag:
        specs = core.levels_for_cluster(cluster)
        spec = next((x for x in specs if x["id"] == level), None)
        expected = [a.lower().strip() for a in (spec.get("answers", []) if spec else [])]
        cleaned_lower = cleaned_flag.lower().strip()
        if cleaned_lower in expected:
            flag_correct = True
            flag_points = max_fp

    # 2. Graph Evaluation
    accepted_set = {edge_key(*t) for t in (accepted_additions or [])}
    scorer = GraphScorer.from_answer_key(accepted_additions=list(accepted_set))
    released = set(core.released_papers(level, cluster))
    parsed = parse_submission(graph_csv, scorer.infos, max_rows=300, allow_any_pair=True)

    submitted_edges = {edge_key(*e) for e in parsed.edges if e[0] in released and e[1] in released}
    reference_edges = {t for t in scorer.reference if t[0] in released and t[1] in released}

    # Reference without novel additions
    initial_reference = reference_edges - accepted_set

    # Categorize submitted edges
    correct_found: list[tuple[str, str, str]] = []
    discovery_bounties: list[tuple[str, str, str]] = []
    injection_hits: list[dict[str, Any]] = []
    decoy_hits: list[tuple[str, str, str]] = []
    novel_candidates: list[dict[str, str]] = []

    hosts = core._injection_hosts()
    inj_annotations = paths.read_json(paths.INJECTIONS)["annotations"]
    inj_map = {edge_key(*a["induced_edge"]): a for a in inj_annotations}

    for e in submitted_edges:
        cls = scorer.classify(e)
        if e in accepted_set:
            discovery_bounties.append(e)
            correct_found.append(e)
        elif cls == "reference":
            correct_found.append(e)
        elif cls == "injection_induced" and hosts.get(e) in released:
            ann = inj_map.get(e, {})
            injection_hits.append({
                "edge": e,
                "injection_id": ann.get("id", "INJ"),
                "host_card": ann.get("host_card_participant_id", ""),
                "difficulty": ann.get("difficulty", ""),
            })
        elif cls == "decoy_induced":
            decoy_hits.append(e)
        elif cls == "ordinary":
            # Candidate for novel discovery
            ev = parsed.evidence.get(e, "")
            novel_candidates.append({
                "source_id": e[0],
                "target_id": e[1],
                "relationship_type": e[2],
                "evidence": ev,
            })

    # Compute base graph points
    total_ref_count = len(reference_edges)
    ratio = (len(correct_found) / total_ref_count) if total_ref_count > 0 else 0.0
    base_gp = round(max_gp * ratio, 2)

    # Compute penalties
    inj_penalty = round(len(injection_hits) * injection_penalty_pts, 2)
    dec_penalty = round(len(decoy_hits) * decoy_penalty_pts, 2)
    bounty_pts = round(len(discovery_bounties) * discovery_bounty_pts, 2)

    final_gp = max(0.0, base_gp - inj_penalty - dec_penalty) + bounty_pts
    final_gp = round(final_gp, 2)

    total_score = round(flag_points + final_gp, 2)

    return EvaluationDetail(
        team_id=team_id,
        level=level,
        flag_submitted=cleaned_flag,
        flag_correct=flag_correct,
        flag_points=flag_points,
        max_flag_points=max_fp,
        correct_edges=sorted(correct_found),
        total_reference_count=total_ref_count,
        base_graph_points=base_gp,
        injection_hits=injection_hits,
        injection_penalty=inj_penalty,
        decoy_hits=sorted(decoy_hits),
        decoy_penalty=dec_penalty,
        discovery_bounty_edges=discovery_bounties,
        discovery_bounty_points=bounty_pts,
        final_graph_points=final_gp,
        max_graph_points=max_gp,
        total_score=total_score,
        max_total_score=total_max,
        novel_candidate_edges=novel_candidates,
        explanation=explanation,
    )


def evaluate_google_form_csv(
    csv_file: Path,
    level: int,
    accepted_additions: list[tuple[str, str, str]] | None = None,
    bounty_pts: float = 250.0,
) -> list[EvaluationDetail]:
    """Parse and grade responses exported from Google Forms."""
    content = csv_file.read_text(encoding="utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(content))

    results = []
    for row in reader:
        # Normalize column lookup
        norm = {k.strip().lower(): v for k, v in row.items()}
        # Identify Team ID
        tid = ""
        for k in ("team id", "team", "team_id", "team name"):
            if k in norm and norm[k].strip():
                tid = norm[k].strip().upper()
                break
        if not tid:
            tid = f"SUBMISSION_{len(results)+1}"

        # Identify Flag
        flag = ""
        for k in ("flag", "flag answer", "answer", "question answer", "level flag"):
            for actual in norm:
                if k in actual and norm[actual].strip():
                    flag = norm[actual].strip()
                    break
            if flag:
                break

        # Identify Graph CSV text
        graph_text = ""
        for k in ("graph", "cumulative graph", "csv", "graph csv", "paste graph"):
            for actual in norm:
                if k in actual and norm[actual].strip():
                    graph_text = norm[actual].strip()
                    break
            if graph_text:
                break

        # Identify Explanation / Reasoning
        expl = ""
        for k in ("explanation", "reasoning", "evidence", "methodology"):
            for actual in norm:
                if k in actual and norm[actual].strip():
                    expl = norm[actual].strip()
                    break
            if expl:
                break

        detail = evaluate_submission(
            team_id=tid,
            level=level,
            flag_answer=flag,
            graph_csv=graph_text,
            explanation=expl,
            accepted_additions=accepted_additions,
            discovery_bounty_pts=bounty_pts,
        )
        results.append(detail)

    return sorted(results, key=lambda x: x.total_score, reverse=True)


def print_single_report(detail: EvaluationDetail):
    print("=" * 65)
    print(f"[EVALUATION REPORT] Team: {detail.team_id} | Level {detail.level}")
    print("=" * 65)
    flag_icon = "[OK]" if detail.flag_correct else "[X]"
    print(f"Flag Status:          {flag_icon} {'Correct' if detail.flag_correct else 'Incorrect'}")
    print(f"Flag Answer:          '{detail.flag_submitted}'")
    print(f"Flag Points:          {detail.flag_points:g} / {detail.max_flag_points:g} pts")
    print("-" * 65)
    print(f"Reference Edges Found: {len(detail.correct_edges)} of {detail.total_reference_count} "
          f"({(len(detail.correct_edges)/detail.total_reference_count*100) if detail.total_reference_count else 0:.1f}%)")
    print(f"Base Graph Points:    {detail.base_graph_points:g} pts")
    if detail.injection_hits:
        print(f"[!] Injection Trap Hits: {len(detail.injection_hits)} (-{detail.injection_penalty:g} pts)")
        for h in detail.injection_hits:
            print(f"    - {h['injection_id']} via card {h['host_card']}: {h['edge']}")
    else:
        print("[v] Injection Trap Hits: None (Clean)")

    if detail.decoy_hits:
        print(f"[!] Decoy Edges:         {len(detail.decoy_hits)} (-{detail.decoy_penalty:g} pts)")
        for d in detail.decoy_hits[:3]:
            print(f"    - {d[0]} -> {d[1]} ({d[2]})")
    else:
        print("[v] Decoy Edges:         None (Clean)")

    if detail.discovery_bounty_edges:
        print(f"[+] Discovery Bounty:   +{detail.discovery_bounty_points:g} pts ({len(detail.discovery_bounty_edges)} edge(s))")

    print(f"Final Graph Points:   {detail.final_graph_points:g} / {detail.max_graph_points:g} pts")
    print("=" * 65)
    print(f"[RESULT] TOTAL LEVEL SCORE:  {detail.total_score:g} / {detail.max_total_score:g} pts")
    print("=" * 65)

    if detail.novel_candidate_edges:
        print(f"\n[?] Novel Candidate Edges to Review ({len(detail.novel_candidate_edges)}):")
        for ne in detail.novel_candidate_edges:
            print(f"  - {ne['source_id']} -> {ne['target_id']} [{ne['relationship_type']}]")
            if ne.get("evidence"):
                print(f"    Evidence citation: \"{ne['evidence']}\"")


def main():
    parser = argparse.ArgumentParser(description="Evaluate Research-CTF Level Submissions")
    parser.add_argument("--level", type=int, default=1, help="Competition level (1-4)")
    parser.add_argument("--flag", type=str, default="", help="Flag answer submitted by participant")
    parser.add_argument("--graph-file", type=str, default="", help="Path to participant's graph CSV file")
    parser.add_argument("--google-form", type=str, default="", help="Path to Google Form responses CSV export")
    parser.add_argument("--export-scores", type=str, default="", help="Path to save scored leaderboard CSV")
    parser.add_argument("--accepted-file", type=str, default="", help="JSON file containing accepted dynamic additions")
    parser.add_argument("--bounty", type=float, default=250.0, help="Discovery bounty points per novel accepted edge")
    parser.add_argument("--inspect-novel", action="store_true", help="Inspect all novel candidate edges across form")

    args = parser.parse_args()

    accepted = load_accepted_additions(args.accepted_file) if args.accepted_file else []

    if args.google_form:
        form_path = Path(args.google_form)
        if not form_path.exists():
            print(f"Error: Google Form file not found: {form_path}", file=sys.stderr)
            sys.exit(1)
        results = evaluate_google_form_csv(form_path, level=args.level, accepted_additions=accepted, bounty_pts=args.bounty)
        print(f"\nGraded {len(results)} submission(s) for Level {args.level}:\n")
        summary_rows = [r.summary_row() for r in results]

        # Print Leaderboard
        import pandas as pd
        df = pd.DataFrame(summary_rows)
        print(df.to_string(index=False))

        if args.export_scores:
            out_p = Path(args.export_scores)
            df.to_csv(out_p, index=False)
            print(f"\nSaved ranked leaderboard to: {out_p.resolve()}")

        if args.inspect_novel:
            print("\n" + "=" * 60)
            print("🔍 CANDIDATE NOVEL EDGES REQUIRING ORGANISER REVIEW:")
            print("=" * 60)
            candidate_counts: dict[tuple, list[str]] = {}
            for r in results:
                for ne in r.novel_candidate_edges:
                    key = (ne["source_id"], ne["target_id"], ne["relationship_type"])
                    candidate_counts.setdefault(key, []).append(f"{r.team_id}: {ne['evidence']}")
            if not candidate_counts:
                print("No novel edges detected. All submitted edges are in reference, decoy, or injection sets.")
            else:
                for edge, team_evs in sorted(candidate_counts.items(), key=lambda x: len(x[1]), reverse=True):
                    print(f"\n• Edge: {edge[0]} -> {edge[1]} ({edge[2]}) [Submitted by {len(team_evs)} team(s)]")
                    for ev_line in team_evs:
                        print(f"    - {ev_line}")
        return

    # Single submission mode
    graph_text = ""
    if args.graph_file:
        gf = Path(args.graph_file)
        if gf.exists():
            graph_text = gf.read_text(encoding="utf-8")
        else:
            print(f"Error: Graph file not found: {gf}", file=sys.stderr)
            sys.exit(1)
    else:
        # Default Level 1 reference for demo if not provided
        graph_text = "source_id,target_id,relationship_type\nP02,P05,CITES\nP13,P05,CITES\nP13,P02,CITES\nP02,P05,ANALOGOUS_PROBLEM\nP05,P13,ANALOGOUS_PROBLEM\n"

    flag_ans = args.flag or "the receivers"
    detail = evaluate_submission(
        team_id="CLI_TEST_TEAM",
        level=args.level,
        flag_answer=flag_ans,
        graph_csv=graph_text,
        accepted_additions=accepted,
        discovery_bounty_pts=args.bounty,
    )
    print_single_report(detail)


if __name__ == "__main__":
    main()
