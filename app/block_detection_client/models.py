"""Модели данных для Block Detection API."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class DetectedBlock:
    """Обнаруженный блок из API детекции."""

    bounding_box: Tuple[float, float, float, float]  # x1, y1, x2, y2 normalized [0-1]
    block_type: str  # "text", "image", "table", "unknown"
    raw_label: str = ""

    @classmethod
    def from_api_response(cls, data: dict) -> "DetectedBlock":
        """Создать из ответа API."""
        bbox = data.get("bounding_box", {})
        return cls(
            bounding_box=(
                bbox.get("x1", 0.0),
                bbox.get("y1", 0.0),
                bbox.get("x2", 0.0),
                bbox.get("y2", 0.0),
            ),
            block_type=data.get("block_type", "unknown"),
            raw_label=data.get("raw_label", ""),
        )


@dataclass
class DetectionResult:
    """Результат детекции блоков."""

    blocks: List[DetectedBlock]
    image_width: int
    image_height: int
    processing_time_ms: float = 0.0
    success: bool = True

    @classmethod
    def from_api_response(cls, data: dict) -> "DetectionResult":
        """Создать из ответа API."""
        blocks = [
            DetectedBlock.from_api_response(b) for b in data.get("blocks", [])
        ]
        return cls(
            blocks=blocks,
            image_width=data.get("image_width", 0),
            image_height=data.get("image_height", 0),
            processing_time_ms=data.get("processing_time_ms", 0.0),
            success=data.get("success", True),
        )
