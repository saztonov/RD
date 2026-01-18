"""Manifest models for two-pass OCR algorithm."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CropManifestEntry:
    """Manifest entry for single crop."""

    block_id: str
    crop_path: str
    block_type: str
    page_index: int
    part_idx: int = 0
    total_parts: int = 1
    width: int = 0
    height: int = 0
    pdf_crop_path: Optional[str] = None  # Path to PDF crop for native OCR


@dataclass
class TwoPassManifest:
    """Full manifest for two-pass processing."""

    pdf_path: str
    crops_dir: str
    text_blocks: List[CropManifestEntry] = field(default_factory=list)
    image_blocks: List[CropManifestEntry] = field(default_factory=list)
    total_blocks: int = 0

    def save(self, path: str):
        data = {
            "pdf_path": self.pdf_path,
            "crops_dir": self.crops_dir,
            "total_blocks": self.total_blocks,
            "text_blocks": [
                {
                    "block_id": e.block_id,
                    "crop_path": e.crop_path,
                    "block_type": e.block_type,
                    "page_index": e.page_index,
                    "part_idx": e.part_idx,
                    "total_parts": e.total_parts,
                    "width": e.width,
                    "height": e.height,
                    "pdf_crop_path": e.pdf_crop_path,
                }
                for e in self.text_blocks
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
                    "pdf_crop_path": e.pdf_crop_path,
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

        # Backward compatibility: ignore deprecated strips field
        _ = data.get("strips", [])

        for e in data.get("text_blocks", []):
            manifest.text_blocks.append(
                CropManifestEntry(
                    block_id=e["block_id"],
                    crop_path=e["crop_path"],
                    block_type=e["block_type"],
                    page_index=e["page_index"],
                    part_idx=e.get("part_idx", 0),
                    total_parts=e.get("total_parts", 1),
                    width=e.get("width", 0),
                    height=e.get("height", 0),
                    pdf_crop_path=e.get("pdf_crop_path"),
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
                    pdf_crop_path=e.get("pdf_crop_path"),
                )
            )

        return manifest
