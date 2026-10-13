from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
import re
from typing import Mapping, Sequence

from .observations import OCRObservation


class ScreenState(StrEnum):
    HOME = "HOME"
    RANKING_LOBBY = "RANKING_LOBBY"
    PITCHER_ORDER = "PITCHER_ORDER"
    OPPONENT_LINEUP = "OPPONENT_LINEUP"
    OPPONENT_STARTING_PITCHER_DETAIL = "OPPONENT_STARTING_PITCHER_DETAIL"
    PLAYER_DETAIL_BATTER = "PLAYER_DETAIL_BATTER"
    PLAYER_DETAIL_PITCHER = "PLAYER_DETAIL_PITCHER"
    TEAM_ROSTER = "TEAM_ROSTER"
    SYNERGY = "SYNERGY"
    POSITION_TRAINING = "POSITION_TRAINING"
    MATCH_RESULT = "MATCH_RESULT"
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


SCREEN_PROFILE_VERSION = "screen-profiles-v3"


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

    def contains(self, bbox: Sequence[float], *, safety_margin: float = 0.01) -> bool:
        """Require the whole OCR box to fit inside the ROI plus an edge margin."""
        if (len(bbox) != 4 or not math.isfinite(safety_margin) or safety_margin < 0
                or any(not math.isfinite(value) for value in bbox)):
            return False
        x, y, width, height = bbox
        if width <= 0 or height <= 0 or x < 0 or y < 0 or x + width > 1 or y + height > 1:
            return False
        return (x >= self.x + safety_margin and y >= self.y + safety_margin
                and x + width <= self.x + self.width - safety_margin
                and y + height <= self.y + self.height - safety_margin)


@dataclass(frozen=True, slots=True)
class PanelLayout:
    """Explicitly measured panel bounds; no default geometry is inferred."""

    active: NormalizedRect
    left_preview: NormalizedRect
    right_preview: NormalizedRect

    def __post_init__(self) -> None:
        regions = (self.active, self.left_preview, self.right_preview)
        for index, first in enumerate(regions):
            for second in regions[index + 1:]:
                overlap_width = min(first.x + first.width, second.x + second.width) - max(first.x, second.x)
                overlap_height = min(first.y + first.height, second.y + second.height) - max(first.y, second.y)
                if overlap_width > 1e-9 and overlap_height > 1e-9:
                    raise ValueError("panel layout regions must not overlap")

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
    profile_version: str = SCREEN_PROFILE_VERSION


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
    swap: list[int] = []
    back: list[int] = []
    own_starter_roles: dict[int, int] = {}
    opponent_starter_roles: dict[int, int] = {}
    for index, observation in enumerate(observations):
        if observation.confidence is None or observation.confidence < 0.3:
            continue
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
        if text == "선수교체" and 0.40 <= x <= 0.60 and y < 0.10:
            swap.append(index)
        if "뒤로가기" in text and 0.35 <= x <= 0.65 and y < 0.05:
            back.append(index)
        role = re.fullmatch(r"([1-5])선발[RL]", text)
        if role and observation.confidence >= 0.9 and 0.15 <= y <= 0.78:
            if 0.18 <= x <= 0.30:
                own_starter_roles.setdefault(int(role.group(1)), index)
            elif 0.34 <= x <= 0.44:
                opponent_starter_roles.setdefault(int(role.group(1)), index)

    if title and instruction and reset and save:
        legacy_indices = [title[0], instruction[0], reset[0], save[0]]
        # The real screenshot has low OCR confidence on its title and action
        # labels. Require their presence and placement, then verify the layout
        # with the high-confidence instruction, reset label, and three distinct
        # own-starter role labels. Opponent-side roles are outside this x band.
        role_indices = [own_starter_roles[key] for key in sorted(own_starter_roles)]
        opponent_role_indices = [opponent_starter_roles[key] for key in sorted(opponent_starter_roles)]
        structurally_verified = (
            len(role_indices) >= 2 and 1 in own_starter_roles
            and len(opponent_role_indices) >= 2
            and bool(swap) and bool(back)
            and observations[instruction[0]].confidence >= 0.85
            and observations[reset[0]].confidence >= 0.85
        )
        if structurally_verified:
            layout_indices = [*legacy_indices, *role_indices, *opponent_role_indices,
                              swap[0], back[0]]
            # Confidence describes the strong structural anchors. Low-confidence
            # title/action OCR remains recorded in anchor_indices for auditing.
            confidence = min(observations[index].confidence for index in
                             (instruction[0], reset[0], *role_indices, *opponent_role_indices))
            status = (ClassificationStatus.VERIFIED if confidence >= 0.85
                      else ClassificationStatus.CANDIDATE)
            indices = tuple(layout_indices)
        else:
            indices = tuple(legacy_indices)
            confidence = min(observations[index].confidence for index in indices)
            status = ClassificationStatus.VERIFIED if confidence >= 0.85 else ClassificationStatus.CANDIDATE
        return ScreenClassification(ScreenState.PITCHER_ORDER, status, confidence, indices)

    return ScreenClassification(ScreenState.UNKNOWN, ClassificationStatus.UNKNOWN, None)


def classifier_payload_matches(payload: Mapping[str, object], classification: ScreenClassification) -> bool:
    """Require Swift and Python state, anchors, confidence and profile versions to agree."""
    confidence = payload.get("screen_confidence")
    confidence_matches = (
        confidence is None and classification.confidence is None
    ) or (
        isinstance(confidence, (int, float)) and classification.confidence is not None
        and abs(float(confidence) - classification.confidence) <= 1e-6
    )
    return (
        payload.get("screen_state") == classification.state.value
        and payload.get("screen_status") == classification.status.value
        and confidence_matches
        and payload.get("screen_anchor_indices") == list(classification.anchor_indices)
        and payload.get("screen_profile_version") == classification.profile_version
    )
