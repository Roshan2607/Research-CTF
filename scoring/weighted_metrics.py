"""Weighted typed-edge precision / recall / F1.

    Weighted Precision = TP / (TP + sum_i w_i * FP_i)
    Recall             = TP / (TP + FN)
    Weighted F1        = 2 * WP * R / (WP + R)

All zero denominators return 0.0, so an empty submission scores 0 rather than
crashing. Scores are always within [0, 1].
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Counts:
    tp: int = 0
    fn: int = 0
    fp_ordinary: int = 0
    fp_decoy: int = 0
    fp_injection: int = 0
    neutral: int = 0

    @property
    def fp(self) -> int:
        return self.fp_ordinary + self.fp_decoy + self.fp_injection


@dataclass(frozen=True)
class Metrics:
    weighted_precision: float
    recall: float
    weighted_f1: float
    weighted_fp: float

    def as_dict(self) -> dict:
        return asdict(self)


def safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def compute(counts: Counts, weights: dict[str, float]) -> Metrics:
    wfp = (
        weights["ordinary"] * counts.fp_ordinary
        + weights["decoy_induced"] * counts.fp_decoy
        + weights["injection_induced"] * counts.fp_injection
    )
    wp = safe_div(counts.tp, counts.tp + wfp)
    rec = safe_div(counts.tp, counts.tp + counts.fn)
    f1 = safe_div(2 * wp * rec, wp + rec)
    clamp = lambda x: max(0.0, min(1.0, x))  # noqa: E731
    return Metrics(clamp(wp), clamp(rec), clamp(f1), wfp)


def compute_from_rows(labels, predictions, fp_weights) -> Metrics:
    """Row-aligned variant (Kaggle style): labels in {0,1}, predictions in {0,1},
    fp_weights = organiser weight per row (0 for neutral rows)."""
    tp = fn = 0
    wfp = 0.0
    for y, p, w in zip(labels, predictions, fp_weights):
        if y == 1 and p == 1:
            tp += 1
        elif y == 1 and p == 0:
            fn += 1
        elif y == 0 and p == 1:
            wfp += float(w)
    wp = safe_div(tp, tp + wfp)
    rec = safe_div(tp, tp + fn)
    f1 = safe_div(2 * wp * rec, wp + rec)
    return Metrics(wp, rec, f1, wfp)
