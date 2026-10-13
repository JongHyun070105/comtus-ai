from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum
import re
from typing import Any, Sequence

from .models import EvidenceSource
from .observations import OCRObservation
from .screens import (
    ClassificationStatus,
    NormalizedRect,
    PanelLayout,
    PanelRole,
    ScreenState,
)


EXTRACTION_VERSION = "ocr-field-candidates-v2"
MIN_FIELD_CONFIDENCE = 0.85


class ExtractionStatus(StrEnum):
    VERIFIED = "VERIFIED"
    CANDIDATE = "CANDIDATE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, slots=True)
class FieldCandidate:
    field_key: str
    value: str | int | float | None
    status: ExtractionStatus
    confidence: float | None
    source: EvidenceSource
    observation_indices: tuple[int, ...]
    bbox: tuple[float, float, float, float]
    panel_role: PanelRole = PanelRole.UNKNOWN
    reason: str | None = None
    derivation_version: str = EXTRACTION_VERSION
    raw_value: str | None = None
    year_candidates: tuple[int, ...] = ()
    screen_state: ScreenState | None = None
    screen_status: ClassificationStatus = ClassificationStatus.UNKNOWN
    player_key: str | None = None
    page: int | None = None
    panel_bounds: tuple[float, float, float, float] | None = None

    def context_dict(self) -> dict[str, Any]:
        return {
            "observation_indices": list(self.observation_indices),
            "bbox": list(self.bbox),
            "panel_role": self.panel_role.value,
            "reason": self.reason,
            "instance_identity": "UNRESOLVED",
            "raw_value": self.raw_value,
            "year_candidates": list(self.year_candidates),
            "screen_state": self.screen_state.value if self.screen_state else None,
            "screen_status": self.screen_status.value,
            "player_key": self.player_key,
            "page": self.page,
            "card_panel_bounds": list(self.panel_bounds) if self.panel_bounds else None,
        }


@dataclass(frozen=True, slots=True)
class CardIdentityCandidate:
    canonical_name: str | None
    season_year: int | None
    card_type: str | None = None
    stars: int | None = None
    enhancement: int | None = None
    instance_key: None = None
    status: str = "UNRESOLVED"
    reason: str = "card edition and owned instance are not uniquely grounded"
    player_key: str | None = None
    screen_state: ScreenState | None = None
    page: int | None = None
    panel_bounds: tuple[float, float, float, float] | None = None


@dataclass(frozen=True, slots=True)
class VerifiedFieldContext:
    screen_state: ScreenState
    screen_status: ClassificationStatus
    player_key: str
    page: int
    active_panel: NormalizedRect

    def __post_init__(self) -> None:
        if self.screen_state not in (ScreenState.PLAYER_DETAIL_BATTER, ScreenState.PLAYER_DETAIL_PITCHER):
            raise ValueError("field verification requires a player-detail screen")
        if self.screen_status != ClassificationStatus.VERIFIED:
            raise ValueError("field verification requires a verified screen classification")
        if not self.player_key.strip() or self.page not in (1, 2, 3):
            raise ValueError("field verification requires a player identity and page 1...3")


@dataclass(frozen=True, slots=True)
class SeasonYearResolution:
    status: ExtractionStatus
    value: int | None
    candidates: tuple[int, ...]
    original: str
    reason: str | None = None


KBO_FIRST_SEASON = 1982


_CARD_LABEL = re.compile(
    r"(?P<name>[\w가-힣]+(?:[ .·][\w가-힣]+)*)\s*(?:['’]\s*(?P<short_year>\d{2})|\s+(?P<full_year>(?:19|20)\d{2}))"
)
_NUMBER = re.compile(r"\d{1,3}(?:\.\d{1,2})?")
_ENHANCEMENT = re.compile(r"\+\s*(\d{1,2})")
_CARD_TYPES = {
    "시즌": "SEASON",
    "라이브": "LIVE",
    "시그니처": "SIGNATURE",
    "임팩트": "IMPACT",
    "골든글러브": "GOLDEN_GLOVE",
    "국가대표": "NATIONAL_TEAM",
    "라이브올스타": "LIVE_ALLSTAR",
    "FA임팩트": "FA_IMPACT",
    "FA시그니처": "FA_SIGNATURE",
}


def _compact(text: str) -> str:
    return "".join(character for character in text if not character.isspace())


