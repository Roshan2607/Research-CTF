"""Kaggle-compatible custom metric: weighted typed-edge F1.

Self-contained (pandas only) so it can be pasted into a Kaggle metric notebook.
It must produce exactly the same number as the local scorer
(``scoring.graph_scorer``), which remains the source of truth; a test checks this.

Competition format
------------------
* ``candidate_edges.csv`` (public data): ``id, source_id, target_id, relationship_type``,
  the fixed candidate universe of typed paper-to-paper edges.
* Submission: ``id, predicted`` with ``predicted`` in {0, 1} for every id.
  An absent relationship is ``predicted = 0``.
* Solution (private, uploaded by the host): ``id, label, fp_weight, Usage``.
  ``label`` = 1 for reference edges. ``fp_weight`` = organiser false-positive weight
  (ordinary 1.0, decoy 0.5, injection 3.0, neutral 0.0). ``Usage`` = Public/Private.
  Kaggle scores the public leaderboard on Public rows and the private one on Private rows.

    weighted precision = TP / (TP + sum(fp_weight of predicted negatives))
    recall             = TP / (TP + FN)
    score              = 2PR / (P + R)        (0 when undefined)
"""
import pandas as pd


class ParticipantVisibleError(Exception):
    pass


def score(solution: pd.DataFrame, submission: pd.DataFrame, row_id_column_name: str) -> float:
    """Kaggle entry point. Returns weighted F1 in [0, 1]."""
    if "predicted" not in submission.columns:
        raise ParticipantVisibleError("Submission must have columns: id, predicted")
    sol = solution[[row_id_column_name, "label", "fp_weight"]].copy()
    sub = submission[[row_id_column_name, "predicted"]].copy()
    if sub[row_id_column_name].duplicated().any():
        raise ParticipantVisibleError("Duplicate ids in submission")
    merged = sol.merge(sub, on=row_id_column_name, how="left", validate="one_to_one")
    if merged["predicted"].isna().any():
        missing = int(merged["predicted"].isna().sum())
        raise ParticipantVisibleError(f"Submission is missing {missing} ids; include every id with predicted 0 or 1")
    try:
        pred = pd.to_numeric(merged["predicted"]).astype(float)
    except (TypeError, ValueError) as exc:
        raise ParticipantVisibleError("predicted must be 0 or 1") from exc
    if not pred.isin([0.0, 1.0]).all():
        raise ParticipantVisibleError("predicted must be 0 or 1")
    label = merged["label"].astype(int)
    weight = merged["fp_weight"].astype(float)
    tp = float(((label == 1) & (pred == 1)).sum())
    fn = float(((label == 1) & (pred == 0)).sum())
    wfp = float(weight[(label == 0) & (pred == 1)].sum())
    precision = tp / (tp + wfp) if (tp + wfp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    return 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
