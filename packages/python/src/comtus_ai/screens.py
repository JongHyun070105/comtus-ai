from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Sequence

from .observations import OCRObservation


class ScreenState(StrEnum):
    RANKING_LOBBY = "RANKING_LOBBY"
    PITCHER_ORDER = "PITCHER_ORDER"
    OPPONENT_LINEUP = "OPPONENT_LINEUP"
    OPPONENT_STARTING_PITCHER_DETAIL = "OPPONENT_STARTING_PITCHER_DETAIL"
    PLAYER_DETAIL_BATTER = "PLAYER_DETAIL_BATTER"
    PLAYER_DETAIL_PITCHER = "PLAYER_DETAIL_PITCHER"
    TEAM_ROSTER = "TEAM_ROSTER"
    SYNERGY = "SYNERGY"
    POSITION_TRAINING = "POSITION_TRAINING"
    UNKNOWN = "UNKNOWN"


class ClassificationStatus(StrEnum):
    VERIFIED = "VERIFIED"
    CANDIDATE = "CANDIDATE"
    UNKNOWN = "UNKNOWN"


class PanelRole(StrEnum):
    LEFT_PREVIEW = "LEFT_PREVIEW"
    ACTIVE = "ACTIVE"
    RIGHT_PREVIEW = "RIGHT_PREVIEW"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class NormalizedRect:
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        if (not all(0 <= item <= 1 for item in (self.x, self.y, self.width, self.height))
                or self.width <= 0 or self.height <= 0
                or self.x + self.width > 1.000001 or self.y + self.height > 1.000001):
            raise ValueError("panel rectangles must be non-empty normalized frame bounds")

    def contains(self, bbox: Sequence[float]) -> bool:
        if len(bbox) != 4:
            return False
        center_x = bbox[0] + bbox[2] / 2
        center_y = bbox[1] + bbox[3] / 2
        return self.x <= center_x <= self.x + self.width and self.y <= center_y <= self.y + self.height


@dataclass(frozen=True, slots=True)
class PanelLayout:
    """Explicitly measured panel bounds; no default geometry is inferred."""

    active: NormalizedRect
    left_preview: NormalizedRect
    right_preview: NormalizedRect

    def role_for(self, bbox: Sequence[float]) -> PanelRole:
        matches = [role for role, region in (
            (PanelRole.ACTIVE, self.active),
            (PanelRole.LEFT_PREVIEW, self.left_preview),
            (PanelRole.RIGHT_PREVIEW, self.right_preview),
        ) if region.contains(bbox)]
        return matches[0] if len(matches) == 1 else PanelRole.UNKNOWN


@dataclass(frozen=True, slots=True)
class ScreenClassification:
    state: ScreenState
    status: ClassificationStatus
    confidence: float | None
    anchor_indices: tuple[int, ...] = ()
    active_panel: NormalizedRect | None = None
    left_preview: NormalizedRect | None = None
    right_preview: NormalizedRect | None = None
    profile_version: str = "screen-profiles-v1"


def _compact(text: str) -> str:
    return "".join(character for character in text if not character.isspace())


def _center(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    return bbox[0] + bbox[2] / 2, bbox[1] + bbox[3] / 2


def recognize_screen(observations: Sequence[OCRObservation]) -> ScreenClassification:
    """Recognize only a multi-anchor profile backed by the local V26 capture.

    Other requested screens deliberately remain UNKNOWN until their own real
    anchor layouts have been collected and reviewed.
    """
    title: list[int] = []
    instruction: list[int] = []
    reset: list[int] = []
    save: list[int] = []
    for index, observation in enumerate(observations):
        text = _compact(observation.text)
        x, y = _center(observation.bbox)
        if ("선발투수변경" in text and 0.34 <= x <= 0.66 and 0.78 <= y <= 0.89):
            title.append(index)
        if ("내선발투수의순서를변경할수있습니다" in text and 0.25 <= x <= 0.75 and 0.74 <= y <= 0.84):
            instruction.append(index)
        if text == "원래대로" and x < 0.42 and y < 0.12:
            reset.append(index)
        if text == "저장" and x > 0.58 and y < 0.12:
            save.append(index)

    if title and instruction and reset and save:
        indices = (title[0], instruction[0], reset[0], save[0])
        confidences = [observations[index].confidence for index in indices]
        confidence = min(confidences) if all(value is not None for value in confidences) else None
        status = ClassificationStatus.VERIFIED if confidence is not None and confidence >= 0.85 else ClassificationStatus.CANDIDATE
        return ScreenClassification(ScreenState.PITCHER_ORDER, status, confidence, indices)

    return ScreenClassification(ScreenState.UNKNOWN, ClassificationStatus.UNKNOWN, None)