def _union_bbox(observations: Sequence[OCRObservation]) -> tuple[float, float, float, float]:
    left = min(row.bbox[0] for row in observations)
    bottom = min(row.bbox[1] for row in observations)
    right = max(row.bbox[0] + row.bbox[2] for row in observations)
    top = max(row.bbox[1] + row.bbox[3] for row in observations)
    return left, bottom, right - left, top - bottom


def _panel_role(bbox: tuple[float, float, float, float], active_panel: NormalizedRect | None,
                panel_layout: PanelLayout | None) -> PanelRole:
    if active_panel is not None and panel_layout is not None:
        if active_panel != panel_layout.active:
            return PanelRole.UNKNOWN
        if active_panel.contains(bbox) and panel_layout.role_for(bbox) == PanelRole.ACTIVE:
            return PanelRole.ACTIVE
        return PanelRole.UNKNOWN
    if panel_layout is not None:
        return panel_layout.role_for(bbox)
    if active_panel is not None and active_panel.contains(bbox):
        return PanelRole.ACTIVE
    return PanelRole.UNKNOWN


def _candidate(field_key: str, value: str | int | float, indices: tuple[int, ...],
               observations: Sequence[OCRObservation], active_panel: NormalizedRect | None,
               panel_layout: PanelLayout | None, context: VerifiedFieldContext | None = None,
               *, raw_value: str | None = None, year_candidates: tuple[int, ...] = ()) -> FieldCandidate:
    rows = [observations[index] for index in indices]
    confidences = [row.confidence for row in rows]
    confidence = min(confidences) if all(item is not None for item in confidences) else None
    source = rows[0].source if all(row.source == rows[0].source for row in rows) else EvidenceSource.UNKNOWN
    bbox = _union_bbox(rows)
    role = _panel_role(bbox, active_panel, panel_layout)
    panel = context.active_panel if context else active_panel or (panel_layout.active if panel_layout else None)
    panel_bounds = (panel.x, panel.y, panel.width, panel.height) if panel else None
    if confidence is None:
        return FieldCandidate(field_key, None, ExtractionStatus.UNKNOWN, None, source, indices, bbox, role,
                              "OCR confidence is unavailable", raw_value=raw_value,
                              year_candidates=year_candidates, screen_state=context.screen_state if context else None,
                              screen_status=context.screen_status if context else ClassificationStatus.UNKNOWN,
                              player_key=context.player_key if context else None, page=context.page if context else None,
                              panel_bounds=panel_bounds)
    if confidence < MIN_FIELD_CONFIDENCE:
        return FieldCandidate(field_key, None, ExtractionStatus.LOW_CONFIDENCE, confidence, source, indices, bbox, role,
                              "OCR confidence is below the field threshold", raw_value=raw_value,
                              year_candidates=year_candidates, screen_state=context.screen_state if context else None,
                              screen_status=context.screen_status if context else ClassificationStatus.UNKNOWN,
                              player_key=context.player_key if context else None, page=context.page if context else None,
                              panel_bounds=panel_bounds)
    return FieldCandidate(field_key, value, ExtractionStatus.CANDIDATE, confidence, source, indices, bbox, role,
                          "Field syntax matched; explicit review is required before verification", raw_value=raw_value,
                          year_candidates=year_candidates, screen_state=context.screen_state if context else None,
                          screen_status=context.screen_status if context else ClassificationStatus.UNKNOWN,
                          player_key=context.player_key if context else None, page=context.page if context else None,
                          panel_bounds=panel_bounds)


def resolve_season_year(raw: str, *, reference_year: int | None = None,
                        first_season: int = KBO_FIRST_SEASON) -> SeasonYearResolution:
    """Resolve a card year only when it fits the known KBO season window.

    The reference year bounds plausible card seasons; it is never used as a
    substitute when the card text contains no year.
    """
    reference = date.today().year if reference_year is None else reference_year
    if first_season < 1900 or reference < first_season or reference > 9999:
        raise ValueError("season-year bounds are invalid")
    original = raw.strip()
    match = re.fullmatch(r"(?:['’]\s*)?(\d{2}|(?:19|20|21)\d{2})", original)
    if not match:
        return SeasonYearResolution(ExtractionStatus.UNRESOLVED, None, (), original,
                                    "year token is not a two- or four-digit season year")
    token = match.group(1)
    if len(token) == 4:
        year = int(token)
        candidates = (year,) if first_season <= year <= reference else ()
    else:
        short_year = int(token)
        candidates = tuple(year for year in range(first_season, reference + 1) if year % 100 == short_year)
    if len(candidates) == 1:
        return SeasonYearResolution(ExtractionStatus.CANDIDATE, candidates[0], candidates, original)
    reason = "year has no season in the configured KBO range" if not candidates else "year maps to multiple seasons"
    return SeasonYearResolution(ExtractionStatus.UNRESOLVED, None, candidates, original, reason)


