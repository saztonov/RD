"""Document service — загрузка, сохранение и миграция аннотаций.

Извлечён из FileOperationsMixin. Инкапсулирует бизнес-логику работы
с аннотациями: 3-source fallback, миграция форматов, PDF status.
GUI вызывает DocumentService вместо прямого обращения к AnnotationDBIO/R2/TreeClient.
"""
from __future__ import annotations

import json
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class AnnotationLoadResult:
    """Результат загрузки аннотации."""
    success: bool
    document: object | None = None  # Document
    source: str = ""  # "supabase", "json_migration", "r2_migration", "empty"
    message: str = ""


class DocumentService:
    """Сервис загрузки/сохранения аннотаций.

    Инкапсулирует 3-source fallback:
    1. Supabase (AnnotationDBIO)
    2. Локальный JSON (миграция)
    3. R2 Storage (миграция)
    """

    def load_annotation(
        self,
        node_id: Optional[str],
        pdf_path: str,
        r2_key: str = "",
    ) -> AnnotationLoadResult:
        """Загрузить аннотацию из доступных источников.

        Returns:
            AnnotationLoadResult с документом и источником.
        """
        # 1. Supabase
        if node_id:
            result = self._load_from_supabase(node_id)
            if result.success:
                return result

        # 2. Локальный JSON → миграция в Supabase
        if node_id:
            result = self._load_from_local_json(node_id, pdf_path)
            if result.success:
                return result

        # 3. R2 → миграция в Supabase
        if r2_key and node_id:
            result = self._load_from_r2(node_id, r2_key)
            if result.success:
                return result

        return AnnotationLoadResult(success=False, source="empty")

    def save_annotation(
        self,
        document: object,  # Document
        node_id: Optional[str],
    ) -> bool:
        """Сохранить аннотацию в Supabase."""
        if not node_id:
            return False

        from app.annotation_db import AnnotationDBIO

        return AnnotationDBIO.save_to_db(document, node_id)

    def update_pdf_status(
        self,
        node_id: str,
        r2_key: str,
    ) -> tuple[str, str]:
        """Пересчитать и обновить PDF status в дереве.

        Returns:
            (status_value, status_message)
        """
        from app.tree_client import TreeClient
        from rd_core.pdf_status import calculate_pdf_status
        from rd_core.r2_storage import R2Storage

        client = TreeClient()
        r2 = R2Storage()
        status, message = calculate_pdf_status(
            r2, node_id, r2_key, client=client,
        )
        client.update_pdf_status(node_id, status.value, message)
        return status.value, message

    def update_node_annotation_flag(
        self,
        node_id: str,
        has_annotation: bool,
        r2_key: Optional[str] = None,
    ) -> Optional[tuple[str, str]]:
        """Обновить has_annotation + пересчитать PDF status.

        Returns:
            (status_value, message) если обновлён, иначе None.
        """
        from app.tree_client import TreeClient

        try:
            client = TreeClient()
            node = client.get_node(node_id)
            if not node:
                return None

            attrs = node.attributes.copy()
            attrs["has_annotation"] = has_annotation
            client.update_node(node_id, attributes=attrs)

            if node.node_type.value == "document" and r2_key:
                status_value, message = self.update_pdf_status(node_id, r2_key)
                return status_value, message
        except Exception as e:
            logger.debug(f"Update annotation flag failed: {e}")

        return None

    def check_r2_exists(self, r2_key: str) -> bool:
        """Проверить наличие файла в R2."""
        from rd_core.r2_storage import R2Storage
        r2 = R2Storage()
        return r2.exists(r2_key)

    def apply_ocr_from_local_result(
        self,
        document: object,  # Document
        pdf_path: str,
    ) -> int:
        """Применить ocr_text из локального _result.json к блокам без ocr_text.

        Returns:
            Количество обновлённых блоков.
        """
        result_path = Path(pdf_path).parent / f"{Path(pdf_path).stem}_result.json"
        if not result_path.exists():
            return 0

        has_empty = any(
            not block.ocr_text
            for page in document.pages
            for block in page.blocks
        )
        if not has_empty:
            return 0

        try:
            with open(result_path, "r", encoding="utf-8") as f:
                result_data = json.load(f)

            ocr_by_id = {}
            for page in result_data.get("pages", []):
                for block in page.get("blocks", []):
                    block_id = block.get("id")
                    ocr_text = block.get("ocr_text")
                    if block_id and ocr_text:
                        ocr_by_id[block_id] = ocr_text

            if not ocr_by_id:
                return 0

            updated = 0
            for page in document.pages:
                for block in page.blocks:
                    if not block.ocr_text and block.id in ocr_by_id:
                        block.ocr_text = ocr_by_id[block.id]
                        updated += 1

            if updated > 0:
                logger.info(f"Applied ocr_text from local result.json: {updated} blocks updated")

            return updated

        except Exception as e:
            logger.warning(f"Failed to apply OCR from local result.json: {e}")
            return 0

    def reload_annotation_from_db(self, node_id: str) -> Optional[object]:
        """Перезагрузить аннотацию из Supabase (после замены в дереве)."""
        from app.annotation_db import AnnotationDBIO

        try:
            return AnnotationDBIO.load_from_db(node_id)
        except Exception as e:
            logger.error(f"Ошибка перезагрузки аннотации: {e}")
            return None

    # ── Private ──────────────────────────────────────────────────────

    def _load_from_supabase(self, node_id: str) -> AnnotationLoadResult:
        from app.annotation_db import AnnotationDBIO

        try:
            loaded = AnnotationDBIO.load_from_db(node_id)
            if loaded:
                logger.info(f"Annotation loaded from Supabase: {node_id}")
                return AnnotationLoadResult(
                    success=True, document=loaded, source="supabase",
                )
        except Exception as e:
            logger.debug(f"Supabase annotation load error: {e}")

        return AnnotationLoadResult(success=False)

    def _load_from_local_json(self, node_id: str, pdf_path: str) -> AnnotationLoadResult:
        from rd_core.annotation_io import AnnotationIO
        from app.annotation_db import AnnotationDBIO

        ann_path = Path(pdf_path).parent / f"{Path(pdf_path).stem}_annotation.json"
        if not ann_path.exists():
            return AnnotationLoadResult(success=False)

        logger.info(f"Найден старый JSON файл: {ann_path}, миграция в Supabase...")
        loaded, result = AnnotationIO.load_and_migrate(str(ann_path))

        if not result.success:
            error_msg = "; ".join(result.errors)
            return AnnotationLoadResult(
                success=False, message=f"Не удалось загрузить: {error_msg}",
            )

        if loaded:
            # Мигрируем в Supabase
            success = AnnotationDBIO.save_to_db(loaded, node_id)
            if success:
                try:
                    ann_path.unlink()
                    logger.info(f"JSON файл удалён после миграции: {ann_path}")
                except Exception as e:
                    logger.warning(f"Не удалось удалить JSON файл: {e}")

            return AnnotationLoadResult(
                success=True,
                document=loaded,
                source="json_migration",
                message="Разметка мигрирована в Supabase" if success else "Миграция не удалась",
            )

        return AnnotationLoadResult(success=False)

    def _load_from_r2(self, node_id: str, r2_key: str) -> AnnotationLoadResult:
        from rd_core.annotation_io import AnnotationIO
        from rd_core.r2_storage import R2Storage
        from app.annotation_db import AnnotationDBIO

        try:
            r2 = R2Storage()
            p = PurePosixPath(r2_key)
            ann_r2_key = str(p.parent / f"{p.stem}_annotation.json")

            with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as tmp:
                tmp_path = tmp.name

            try:
                success = r2.download_file(ann_r2_key, tmp_path)
                if success:
                    loaded, result = AnnotationIO.load_and_migrate(tmp_path)
                    if result.success and loaded:
                        AnnotationDBIO.save_to_db(loaded, node_id)
                        logger.info(f"Annotation migrated from R2 to Supabase: {ann_r2_key}")
                        return AnnotationLoadResult(
                            success=True,
                            document=loaded,
                            source="r2_migration",
                            message="Разметка мигрирована из R2 в Supabase",
                        )
            finally:
                try:
                    Path(tmp_path).unlink()
                except Exception:
                    pass

        except Exception as e:
            logger.debug(f"R2 annotation migration error: {e}")

        return AnnotationLoadResult(success=False)


# Singleton
_instance: Optional[DocumentService] = None


def get_document_service() -> DocumentService:
    """Получить singleton DocumentService."""
    global _instance
    if _instance is None:
        _instance = DocumentService()
    return _instance
