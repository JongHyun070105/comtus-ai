from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .models import EvidenceSource, validate_confidence


@dataclass(frozen=True, slots=True)
class OCRObservation:
    text: str
    confidence: float | None
    bbox: tuple[float, float, float, float]
    source: EvidenceSource
    schema_version: int = 1
    field: str | None = None

    def __post_init__(self) -> None:
        validate_confidence(self.confidence)
        if len(self.bbox) != 4 or any(not 0 <= n <= 1 for n in self.bbox):
            raise ValueError("bbox must contain normalized x, y, width, height values")
        if self.bbox[0] + self.bbox[2] > 1.000001 or self.bbox[1] + self.bbox[3] > 1.000001:
            raise ValueError("bbox must fit within the normalized frame")
        if self.schema_version != 1:
            raise ValueError("unsupported OCR schema_version")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> OCRObservation:
        if value.get("schema_version") != 1:
            raise ValueError("unsupported OCR schema_version")
        bbox = value.get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            raise ValueError("bbox must be a four-element array")
        try:
            raw_source = value.get("source", "UNKNOWN")
            # Swift identifies the OCR engine as "vision". That is not an
            # evidence provenance claim, so keep it separate from trusted
            # evidence-source values and fail closed to UNKNOWN.
            source = EvidenceSource.UNKNOWN if raw_source == "vision" else EvidenceSource(raw_source)
            confidence = value.get("confidence")
            return cls(
                text=str(value["text"]),
                confidence=None if confidence is None else float(confidence),
                bbox=tuple(float(n) for n in bbox),  # type: ignore[arg-type]
                source=source,
                schema_version=1,
                field=value.get("field"),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"invalid OCR observation: {error}") from error


def load_ocr_document(raw: str) -> tuple[OCRObservation, ...]:
    document = json.loads(raw)
    if document.get("schema_version") != 1:
        raise ValueError("unsupported OCR document schema_version")
    observations = document.get("observations")
    if not isinstance(observations, list):
        raise ValueError("observations must be an array")
    return tuple(OCRObservation.from_dict(row) for row in observations)