def _parse_card_label(index: int, observation: OCRObservation, observations: Sequence[OCRObservation],
                      active_panel: NormalizedRect | None, panel_layout: PanelLayout | None,
                      context: VerifiedFieldContext | None, reference_year: int) -> list[FieldCandidate]:
    match = _CARD_LABEL.fullmatch(observation.text.strip())
    if not match:
        return []
    name = match.group("name").strip(" .·")
    year_text = match.group("short_year") or match.group("full_year")
    resolution = resolve_season_year("'" + year_text if match.group("short_year") else year_text,
                                     reference_year=reference_year)
    year_candidate = _candidate("season_year", resolution.value if resolution.value is not None else 0,
                                (index,), observations, active_panel, panel_layout, context,
                                raw_value=observation.text, year_candidates=resolution.candidates)
    if resolution.status == ExtractionStatus.UNRESOLVED:
        year_candidate = replace(year_candidate, value=None, status=ExtractionStatus.UNRESOLVED,
                                 reason=resolution.reason)
    return [
        _candidate("player_name", name, (index,), observations, active_panel, panel_layout, context,
                   raw_value=observation.text),
        year_candidate,
    ]


def _parse_ovr(observations: Sequence[OCRObservation], active_panel: NormalizedRect | None,
               panel_layout: PanelLayout | None, context: VerifiedFieldContext | None) -> list[FieldCandidate]:
    labels: list[tuple[int, str]] = []
    for index, observation in enumerate(observations):
        compact = _compact(observation.text).upper()
        if "OVR" in compact:
            key = "opponent_batter_ovr" if "상대타자" in compact else "overall"
            labels.append((index, key))

    result: list[FieldCandidate] = []
    # OVR values are associated only inside a measured active card panel.
    if active_panel is None and panel_layout is None:
        return result
    for number_index, observation in enumerate(observations):
        text = observation.text.strip()
        if not _NUMBER.fullmatch(text):
            continue
        x = observation.bbox[0] + observation.bbox[2] / 2
        y = observation.bbox[1] + observation.bbox[3] / 2
        matches: list[tuple[float, int, str]] = []
        number_role = _panel_role(observation.bbox, active_panel, panel_layout)
        if number_role != PanelRole.ACTIVE:
            continue
        for label_index, field_key in labels:
            label = observations[label_index]
            if _panel_role(label.bbox, active_panel, panel_layout) != PanelRole.ACTIVE:
                continue
            label_x = label.bbox[0] + label.bbox[2] / 2
            label_y = label.bbox[1] + label.bbox[3] / 2
            distance = abs(x - label_x) + abs(y - label_y)
            if abs(x - label_x) <= 0.14 and abs(y - label_y) <= 0.14:
                matches.append((distance, label_index, field_key))
        if not matches:
            continue
        matches.sort()
        if len(matches) > 1 and abs(matches[0][0] - matches[1][0]) <= 0.005:
            label_indices = tuple(sorted(item[1] for item in matches if abs(item[0] - matches[0][0]) <= 0.005))
            result.append(FieldCandidate("overall", None, ExtractionStatus.AMBIGUOUS, None,
                                         EvidenceSource.UNKNOWN, (number_index, *label_indices),
                                         _union_bbox([observations[item] for item in (number_index, *label_indices)]),
                                         _panel_role(observation.bbox, active_panel, panel_layout),
                                         "Multiple OVR labels are equally close"))
            continue
        _, label_index, field_key = matches[0]
        try:
            value = float(text) if "." in text else int(text)
        except ValueError:
            continue
        if not 0 <= value <= 200:
            continue
        result.append(_candidate(field_key, value, (number_index, label_index), observations, active_panel,
                                 panel_layout, context, raw_value=text))
    return result


