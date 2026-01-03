"""Модели манифестов для двухпроходного алгоритма OCR"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List


@dataclass
class CropManifestEntry:
    """Запись в manifest для одного кропа"""

    block_id: str
    crop_path: str
    block_type: str
    page_index: int
    part_idx: int = 0
    total_parts: int = 1
    width: int = 0
    height: int = 0


@dataclass
class StripManifestEntry:
    """Запись в manifest для полосы (merged strip)"""

    strip_id: str
    strip_path: str
    block_ids: List[str] = field(default_factory=list)
    block_parts: List[dict] = field(
        default_factory=list
    )  # [{block_id, part_idx, total_parts}]


@dataclass
class TwoPassManifest:
    """Полный manifest двухпроходной обработки"""

    pdf_path: str
    crops_dir: str
    strips: List[StripManifestEntry] = field(default_factory=list)
    image_blocks: List[CropManifestEntry] = field(default_factory=list)
    total_blocks: int = 0

    def save(self, path: str):
        data = {
            "pdf_path": self.pdf_path,
            "crops_dir": self.crops_dir,
            "total_blocks": self.total_blocks,
            "strips": [
                {
                    "strip_id": s.strip_id,
                    "strip_path": s.strip_path,
                    "block_ids": s.block_ids,
                    "block_parts": s.block_parts,
                }
                for s in self.strips
            ],
            "image_blocks": [
                {
                    "block_id": e.block_id,
                    "crop_path": e.crop_path,
                    "block_type": e.block_type,
                    "page_index": e.page_index,
                    "part_idx": e.part_idx,
                    "total_parts": e.total_parts,
                    "width": e.width,
                    "height": e.height,
                }
                for e in self.image_blocks
            ],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "TwoPassManifest":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        manifest = cls(
            pdf_path=data["pdf_path"],
            crops_dir=data["crops_dir"],
            total_blocks=data.get("total_blocks", 0),
        )

        for s in data.get("strips", []):
            manifest.strips.append(
                StripManifestEntry(
                    strip_id=s["strip_id"],
                    strip_path=s["strip_path"],
                    block_ids=s.get("block_ids", []),
                    block_parts=s.get("block_parts", []),
                )
            )

        for e in data.get("image_blocks", []):
            manifest.image_blocks.append(
                CropManifestEntry(
                    block_id=e["block_id"],
                    crop_path=e["crop_path"],
                    block_type=e["block_type"],
                    page_index=e["page_index"],
                    part_idx=e.get("part_idx", 0),
                    total_parts=e.get("total_parts", 1),
                    width=e.get("width", 0),
                    height=e.get("height", 0),
                )
            )

        return manifest
