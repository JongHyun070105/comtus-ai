from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from typing import TypeAlias


class EvidenceSource(StrEnum):
    SCREEN_CAPTURE_VERIFIED = "SCREEN_CAPTURE_VERIFIED"
    USER_PROVIDED_REFERENCE = "USER_PROVIDED_REFERENCE"
    MANUAL_TRANSCRIPTION = "MANUAL_TRANSCRIPTION"
    COMMUNITY_RESEARCH = "COMMUNITY_RESEARCH"
    OFFICIAL_RULE = "OFFICIAL_RULE"
    SYNTHETIC_TEST = "SYNTHETIC_TEST"
    UNKNOWN = "UNKNOWN"


class CardType(StrEnum):
    SEASON = "SEASON"
    LIVE = "LIVE"
    SIGNATURE = "SIGNATURE"
    IMPACT = "IMPACT"
    GOLDEN_GLOVE = "GOLDEN_GLOVE"
    NATIONAL_TEAM = "NATIONAL_TEAM"
    LIVE_ALLSTAR = "LIVE_ALLSTAR"
    FA_IMPACT = "FA_IMPACT"
    FA_SIGNATURE = "FA_SIGNATURE"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class GameMode(StrEnum):
    LEAGUE = "LEAGUE"
    RANKING_CHALLENGE = "RANKING_CHALLENGE"
    REALTIME_MATCH = "REALTIME_MATCH"
    SPECIAL_MATCH = "SPECIAL_MATCH"
    CLUB_BATTLE = "CLUB_BATTLE"
    UNKNOWN = "UNKNOWN"


class PlayerRole(StrEnum):
    BATTER = "BATTER"
    STARTING_PITCHER = "STARTING_PITCHER"
    RELIEF_PITCHER = "RELIEF_PITCHER"
    CLOSER = "CLOSER"
    UNKNOWN = "UNKNOWN"


def parse_card_type(value: str | CardType | None) -> CardType:
    if isinstance(value, CardType):
        return value
    if value is None:
        return CardType.UNKNOWN
    try:
        return CardType(value.strip().upper())
    except ValueError:
        return CardType.UNKNOWN


def normalize_grade(value: str | None) -> str | None:
    """Normalize ordinal labels without treating them as numeric statistics."""
    if value is None:
        return None
    normalized = value.strip().upper().replace(" ", "")
    return normalized or None


@dataclass(frozen=True, slots=True)
class CardMaster:
    canonical_name: str
    team_name: str | None
    card_type: CardType = CardType.UNKNOWN
    season_year: int | None = None


@dataclass(frozen=True, slots=True)
class CardInstance:
    account_key: str
    master: CardMaster
    stars: int | None = None
    live_version: str | None = None
    enhancement: int | None = None
    instance_key: str | None = None

    def __post_init__(self) -> None:
        if self.stars is not None and not 1 <= self.stars <= 5:
            raise ValueError("stars must be between 1 and 5")
        if self.enhancement is not None and self.enhancement < 0:
            raise ValueError("enhancement must be non-negative")


@dataclass(frozen=True, slots=True)
class BatterStats:
    power: float | None = None
    contact: float | None = None
    eye: float | None = None
    patience: float | None = None
    speed: float | None = None
    fielding: float | None = None


@dataclass(frozen=True, slots=True)
class PitcherStats:
    velocity: float | None = None
    movement: float | None = None
    stuff: float | None = None
    control: float | None = None
    stamina: float | None = None
    fielding: float | None = None


PlayerStats: TypeAlias = BatterStats | PitcherStats | None


@dataclass(frozen=True, slots=True)
class SkillRecord:
    slot: int
    name: str
    level: int | None
    source: EvidenceSource
    confidence: float | None = None

    def __post_init__(self) -> None:
        if self.slot < 1:
            raise ValueError("skill slot numbers start at 1")
        validate_confidence(self.confidence)


@dataclass(frozen=True, slots=True)
class PotentialRecord:
    name: str
    grade: str | None
    trained: bool | None
    source: EvidenceSource
    confidence: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "grade", normalize_grade(self.grade))
        validate_confidence(self.confidence)


@dataclass(frozen=True, slots=True)
class PitchGradeRecord:
    pitch_name: str
    grade: str | None
    source: EvidenceSource
    confidence: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "grade", normalize_grade(self.grade))
        validate_confidence(self.confidence)


@dataclass(frozen=True, slots=True)
class PlayerSnapshot:
    card: CardInstance
    role: PlayerRole
    position: str | None = None
    handedness: str | None = None
    overall: float | None = None
    stats: PlayerStats = None
    average_launch_angle: float | None = None
    set_deck_points: float | None = None
    skills: tuple[SkillRecord, ...] = ()
    potentials: tuple[PotentialRecord, ...] = ()
    pitch_grades: tuple[PitchGradeRecord, ...] = ()
    hot_cold_zones: tuple[float | None, ...] = ()
    source: EvidenceSource = EvidenceSource.UNKNOWN
    confidence: float | None = None
    observed_at: str | None = None
    game_version: str | None = None
    mode: GameMode = GameMode.UNKNOWN
    rules_version: str | None = None

    def __post_init__(self) -> None:
        if self.role == PlayerRole.BATTER and isinstance(self.stats, PitcherStats):
            raise ValueError("batter snapshots cannot contain pitcher statistics")
        if self.role in (PlayerRole.STARTING_PITCHER, PlayerRole.RELIEF_PITCHER, PlayerRole.CLOSER) and isinstance(self.stats, BatterStats):
            raise ValueError("pitcher snapshots cannot contain batter statistics")
        if self.hot_cold_zones and len(self.hot_cold_zones) != 9:
            raise ValueError("hot/cold zones must contain exactly nine cells")
        if len({skill.slot for skill in self.skills}) != len(self.skills):
            raise ValueError("skill slots must be unique within a snapshot")
        validate_confidence(self.confidence)


def validate_confidence(value: float | None) -> float | None:
    if value is None:
        return None
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("confidence must be a finite value in [0, 1]")
    return value
