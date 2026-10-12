from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence

from .models import CardType, GameMode


BATTER_SLOTS = ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH", "SUB")
PITCHER_SLOTS = tuple([f"SP{i}" for i in range(1, 6)] + [f"RP{i}" for i in range(1, 6)] + ["CP"])
TRAINING_MILESTONES = {5: "ATTRIBUTE_BONUS", 10: "SKILL_BONUS", 15: "ADDITIONAL_ATTRIBUTE_BONUS", 20: "ADDITIONAL_SKILL_BONUS"}


def unlocked_training_milestones(level: int) -> tuple[str, ...]:
    if not 0 <= level <= 20:
        raise ValueError("training level must be in [0, 20]")
    return tuple(name for threshold, name in TRAINING_MILESTONES.items() if level >= threshold)


@dataclass(frozen=True, slots=True)
class RosterCard:
    card_id: str
    card_type: CardType
    team_name: str | None = None
    role: str | None = None


@dataclass(frozen=True, slots=True)
class SynergyRule:
    rule_id: str
    mode: GameMode
    card_types: frozenset[CardType]
    threshold: int
    attributes: frozenset[str]
    delta: float
    source: str
    rules_version: str
    team_name: str | None = None
    targets: str = "ALL_PLAYERS"
    active_from: datetime | None = None
    active_until: datetime | None = None


@dataclass(frozen=True, slots=True)
class RuleDecision:
    rule_id: str
    eligible: bool
    applied: bool
    reason: str
    targets: tuple[str, ...] = ()


def evaluate_synergies(
    mode: GameMode,
    roster: Sequence[RosterCard],
    rules: Sequence[SynergyRule],
    *,
    stats_include_modifiers: bool | None,
    now: datetime | None = None,
) -> tuple[RuleDecision, ...]:
    """Evaluate declared conditions and fail closed on unknown modifier provenance."""
    now = now or datetime.now().astimezone()
    seen_rules: set[str] = set()
    decisions: list[RuleDecision] = []
    for rule in rules:
        if rule.rule_id in seen_rules:
            continue
        seen_rules.add(rule.rule_id)
        if rule.mode != mode:
            decisions.append(RuleDecision(rule.rule_id, False, False, "mode mismatch"))
            continue
        if rule.threshold < 1:
            decisions.append(RuleDecision(rule.rule_id, False, False, "invalid threshold"))
            continue
        if rule.active_from and now < rule.active_from:
            decisions.append(RuleDecision(rule.rule_id, False, False, "not active yet"))
            continue
        if rule.active_until and now >= rule.active_until:
            decisions.append(RuleDecision(rule.rule_id, False, False, "expired"))
            continue
        matched = [
            card for card in roster
            if card.card_type in rule.card_types
            and (rule.team_name is None or card.team_name == rule.team_name)
        ]
        if len(matched) < rule.threshold:
            decisions.append(RuleDecision(rule.rule_id, False, False, "threshold not met"))
            continue
        targets = tuple(
            card.card_id for card in roster
            if rule.targets == "ALL_PLAYERS" or (rule.targets == "BATTERS" and card.role == "BATTER")
        )
        if stats_include_modifiers is not False:
            reason = "base stat modifier inclusion is unknown" if stats_include_modifiers is None else "base stats already include modifiers"
            decisions.append(RuleDecision(rule.rule_id, True, False, reason, targets))
            continue
        decisions.append(RuleDecision(rule.rule_id, True, True, "condition met; raw base stats declared", targets))
    return tuple(decisions)


def apply_declared_effects(
    base_stats: Mapping[str, Mapping[str, float]],
    rules: Sequence[SynergyRule],
    decisions: Sequence[RuleDecision],
) -> dict[str, dict[str, float]]:
    result = {player_id: dict(values) for player_id, values in base_stats.items()}
    by_id = {rule.rule_id: rule for rule in rules}
    for decision in decisions:
        rule = by_id.get(decision.rule_id)
        if not decision.applied or rule is None:
            continue
        for player_id in decision.targets:
            if player_id not in result:
                continue
            for attribute in rule.attributes:
                if attribute in result[player_id]:
                    result[player_id][attribute] += rule.delta
    return result
