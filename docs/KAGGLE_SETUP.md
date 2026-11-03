# Kaggle setup (Submission 1: graph reconstruction)

The **local scorer is the source of truth** (`scoring/graph_scorer.py`). The Kaggle metric (`scoring/kaggle_metric.py`)
mirrors it exactly, and `tests/test_kaggle.py` checks they agree. Kaggle provides the hosted leaderboard. If Kaggle is
unavailable, use the local fallback (section 6).

> The Kaggle API cannot create or configure a competition. Everything below is a **manual** step in the Kaggle web
> interface. Kaggle's host UI changes from time to time, so check each step against Kaggle's current host documentation.

## 1. Why the format is a fixed grid

Kaggle compares submission rows to solution rows by `id`, so an open-ended edge list will not work. Instead the
competition enumerates every possible typed paper-to-paper edge as one row (the *candidate universe*):

| File | Visibility | Columns |
|---|---|---|
| `kaggle/candidate_edges.csv` | public data | `id, source_id, target_id, relationship_type` (473 rows) |
| `kaggle/sample_submission.csv` | public data | `id, predicted` (all 0) |
| `data/answer_key/kaggle_solution.csv` | **host only** (git-ignored) | `id, label, fp_weight, Usage` |

A team's submission marks `predicted = 1` for each edge it asserts. An **absent** relationship is `predicted = 0`. Symmetric
relations (`SHARES_PRINCIPLE`, `ANALOGOUS_PROBLEM`) appear once, with the smaller ID first. Directed relations that are
impossible (a 1999 paper citing a 2008 one) are not in the grid.

`fp_weight` carries the organiser's false-positive classification: ordinary 1.0, decoy-induced 0.5, injection-induced 3.0,
neutral / under review 0.0, reference 0.0 (and `label = 1`). Participants never see or choose these classes.

Teams can keep working with the friendlier edge-list CSV and convert it:

```bash
python -m scoring.kaggle_format my_edges.csv kaggle_submission.csv
```

The participant app's *Graph builder* tab also has a "Download Kaggle submission" button.

## 2. Build the files

```bash
python scripts/build_challenge.py          # writes kaggle/*.csv and data/answer_key/kaggle_solution.csv
python -m pytest tests/test_kaggle.py      # metric parity with the local scorer
```

Rebuild and re-upload the solution whenever you promote reviewed edges (section 5).

## 3. Create the competition (manual)

1. Go to **kaggle.com → Competitions → Host a competition** and choose a **Community** competition.
2. Basic details: title *Uncharted Literature: Knowledge Graph CTF*, a short description, and "private / invite-only"
   visibility with an invitation link for workshop teams.
3. **Data:** upload `kaggle/candidate_edges.csv`, `kaggle/sample_submission.csv`, `data/participant/participant_papers.json`,
   `data/participant/relationship_vocabulary.json` and the card PDFs in `data/participant/cards/`.
   **Never upload `kaggle_solution.csv` as data.**
4. **Solution file:** upload `data/answer_key/kaggle_solution.csv` in the host *Evaluation / Solution* settings. Kaggle uses
   the `Usage` column (`Public` / `Private`) to split the public and private leaderboards.
5. **Metric:** create a new Kaggle Notebook and paste the whole of `scoring/kaggle_metric.py` into it (it depends only on
   pandas). Publish it as a metric following Kaggle's custom-metric instructions, then select it in the competition's
   evaluation settings. The entry point is `score(solution, submission, row_id_column_name)`, with `id` as the row-ID
   column. Test it against `data/samples/kaggle_submission_revised.csv`: Kaggle should report **0.6333** overall,
   matching `python -m scoring.graph_scorer data/samples/sample_submission_revised.csv`.
6. **Rules / limits:**
   * Team size: **2**.
   * Maximum daily submissions: about **15** (matches `config/challenge_config.json`; it also limits score probing).
   * Final submissions for private-leaderboard scoring: let teams select up to 2. If they select none, Kaggle uses their
     best public-leaderboard submissions. Tell teams to select their best graph.
   * Deadline: the end of the graph-correction block (about minute 135 of the workshop).
7. Leaderboard feedback is aggregate only (one number per submission). This is the brief's requirement that score
   responses must not reveal edge-by-edge reference information.

## 4. Public vs private leaderboard

About half of the candidate edges (and about half of the 41 reference edges) are `Public`. The split comes from a stable
hash (`config.graph_submission.split_seed`), so promoting a reviewed edge never moves other edges between splits.
The private leaderboard decides the final ranking. This blunts *oracle probing*, where a team submits one edge at a time
to learn which are correct.

## 5. Manual review and rescoring

1. Teams may include an `evidence_reference` with each edge (local app). False-positive edges that come with evidence go
   to the organiser **review queue** (organiser console → *Review queue*).
2. Accepting an edge records it in `data/submissions/accepted_additions.json`. The local scorer picks it up immediately.
3. For Kaggle, run `python scripts/build_challenge.py` again, re-upload `kaggle_solution.csv`, and use the host option to
   **rescore** existing submissions, if available in your competition type. Otherwise announce the change and use the
   local leaderboard for the final ranking.

## 6. Local fallback (no Kaggle)

The participant app (`streamlit run app.py`) has a *Submit & score* tab that scores the same edge list with the same
weights. It shows the public-split score and stores every submission with team and timestamp. The organiser console
leaderboard shows the **best valid score before the deadline** for each team, on the public, private or all split.
Export it as CSV from the console.
