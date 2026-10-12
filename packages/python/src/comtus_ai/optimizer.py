from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations
import math
from typing import Mapping, Sequence

from .models import EvidenceSource


@dataclass(frozen=True, slots=True)
class Pitcher:
    card_id: str
    display_name: str


@dataclass(frozen=True, slots=True)
class Opponent:
    opponent_id: str
    display_name: str


@dataclass(frozen=True, slots=True)
class RotationResult:
    recommended: tuple[str, ...]
    baseline: tuple[str, ...]
    ties: tuple[tuple[str, ...], ...]
    matrix: dict[str, dict[str, float | None]]
    score_type: str
    input_source: str
    model_version: str
    known_matchups: int
    total_matchups: int
    recommendation_reasons: tuple[str, ...]
    reflected_rules: tuple[str, ...]
    omitted_rules: tuple[str, ...]
    data_confidence: str

    def to_dict(self, pitchers: Sequence[Pitcher], opponents: Sequence[Opponent]) -> dict[str, object]:
        pitcher_names = {p.card_id: p.display_name for p in pitchers}
        opponent_names = {o.opponent_id: o.display_name for o in opponents}
        opponent_pitcher_rows = [
            {"opponent_id": opponent.opponent_id, "opponent": opponent_names[opponent.opponent_id],
             "pitcher_card_id": pitcher_id, "pitcher": pitcher_names[pitcher_id]}
            for opponent, pitcher_id in zip(opponents, self.baseline, strict=True)
        ]
        return {
            "recommended_rotation": [
                {"opponent_id": opponent.opponent_id, "opponent": opponent_names[opponent.opponent_id],
                 "pitcher_card_id": pitcher_id, "pitcher": pitcher_names[pitcher_id]}
                for opponent, pitcher_id in zip(opponents, self.recommended, strict=True)
            ],
            "baseline_rotation": opponent_pitcher_rows,
            "baseline_pitcher_card_ids": list(self.baseline),
            "tied_optima": [list(row) for row in self.ties],
            "matchup_matrix": self.matrix,
            "score_type": self.score_type,
            "input_source": self.input_source,
            "model_version": self.model_version,
            "known_matchups": self.known_matchups,
            "total_matchups": self.total_matchups,
            "data_confidence": self.data_confidence,
            "recommendation_reasons": list(self.recommendation_reasons),
            "reflected_rules": list(self.reflected_rules),
            "omitted_rules": list(self.omitted_rules),
            "probability_calibrated": False,
        }


def optimize_rotation(
    pitchers: Sequence[Pitcher],
    opponents: Sequence[Opponent],
    scores: Mapping[tuple[str, str], float | None],
    baseline: Sequence[str] | None = None,
    input_source: EvidenceSource | str = EvidenceSource.UNKNOWN,
) -> RotationResult:
    """Maximize a relative, uncalibrated heuristic over every 5-pitcher ordering.

    Missing scores are not interpreted as wins or positive evidence. Candidates
    are ranked first by the number of rated matchups, then by their score sum.
    """
    if len(pitchers) != 5 or len(opponents) != 5:
        raise ValueError("rotation optimization requires exactly five pitchers and opponents")
    pitcher_ids = tuple(p.card_id for p in pitchers)
    opponent_ids = tuple(o.opponent_id for o in opponents)
    if len(set(pitcher_ids)) != 5 or len(set(opponent_ids)) != 5:
        raise ValueError("pitcher card IDs and opponent IDs must each be unique")
    try:
        source = EvidenceSource(input_source)
    except ValueError:
        source = EvidenceSource.UNKNOWN
    for value in scores.values():
        if value is not None and not math.isfinite(value):
            raise ValueError("matchup heuristic scores must be finite or missing")
    base = tuple(baseline or pitcher_ids)
    if len(base) != 5 or set(base) != set(pitcher_ids):
        raise ValueError("baseline must contain each pitcher card ID exactly once")

    matrix = {
        pitcher_id: {opponent_id: scores.get((pitcher_id, opponent_id)) for opponent_id in opponent_ids}
        for pitcher_id in pitcher_ids
    }

    def quality(rotation: tuple[str, ...]) -> tuple[int, float]:
        cells = [scores.get((pitcher_id, opponent_id)) for pitcher_id, opponent_id in zip(rotation, opponent_ids, strict=True)]
        rated = [score for score in cells if score is not None]
        return len(rated), sum(rated)

    candidates = list(permutations(pitcher_ids))
    qualities = {candidate: quality(candidate) for candidate in candidates}
    best_quality = max(qualities.values())
    ties = tuple(sorted(candidate for candidate, value in qualities.items() if value == best_quality))
    recommended = ties[0]
    reasons: list[str] = []
    baseline_quality = qualities[base]
    if recommended == base:
        reasons.append("The baseline rotation is already the deterministic best-scoring assignment.")
    else:
        reasons.append(f"The selected assignment has quality {best_quality} versus baseline {baseline_quality} (rated matchups, heuristic score sum).")
    for index, (old, new, opponent_id) in enumerate(zip(base, recommended, opponent_ids, strict=True), start=1):
        if old != new:
            old_score = scores.get((old, opponent_id))
            new_score = scores.get((new, opponent_id))
            if old_score is None or new_score is None:
                reasons.append(f"Slot {index} vs {opponent_id}: {old} -> {new}; at least one matchup score is unknown.")
            else:
                reasons.append(f"Slot {index} vs {opponent_id}: {old} ({old_score:g}) -> {new} ({new_score:g}) by heuristic score.")
    known = sum(score is not None for row in matrix.values() for score in row.values())
    confidence = "UNKNOWN" if known == 0 else "LOW" if known < 25 else "UNVALIDATED_HEURISTIC"
    return RotationResult(
        recommended=recommended,
        baseline=base,
        ties=ties,
        matrix=matrix,
        score_type="HEURISTIC_SCORE",
        input_source=source.value,
        model_version="rotation-heuristic-v1",
        known_matchups=known,
        total_matchups=25,
        recommendation_reasons=tuple(reasons),
        reflected_rules=("provided matchup scores", "one-to-one five-game assignment"),
        omitted_rules=("calibrated win probability", "our batting lineup vs opponent starting/bullpen", "unverified skills/potentials/synergy modifiers", "score prediction"),
        data_confidence=confidence,
    )
