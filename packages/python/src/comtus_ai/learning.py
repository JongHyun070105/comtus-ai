from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence


@dataclass(frozen=True, slots=True)
class MatchLabel:
    predicted_win_probability: float
    actual_win: bool
    predicted_score: float | None = None
    actual_score: float | None = None


def evaluate_predictions(rows: Sequence[MatchLabel]) -> dict[str, object]:
    """Compute offline metrics only from caller-supplied, labeled real results."""
    if not rows:
        return {"status": "NO_LABELED_RESULTS", "sample_count": 0, "metrics": None}
    for row in rows:
        if not math.isfinite(row.predicted_win_probability) or not 0 <= row.predicted_win_probability <= 1:
            raise ValueError("predicted win probabilities must be finite and in [0, 1]")
    brier = sum((row.predicted_win_probability - float(row.actual_win)) ** 2 for row in rows) / len(rows)
    epsilon = 1e-15
    log_loss = -sum(
        float(row.actual_win) * math.log(max(row.predicted_win_probability, epsilon))
        + (1 - float(row.actual_win)) * math.log(max(1 - row.predicted_win_probability, epsilon))
        for row in rows
    ) / len(rows)
    scored = [row for row in rows if row.predicted_score is not None and row.actual_score is not None]
    score_mae = None if not scored else sum(abs(row.predicted_score - row.actual_score) for row in scored) / len(scored)  # type: ignore[operator]
    wins = sum(row.actual_win for row in rows)
    return {
        "status": "OFFLINE_EVALUATION",
        "sample_count": len(rows),
        "metrics": {"brier_score": brier, "log_loss": log_loss, "actual_win_rate": wins / len(rows), "score_mae": score_mae},
        "calibration": _calibration(rows),
    }


def _calibration(rows: Sequence[MatchLabel], bins: int = 10) -> list[dict[str, float | int]]:
    groups: list[list[MatchLabel]] = [[] for _ in range(bins)]
    for row in rows:
        index = min(bins - 1, int(row.predicted_win_probability * bins))
        groups[index].append(row)
    return [
        {"bin": index, "count": len(group), "mean_predicted": sum(r.predicted_win_probability for r in group) / len(group), "observed_rate": sum(r.actual_win for r in group) / len(group)}
        for index, group in enumerate(groups) if group
    ]
