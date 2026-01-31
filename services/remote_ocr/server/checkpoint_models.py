"""
Модели для checkpoint/resume системы OCR.

Позволяет сохранять прогресс обработки и восстанавливать его после паузы.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

from .logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class OCRCheckpoint:
    """
    Checkpoint для сохранения прогресса OCR обработки.

    Позволяет:
    - Сохранять состояние между PASS1 и PASS2
    - Восстанавливать обработку после паузы
    - Пропускать уже обработанные элементы
    """

    job_id: str
    phase: str  # "pass1", "pass2_strips", "pass2_images", "verification", "completed"

    # Обработанные элементы (strip_id или block_id)
    processed_strips: Set[str] = field(default_factory=set)
    processed_images: Set[str] = field(default_factory=set)

    # Частичные результаты: block_id -> ocr_text
    partial_results: Dict[str, str] = field(default_factory=dict)

    # Частичные результаты по частям (для split блоков)
    # block_id -> {part_idx: text}
    partial_parts: Dict[str, Dict[int, str]] = field(default_factory=dict)

    # Метаданные
    manifest_path: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    # Статистика
    total_strips: int = 0
    total_images: int = 0

    def is_strip_processed(self, strip_id: str) -> bool:
        """Проверить, обработан ли strip"""
        return strip_id in self.processed_strips

    def is_image_processed(self, block_id: str) -> bool:
        """Проверить, обработан ли image блок"""
        return block_id in self.processed_images

    def mark_strip_processed(self, strip_id: str, block_results: Dict[str, str] = None):
        """Отметить strip как обработанный"""
        self.processed_strips.add(strip_id)
        if block_results:
            for block_id, text in block_results.items():
                self.partial_results[block_id] = text
        self.updated_at = datetime.utcnow().isoformat()

    def mark_image_processed(
        self, block_id: str, text: str, part_idx: int = 0, total_parts: int = 1
    ):
        """Отметить image блок как обработанный"""
        if total_parts == 1:
            self.partial_results[block_id] = text
            self.processed_images.add(block_id)
        else:
            # Для split блоков сохраняем части
            if block_id not in self.partial_parts:
                self.partial_parts[block_id] = {}
            self.partial_parts[block_id][part_idx] = text

            # Проверяем, все ли части собраны
            if len(self.partial_parts[block_id]) >= total_parts:
                combined = [
                    self.partial_parts[block_id].get(i, "")
                    for i in range(total_parts)
                ]
                self.partial_results[block_id] = "\n\n".join(combined)
                self.processed_images.add(block_id)

        self.updated_at = datetime.utcnow().isoformat()

    def get_pending_strips(self, all_strip_ids: List[str]) -> List[str]:
        """Получить список необработанных strips"""
        return [s for s in all_strip_ids if s not in self.processed_strips]

    def get_pending_images(self, all_block_ids: List[str]) -> List[str]:
        """Получить список необработанных image блоков"""
        return [b for b in all_block_ids if b not in self.processed_images]

    def get_progress(self) -> Dict[str, float]:
        """Получить прогресс обработки"""
        total = self.total_strips + self.total_images
        if total == 0:
            return {"strips": 0.0, "images": 0.0, "total": 0.0}

        strips_done = len(self.processed_strips)
        images_done = len(self.processed_images)

        return {
            "strips": strips_done / self.total_strips if self.total_strips > 0 else 1.0,
            "images": images_done / self.total_images if self.total_images > 0 else 1.0,
            "total": (strips_done + images_done) / total,
        }

    def save(self, path: Path) -> bool:
        """
        Сохранить checkpoint в файл.

        Использует атомарную запись (write to tmp, then rename).
        """
        try:
            data = {
                "job_id": self.job_id,
                "phase": self.phase,
                "processed_strips": list(self.processed_strips),
                "processed_images": list(self.processed_images),
                "partial_results": self.partial_results,
                "partial_parts": {
                    k: {str(pi): pv for pi, pv in v.items()}
                    for k, v in self.partial_parts.items()
                },
                "manifest_path": self.manifest_path,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "total_strips": self.total_strips,
                "total_images": self.total_images,
            }

            # Атомарная запись
            tmp_path = path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            # Rename (атомарно на большинстве FS)
            os.replace(tmp_path, path)

            logger.debug(
                f"Checkpoint saved: {path}",
                extra={
                    "job_id": self.job_id,
                    "phase": self.phase,
                    "processed_strips": len(self.processed_strips),
                    "processed_images": len(self.processed_images),
                },
            )
            return True

        except Exception as e:
            logger.error(f"Failed to save checkpoint: {e}", exc_info=True)
            return False

    @classmethod
    def load(cls, path: Path) -> Optional["OCRCheckpoint"]:
        """Загрузить checkpoint из файла"""
        if not path.exists():
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            checkpoint = cls(
                job_id=data["job_id"],
                phase=data["phase"],
                processed_strips=set(data.get("processed_strips", [])),
                processed_images=set(data.get("processed_images", [])),
                partial_results=data.get("partial_results", {}),
                partial_parts={
                    k: {int(pi): pv for pi, pv in v.items()}
                    for k, v in data.get("partial_parts", {}).items()
                },
                manifest_path=data.get("manifest_path"),
                created_at=data.get("created_at", datetime.utcnow().isoformat()),
                updated_at=data.get("updated_at", datetime.utcnow().isoformat()),
                total_strips=data.get("total_strips", 0),
                total_images=data.get("total_images", 0),
            )

            logger.info(
                f"Checkpoint loaded: {path}",
                extra={
                    "job_id": checkpoint.job_id,
                    "phase": checkpoint.phase,
                    "processed_strips": len(checkpoint.processed_strips),
                    "processed_images": len(checkpoint.processed_images),
                },
            )
            return checkpoint

        except Exception as e:
            logger.error(f"Failed to load checkpoint: {e}", exc_info=True)
            return None

    @classmethod
    def create_new(
        cls,
        job_id: str,
        total_strips: int = 0,
        total_images: int = 0,
        manifest_path: str = None,
    ) -> "OCRCheckpoint":
        """Создать новый checkpoint"""
        return cls(
            job_id=job_id,
            phase="pass1",
            total_strips=total_strips,
            total_images=total_images,
            manifest_path=manifest_path,
        )

    def apply_to_blocks(self, blocks: List) -> int:
        """
        Применить сохранённые результаты к блокам.

        Returns:
            Количество блоков с восстановленными результатами
        """
        applied = 0
        blocks_by_id = {b.id: b for b in blocks}

        for block_id, ocr_text in self.partial_results.items():
            if block_id in blocks_by_id:
                blocks_by_id[block_id].ocr_text = ocr_text
                applied += 1

        logger.info(
            f"Checkpoint applied: {applied} blocks restored",
            extra={"job_id": self.job_id},
        )
        return applied


def get_checkpoint_path(work_dir: Path) -> Path:
    """Получить путь к файлу checkpoint"""
    return work_dir / "ocr_checkpoint.json"
