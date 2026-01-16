"""Генерация QA манифеста для OCR результатов.

Манифест содержит метаданные всех блоков (кроме штампов) с точными R2 ключами
для кропов, что позволяет Q&A приложению использовать точные URL вместо
угадывания по шаблону.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0"


def _compute_file_sha256(file_path: Path) -> Optional[str]:
    """Вычислить SHA256 хеш файла.

    Args:
        file_path: путь к файлу

    Returns:
        Hex-строка SHA256 хеша или None при ошибке
    """
    if not file_path.exists():
        return None
    try:
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
    except Exception as e:
        logger.warning(f"Failed to compute SHA256 for {file_path}: {e}")
        return None


def generate_qa_manifest(
    work_dir: Path,
    r2_prefix: str,
    job_id: str,
    node_id: Optional[str] = None,
) -> Optional[Path]:
    """Генерировать qa_manifest.json из annotation.json и кропов.

    Args:
        work_dir: рабочая директория с результатами OCR
        r2_prefix: префикс R2 (например tree_docs/{node_id}/ocr_runs/{job_id})
        job_id: ID задачи OCR
        node_id: ID узла документа (опционально)

    Returns:
        Path к сгенерированному qa_manifest.json или None при ошибке
    """
    annotation_path = work_dir / "annotation.json"
    if not annotation_path.exists():
        logger.warning(f"annotation.json не найден: {annotation_path}")
        return None

    try:
        with open(annotation_path, "r", encoding="utf-8") as f:
            ann = json.load(f)
    except Exception as e:
        logger.error(f"Ошибка чтения annotation.json: {e}")
        return None

    # Определяем директорию с кропами (приоритет crops_final)
    crops_dir = work_dir / "crops_final"
    if not crops_dir.exists():
        crops_dir = work_dir / "crops"
        if not crops_dir.exists():
            crops_dir = None

    # Генерируем записи манифеста
    manifest_blocks: List[Dict[str, Any]] = []

    for page in ann.get("pages", []):
        page_index = page.get("page_index", 0)
        page_number = page_index + 1  # 1-based

        for blk in page.get("blocks", []):
            block_id = blk.get("id")
            block_type = blk.get("block_type", "text")
            category_code = blk.get("category_code")

            # Пропускаем штампы
            if category_code == "stamp":
                continue

            entry: Dict[str, Any] = {
                "block_id": block_id,
                "page_index": page_index,
                "page_number": page_number,
                "block_type": block_type,
                "coords_norm": blk.get("coords_norm"),
            }

            # Добавляем опциональные поля группы
            if blk.get("group_id"):
                entry["group_id"] = blk["group_id"]
            if blk.get("group_name"):
                entry["group_name"] = blk["group_name"]

            # Добавляем linked_block_id если есть
            if blk.get("linked_block_id"):
                entry["linked_block_id"] = blk["linked_block_id"]

            # Для IMAGE блоков добавляем информацию о кропе
            if block_type == "image" and crops_dir:
                crop_file = crops_dir / f"{block_id}.pdf"
                if crop_file.exists():
                    entry["crop_r2_key"] = f"{r2_prefix}/crops/{block_id}.pdf"
                    entry["content_type"] = "application/pdf"
                    sha256 = _compute_file_sha256(crop_file)
                    if sha256:
                        entry["sha256"] = sha256

            manifest_blocks.append(entry)

    # Формируем итоговый манифест
    now = datetime.utcnow().isoformat() + "Z"

    manifest: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "created_at": now,
        "job_id": job_id,
        "blocks": manifest_blocks,
    }

    if node_id:
        manifest["node_id"] = node_id

    # Записываем манифест
    manifest_path = work_dir / "qa_manifest.json"
    try:
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        logger.info(
            f"qa_manifest.json сгенерирован: {manifest_path} ({len(manifest_blocks)} блоков)"
        )
        return manifest_path
    except Exception as e:
        logger.error(f"Ошибка записи qa_manifest.json: {e}")
        return None