def parse_ocr_fields(observations: Sequence[OCRObservation], *, active_panel: NormalizedRect | None = None,
                     panel_layout: PanelLayout | None = None, context: VerifiedFieldContext | None = None,
                     reference_year: int | None = None) -> tuple[FieldCandidate, ...]:
    """Extract syntax-level candidates without promoting them to player facts."""
    if context is not None and active_panel is not None and active_panel != context.active_panel:
        raise ValueError("active panel must match the verified field context")
    active_panel = context.active_panel if context else active_panel
    season_reference = date.today().year if reference_year is None else reference_year
    result: list[FieldCandidate] = []
    for index, observation in enumerate(observations):
        result.extend(_parse_card_label(index, observation, observations, active_panel, panel_layout,
                                        context, season_reference))

        compact = _compact(observation.text).upper()
        card_type = _CARD_TYPES.get(compact)
        if card_type is not None:
            result.append(_candidate("card_type", card_type, (index,), observations, active_panel, panel_layout,
                                     context, raw_value=observation.text))

        stars = re.fullmatch(r"[★⭐]{1,5}", observation.text.strip())
        ordinal_stars = re.fullmatch(r"별\s*([1-5])", observation.text.strip())
        if stars or ordinal_stars:
            value = len(stars.group(0)) if stars else int(ordinal_stars.group(1))  # type: ignore[union-attr]
            result.append(_candidate("stars", value, (index,), observations, active_panel, panel_layout,
                                     context, raw_value=observation.text))

        enhancement = _ENHANCEMENT.fullmatch(observation.text.strip())
        if enhancement:
            value = int(enhancement.group(1))
            result.append(_candidate("enhancement", value, (index,), observations, active_panel, panel_layout,
                                     context, raw_value=observation.text))

    result.extend(_parse_ovr(observations, active_panel, panel_layout, context))
    return tuple(result)


def verify_field_candidate(candidate: FieldCandidate) -> FieldCandidate:
    """Promote a candidate only when identity, page, screen and panel all agree."""
    if candidate.status != ExtractionStatus.CANDIDATE or candidate.value is None:
        raise ValueError("only non-empty candidates can be verified")
    if (candidate.screen_status != ClassificationStatus.VERIFIED
            or candidate.screen_state not in (ScreenState.PLAYER_DETAIL_BATTER, ScreenState.PLAYER_DETAIL_PITCHER)
            or not candidate.player_key or candidate.page not in (1, 2, 3)
            or candidate.panel_role != PanelRole.ACTIVE or candidate.panel_bounds is None):
        raise ValueError("verified player identity, page, detail screen and active panel are required")
    return replace(candidate, status=ExtractionStatus.VERIFIED,
                   reason="field was explicitly reviewed against the verified player, page and active card panel")


def card_identity_candidate(fields: Sequence[FieldCandidate]) -> CardIdentityCandidate:
    """Keep master and owned-card identity separate; never invent an instance key."""
    labels = [field for field in fields if field.field_key in ("player_name", "season_year")
              and field.status == ExtractionStatus.CANDIDATE]
    label_indices = {field.observation_indices for field in labels}
    panel_bounds = {field.panel_bounds for field in labels}
    panel_roles = {field.panel_role for field in labels}
    player_keys = {field.player_key for field in labels}
    screen_states = {field.screen_state for field in labels}
    pages = {field.page for field in labels}
    if (len(label_indices) != 1 or len(panel_bounds) != 1 or None in panel_bounds
            or panel_roles != {PanelRole.ACTIVE} or not labels):
        reason = ("player label is missing or multiple cards could be merged" if len(label_indices) > 1
                  else "player label is not grounded to exactly one active card panel")
        return CardIdentityCandidate(None, None, None, None, None,
                                     reason=reason)
    by_key = {field.field_key: field.value for field in labels}
    return CardIdentityCandidate(
        canonical_name=by_key.get("player_name") if isinstance(by_key.get("player_name"), str) else None,
        season_year=by_key.get("season_year") if isinstance(by_key.get("season_year"), int) else None,
        player_key=next(iter(player_keys)) if len(player_keys) == 1 else None,
        screen_state=next(iter(screen_states)) if len(screen_states) == 1 else None,
        page=next(iter(pages)) if len(pages) == 1 else None,
        panel_bounds=next(iter(panel_bounds)),
    )
