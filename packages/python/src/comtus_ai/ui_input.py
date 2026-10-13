"""Fail-closed UI target rules shared by live and simulated navigation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
import re

from .navigation import UIAction
from .screens import ClassificationStatus, NormalizedRect, ScreenClassification, ScreenState


PITCHER_ORDER_LAYOUT_VERSION = "pitcher-order-layout-v1"
FIRST_STARTER_CARD_BOUNDS = NormalizedRect(0.145, 0.600, 0.122, 0.2067)

# Measured from the preserved V26 pitcher-order frame. All coordinates are
# normalized to the captured game window, so Retina pixels never enter plans.
PITCHER_ORDER_BLOCKED_CONTROLS = (
    NormalizedRect(0.145, 0.030, 0.180, 0.060),  # 원래대로
    NormalizedRect(0.320, 0.030, 0.190, 0.060),  # 선수 교체
    NormalizedRect(0.495, 0.030, 0.200, 0.060),  # 저장
    NormalizedRect(0.000, 0.000, 1.000, 0.025),  # 뒤로 가기
)


class AccountStateChangingAction(StrEnum):
    """Actions with side effects. This type is deliberately not accepted by a click plan."""

    START_MATCH = "START_MATCH"
    CONSUME_CHALLENGE_ATTEMPT = "CONSUME_CHALLENGE_ATTEMPT"
    CONFIRM_PLAYER_SWAP = "CONFIRM_PLAYER_SWAP"
    SAVE_STARTER_ORDER = "SAVE_STARTER_ORDER"
    RESET_STARTER_ORDER = "RESET_STARTER_ORDER"
    ENHANCE_PLAYER = "ENHANCE_PLAYER"
    TRAIN_PLAYER = "TRAIN_PLAYER"
    COMBINE_PLAYER = "COMBINE_PLAYER"
    RELEASE_PLAYER = "RELEASE_PLAYER"
    SPEND_CURRENCY = "SPEND_CURRENCY"
    PURCHASE_ITEM = "PURCHASE_ITEM"
    CHANGE_ACCOUNT_SETTINGS = "CHANGE_ACCOUNT_SETTINGS"


class SafeTargetKind(StrEnum):
    FIRST_STARTER_CARD = "FIRST_STARTER_CARD"


@dataclass(frozen=True, slots=True)
class LocalizedActionTarget:
    kind: SafeTargetKind
    action: UIAction
    screen_state: ScreenState
    bounds: NormalizedRect
    layout_profile_version: str
    label: str
    evidence_sha256: str
    localization_confidence: float

    def authorize(self, classification: ScreenClassification, *, identity_confidence: float) -> tuple[bool, str]:
        if not isinstance(self.action, UIAction):
            return False, "action is outside the safe navigation enum"
        if classification.state != self.screen_state or classification.status != ClassificationStatus.VERIFIED:
            return False, "current screen is not verified for this target"
        if classification.profile_version != "screen-profiles-v3":
            return False, "screen profile version is not current"
        if self.kind != SafeTargetKind.FIRST_STARTER_CARD or self.action != UIAction.OPEN_STARTER_DETAIL:
            return False, "target/action pair is not allowlisted"
        if self.screen_state != ScreenState.PITCHER_ORDER:
            return False, "starter card target is valid only on pitcher order"
        if self.layout_profile_version != PITCHER_ORDER_LAYOUT_VERSION:
            return False, "click area profile version is not current"
        if self.bounds != FIRST_STARTER_CARD_BOUNDS:
            return False, "target bounds do not match the measured first-card region"
        if not re.fullmatch(r"[0-9a-f]{64}", self.evidence_sha256):
            return False, "target lacks a valid source-image hash"
        if (not math.isfinite(self.localization_confidence)
                or self.localization_confidence < 0.95):
            return False, "target localization confidence is too low"
        if self.label != "후라도'26":
            return False, "first-card identity does not match the reviewed image"
        if not math.isfinite(identity_confidence) or identity_confidence < 0.90:
            return False, "current player identity is not verified"
        if any(_overlaps(self.bounds, blocked) for blocked in PITCHER_ORDER_BLOCKED_CONTROLS):
            return False, "target overlaps a blocked account-state control"
        return True, "safe target verified"


def _overlaps(left: NormalizedRect, right: NormalizedRect) -> bool:
    return (min(left.x + left.width, right.x + right.width) > max(left.x, right.x)
            and min(left.y + left.height, right.y + right.height) > max(left.y, right.y))
