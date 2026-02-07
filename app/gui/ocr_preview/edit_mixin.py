"""Миксин редактирования OCR результатов."""
from __future__ import annotations

import json
import logging

from PySide6.QtWidgets import QMessageBox

logger = logging.getLogger(__name__)


class EditMixin:
    """Редактирование HTML и сохранение результатов."""

    def _toggle_edit_mode(self):
        """Переключение между режимами просмотра и редактирования"""
        if not self._current_block_id:
            return

        if self._is_editing:
            # Сохраняем и закрываем редактор
            self._save_all()
            self._is_editing = False
            self.editor_widget.hide()
            self.edit_save_btn.setText("✏️ Редактировать")
            self.edit_save_btn.setToolTip("Редактировать HTML")
        else:
            # Открываем редактор
            self._is_editing = True
            self.editor_widget.show()
            self.edit_save_btn.setText("💾 Сохранить")
            self.edit_save_btn.setToolTip("Сохранить изменения (локально + R2)")

    def _on_text_changed(self):
        """Обработка изменения текста"""
        if not self._current_block_id or not self._is_editing:
            return

        self._is_modified = True

        # Обновляем preview
        new_html = self.html_edit.toPlainText()
        styled_html = self._apply_preview_styles(new_html)
        self.preview_edit.setHtml(styled_html)

    def _save_all(self):
        """Сохранить изменения локально и на R2"""
        if not self._result_path or not self._current_block_id:
            return

        try:
            new_html = self.html_edit.toPlainText()

            # Обновляем данные в структуре {pages: [{blocks: [...]}]}
            for page in self._result_data.get("pages", []):
                for b in page.get("blocks", []):
                    if b.get("id") == self._current_block_id:
                        b["ocr_html"] = new_html
                        # Обновляем индекс
                        self._blocks_index[self._current_block_id] = b
                        break

            # Сохраняем локально
            with open(self._result_path, "w", encoding="utf-8") as f:
                json.dump(self._result_data, f, ensure_ascii=False, indent=2)

            # Сохраняем на R2
            try:
                from pathlib import PurePosixPath

                from rd_core.r2_storage import R2Storage

                r2 = R2Storage()

                if self._r2_key:
                    r2_dir = str(PurePosixPath(self._r2_key).parent)
                    result_r2_key = f"{r2_dir}/{self._result_path.name}"
                else:
                    result_r2_key = f"tree_docs/{self._result_path.name}"

                r2.upload_file(str(self._result_path), result_r2_key)
                logger.info(f"Saved to R2: {result_r2_key}")
            except Exception as e:
                logger.error(f"Failed to save to R2: {e}")

            self._is_modified = False

            from app.gui.toast import show_toast

            show_toast(self.window(), "Сохранено")

            self.content_changed.emit(self._current_block_id, new_html)

        except Exception as e:
            logger.error(f"Failed to save: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить:\n{e}")
