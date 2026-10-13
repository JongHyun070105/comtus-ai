from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Any, Sequence

from .models import EvidenceSource
from .observations import OCRObservation
from .screens import NormalizedRect, PanelLayout, PanelRole


EXTRACTION_VERSION = "ocr-field-candidates-v1"
MIN_FIELD_CONFIDENCE = 0.85


class ExtractionStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"


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

    def context_dict(self) -> dict[str, Any]:
        return {
            "observation_indices": list(self.observation_indices),
            "bbox": list(self.bbox),
            "panel_role": self.panel_role.value,
            "reason": self.reason,
            "instance_identity": "UNRESOLVED",
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
    if active_panel is not None and active_panel.contains(bbox):
        return PanelRole.ACTIVE
    if panel_layout is not None:
        return panel_layout.role_for(bbox)
    return PanelRole.UNKNOWN


def _candidate(field_key: str, value: str | int | float, indices: tuple[int, ...],
               observations: Sequence[OCRObservation], active_panel: NormalizedRect | None,
               panel_layout: PanelLayout | None) -> FieldCandidate:
    rows = [observations[index] for index in indices]
    confidences = [row.confidence for row in rows]
    confidence = min(confidences) if all(item is not None for item in confidences) else None
    source = rows[0].source if all(row.source == rows[0].source for row in rows) else EvidenceSource.UNKNOWN
    bbox = _union_bbox(rows)
    role = _panel_role(bbox, active_panel, panel_layout)
    if confidence is None:
        return FieldCandidate(field_key, None, ExtractionStatus.UNKNOWN, None, source, indices, bbox, role,
                              "OCR confidence is unavailable")
    if confidence < MIN_FIELD_CONFIDENCE:
        return FieldCandidate(field_key, None, ExtractionStatus.LOW_CONFIDENCE, confidence, source, indices, bbox, role,
                              "OCR confidence is below the field threshold")
    return FieldCandidate(field_key, value, ExtractionStatus.CANDIDATE, confidence, source, indices, bbox, role,
                          "Field syntax matched; screen/player/page identity is not verified")


def _parse_card_label(index: int, observation: OCRObservation, observations: Sequence[OCRObservation],
                      active_panel: NormalizedRect | None, panel_layout: PanelLayout | None) -> list[FieldCandidate]:
    match = _CARD_LABEL.fullmatch(observation.text.strip())
    if not match:
        return []
    name = match.group("name").strip(" .·")
    short_year = match.group("short_year")
    year_text = match.group("full_year")
    year = int(year_text) if year_text else 2000 + int(short_year)
    return [
        _candidate("player_name", name, (index,), observations, active_panel, panel_layout),
        _candidate("season_year", year, (index,), observations, active_panel, panel_layout),
    ]


def _parse_ovr(observations: Sequence[OCRObservation], active_panel: NormalizedRect | None,
               panel_layout: PanelLayout | None) -> list[FieldCandidate]:
    labels: list[tuple[int, str]] = []
    for index, observation in enumerate(observations):
        compact = _compact(observation.text).upper()
        if "OVR" in compact:
            key = "opponent_batter_ovr" if "상대타자" in compact else "overall"
            labels.append((index, key))

    result: list[FieldCandidate] = []
    for number_index, observation in enumerate(observations):
        text = observation.text.strip()
        if not _NUMBER.fullmatch(text):
            continue
        x = observation.bbox[0] + observation.bbox[2] / 2
        y = observation.bbox[1] + observation.bbox[3] / 2
        matches: list[tuple[float, int, str]] = []
        for label_index, field_key in labels:
            label = observations[label_index]
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
        result.append(_candidate(field_key, value, (number_index, label_index), observations, active_panel, panel_layout))
    return result


def parse_ocr_fields(observations: Sequence[OCRObservation], *, active_panel: NormalizedRect | None = None,
                     panel_layout: PanelLayout | None = None) -> tuple[FieldCandidate, ...]:
    """Extract syntax-level candidates without promoting them to player facts."""
    result: list[FieldCandidate] = []
    for index, observation in enumerate(observations):
        result.extend(_parse_card_label(index, observation, observations, active_panel, panel_layout))

        compact = _compact(observation.text).upper()
        card_type = _CARD_TYPES.get(compact)
        if card_type is not None:
            result.append(_candidate("card_type", card_type, (index,), observations, active_panel, panel_layout))

        stars = re.fullmatch(r"[★⭐]{1,5}", observation.text.strip())
        ordinal_stars = re.fullmatch(r"별\s*([1-5])", observation.text.strip())
        if stars or ordinal_stars:
            value = len(stars.group(0)) if stars else int(ordinal_stars.group(1))  # type: ignore[union-attr]
            result.append(_candidate("stars", value, (index,), observations, active_panel, panel_layout))

        enhancement = _ENHANCEMENT.fullmatch(observation.text.strip())
        if enhancement:
            value = int(enhancement.group(1))
            result.append(_candidate("enhancement", value, (index,), observations, active_panel, panel_layout))

    result.extend(_parse_ovr(observations, active_panel, panel_layout))
    return tuple(result)


def card_identity_candidate(fields: Sequence[FieldCandidate]) -> CardIdentityCandidate:
    """Keep master and owned-card identity separate; never invent an instance key."""
    labels = [field for field in fields if field.field_key in ("player_name", "season_year")
              and field.status == ExtractionStatus.CANDIDATE]
    label_indices = {field.observation_indices for field in labels}
    if len(label_indices) != 1 or not labels:
        return CardIdentityCandidate(None, None, None, None, None,
                                     reason="player label is missing or multiple cards could be merged")
    by_key = {field.field_key: field.value for field in labels}
    return CardIdentityCandidate(
        canonical_name=by_key.get("player_name") if isinstance(by_key.get("player_name"), str) else None,
        season_year=by_key.get("season_year") if isinstance(by_key.get("season_year"), int) else None,
    )
