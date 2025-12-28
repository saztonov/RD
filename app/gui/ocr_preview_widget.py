"""
Виджет предварительного просмотра OCR результатов
Отображает HTML из _result.json для выбранного блока
"""

import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QSplitter, QMessageBox,
    QApplication, QGroupBox
)
from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QFont, QCursor
from PySide6.QtWebEngineWidgets import QWebEngineView

logger = logging.getLogger(__name__)


class OcrPreviewWidget(QWidget):
    """Виджет просмотра и редактирования OCR результатов"""
    
    content_changed = Signal(str, str)  # block_id, new_html
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_block_id: Optional[str] = None
        self._result_data: Optional[Dict[str, Any]] = None
        self._result_path: Optional[Path] = None
        self._r2_key: Optional[str] = None
        self._is_modified = False
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Настройка UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        
        # Заголовок с ID блока
        header = QHBoxLayout()
        header.setSpacing(4)
        
        self.title_label = QLabel("OCR Preview")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 11px;")
        header.addWidget(self.title_label)
        
        # ID блока (полный, с возможностью копирования)
        self.block_id_label = QLabel("")
        self.block_id_label.setStyleSheet("""
            QLabel {
                color: #888;
                font-family: 'Consolas', monospace;
                font-size: 10px;
                padding: 2px 4px;
                background: #2d2d2d;
                border-radius: 3px;
            }
        """)
        self.block_id_label.setCursor(QCursor(Qt.PointingHandCursor))
        self.block_id_label.setToolTip("Клик для копирования ID")
        self.block_id_label.mousePressEvent = self._copy_block_id
        header.addWidget(self.block_id_label)
        
        header.addStretch()
        
        # Кнопка сохранения (локально + R2)
        self.save_btn = QPushButton("💾 Сохранить")
        self.save_btn.setToolTip("Сохранить (локально + R2)")
        self.save_btn.clicked.connect(self._save_all)
        self.save_btn.setEnabled(False)
        header.addWidget(self.save_btn)
        
        layout.addLayout(header)
        
        # Главный splitter
        main_splitter = QSplitter(Qt.Vertical)
        
        # === Верхняя часть: Preview + Editor ===
        content_splitter = QSplitter(Qt.Vertical)
        
        # HTML Preview (QWebEngineView для корректного рендеринга HTML/CSS)
        self.preview_edit = QWebEngineView()
        self.preview_edit.setStyleSheet("""
            QWebEngineView {
                background-color: #1e1e1e;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
            }
        """)
        # Отключаем контекстное меню браузера
        self.preview_edit.setContextMenuPolicy(Qt.NoContextMenu)
        content_splitter.addWidget(self.preview_edit)
        
        # Raw HTML Editor
        editor_widget = QWidget()
        editor_layout = QVBoxLayout(editor_widget)
        editor_layout.setContentsMargins(0, 4, 0, 0)
        
        editor_label = QLabel("HTML (редактирование)")
        editor_label.setStyleSheet("font-size: 10px; color: #888;")
        editor_layout.addWidget(editor_label)
        
        self.html_edit = QTextEdit()
        self.html_edit.setStyleSheet("""
            QTextEdit {
                background-color: #252526;
                color: #9cdcfe;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                padding: 4px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
            }
        """)
        self.html_edit.textChanged.connect(self._on_text_changed)
        editor_layout.addWidget(self.html_edit)
        
        content_splitter.addWidget(editor_widget)
        content_splitter.setSizes([250, 150])
        
        main_splitter.addWidget(content_splitter)
        
        # === Нижняя часть: Штамп ===
        self.stamp_group = QGroupBox("📋 Штамп листа")
        self.stamp_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #569cd6;
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #569cd6;
            }
        """)
        stamp_layout = QVBoxLayout(self.stamp_group)
        stamp_layout.setContentsMargins(8, 12, 8, 8)
        
        self.stamp_content = QLabel("")
        self.stamp_content.setWordWrap(True)
        self.stamp_content.setStyleSheet("font-size: 11px; color: #d4d4d4;")
        self.stamp_content.setTextInteractionFlags(Qt.TextSelectableByMouse)
        stamp_layout.addWidget(self.stamp_content)
        
        self.stamp_group.hide()
        main_splitter.addWidget(self.stamp_group)
        
        main_splitter.setSizes([400, 150])
        layout.addWidget(main_splitter)
        
        # Placeholder
        self._show_placeholder()
    
    def _copy_block_id(self, event):
        """Копировать ID блока в буфер обмена"""
        if self._current_block_id:
            QApplication.clipboard().setText(self._current_block_id)
            from app.gui.toast import show_toast
            show_toast(self.window(), f"ID скопирован: {self._current_block_id}")
    
    def _show_placeholder(self):
        """Показать заглушку"""
        self.preview_edit.setHtml(
            '<p style="color: #666; text-align: center; margin-top: 40px;">'
            'Выберите блок для просмотра OCR результата</p>'
        )
        self.html_edit.clear()
        self.html_edit.setEnabled(False)
        self.block_id_label.setText("")
        self.stamp_group.hide()
        self._current_block_id = None
    
    def load_result_file(self, pdf_path: str, r2_key: Optional[str] = None):
        """Загрузить _result.json для PDF документа"""
        self._result_data = None
        self._result_path = None
        self._r2_key = r2_key
        self._blocks_index: Dict[str, Dict] = {}
        
        if not pdf_path:
            return
        
        pdf_path = Path(pdf_path)
        result_path = pdf_path.parent / f"{pdf_path.stem}_result.json"
        
        if not result_path.exists():
            logger.debug(f"Result file not found: {result_path}")
            return
        
        try:
            with open(result_path, "r", encoding="utf-8") as f:
                self._result_data = json.load(f)
            self._result_path = result_path
            
            # Индексируем блоки по ID из структуры {pages: [{blocks: [...]}]}
            blocks_count = 0
            for page in self._result_data.get("pages", []):
                for block in page.get("blocks", []):
                    block_id = block.get("id")
                    if block_id:
                        self._blocks_index[block_id] = block
                        blocks_count += 1
            
            logger.info(f"Loaded result file: {result_path} ({blocks_count} blocks)")
            self.title_label.setText(f"OCR Preview ({blocks_count} блоков)")
        except Exception as e:
            logger.error(f"Failed to load result file: {e}")
            self.title_label.setText("OCR Preview")
    
    def show_block(self, block_id: str):
        """Показать OCR результат для блока"""
        self._current_block_id = block_id
        self._is_modified = False
        self.save_btn.setEnabled(False)
        
        # Обновляем ID блока
        self.block_id_label.setText(block_id if block_id else "")
        
        if not self._result_data or not block_id:
            self._show_placeholder()
            return
        
        # Ищем блок по индексу
        block_data = self._blocks_index.get(block_id)
        
        if not block_data:
            self.preview_edit.setHtml(
                '<p style="color: #888;">OCR результат для этого блока не найден</p>'
            )
            self.html_edit.clear()
            self.html_edit.setEnabled(False)
            self.stamp_group.hide()
            return
        
        block_type = block_data.get("block_type", "text")
        
        # Получаем HTML (ocr_html из result.json)
        html_content = block_data.get("ocr_html", "") or block_data.get("html", "")
        
        # Для IMAGE блоков: форматируем ocr_json если есть
        if block_type == "image":
            html_content = self._format_image_block(block_data, html_content)
        
        # Fallback: ocr_text если нет HTML
        if not html_content and block_data.get("ocr_text"):
            html_content = f"<pre>{block_data['ocr_text']}</pre>"
        
        # Обрабатываем штамп отдельно
        stamp_data = block_data.get("stamp_data")
        if stamp_data:
            self._show_stamp(stamp_data)
        else:
            self.stamp_group.hide()
        
        if not html_content:
            self.preview_edit.setHtml(
                '<p style="color: #888;">Пустой OCR результат</p>'
            )
            self.html_edit.clear()
            self.html_edit.setEnabled(False)
            return
        
        # Показываем HTML
        styled_html = self._apply_preview_styles(html_content)
        self.preview_edit.setHtml(styled_html)
        
        # Редактор
        self.html_edit.blockSignals(True)
        self.html_edit.setPlainText(html_content)
        self.html_edit.blockSignals(False)
        self.html_edit.setEnabled(True)
        
        self.title_label.setText("OCR Preview")
    
    def _show_stamp(self, stamp_data: dict):
        """Показать данные штампа в отдельном блоке"""
        lines = []
        
        if stamp_data.get("document_code"):
            lines.append(f"<b>Шифр:</b> {stamp_data['document_code']}")
        
        if stamp_data.get("sheet_name"):
            lines.append(f"<b>Наименование:</b> {stamp_data['sheet_name']}")
        
        sheet_num = stamp_data.get("sheet_number", "")
        total = stamp_data.get("total_sheets", "")
        if sheet_num or total:
            lines.append(f"<b>Лист:</b> {sheet_num}/{total}")
        
        if stamp_data.get("stage"):
            lines.append(f"<b>Стадия:</b> {stamp_data['stage']}")
        
        if stamp_data.get("organization"):
            lines.append(f"<b>Организация:</b> {stamp_data['organization']}")
        
        if stamp_data.get("project_name"):
            lines.append(f"<b>Проект:</b> {stamp_data['project_name']}")
        
        signatures = stamp_data.get("signatures", [])
        if signatures:
            sig_parts = [f"{s.get('role', '')}: {s.get('surname', '')} ({s.get('date', '')})" for s in signatures]
            lines.append(f"<b>Подписи:</b> {'; '.join(sig_parts)}")
        
        self.stamp_content.setText("<br>".join(lines))
        self.stamp_group.show()
    
    def _format_image_block(self, block_data: dict, html_content: str) -> str:
        """Форматировать IMAGE блок с ocr_json и crop_url."""
        parts = []
        
        # Ссылка на кроп
        crop_url = block_data.get("crop_url")
        if crop_url:
            parts.append(f'<p><a href="{crop_url}" target="_blank">📎 Открыть кроп</a></p>')
        
        # ocr_json от модели
        ocr_json = block_data.get("ocr_json")
        if ocr_json:
            parts.append(self._format_ocr_json(ocr_json))
        elif html_content:
            parts.append(html_content)
        elif block_data.get("ocr_text"):
            parts.append(f"<pre>{block_data['ocr_text']}</pre>")
        
        return "\n".join(parts) if parts else html_content
    
    def _format_stamp_data(self, stamp_data: dict) -> str:
        """Форматировать данные штампа в HTML."""
        parts = ['<div style="border: 1px solid #569cd6; padding: 8px; margin: 8px 0; border-radius: 4px;">']
        parts.append('<h3 style="margin: 0 0 8px 0;">📋 Штамп</h3>')
        
        if stamp_data.get("document_code"):
            parts.append(f'<p><b>Шифр:</b> {stamp_data["document_code"]}</p>')
        
        if stamp_data.get("project_name"):
            parts.append(f'<p><b>Проект:</b> {stamp_data["project_name"]}</p>')
        
        if stamp_data.get("sheet_name"):
            parts.append(f'<p><b>Наименование:</b> {stamp_data["sheet_name"]}</p>')
        
        sheet_num = stamp_data.get("sheet_number", "")
        total = stamp_data.get("total_sheets", "")
        if sheet_num or total:
            parts.append(f'<p><b>Лист:</b> {sheet_num}/{total}</p>')
        
        if stamp_data.get("stage"):
            parts.append(f'<p><b>Стадия:</b> {stamp_data["stage"]}</p>')
        
        if stamp_data.get("organization"):
            parts.append(f'<p><b>Организация:</b> {stamp_data["organization"]}</p>')
        
        signatures = stamp_data.get("signatures", [])
        if signatures:
            sig_parts = []
            for sig in signatures:
                role = sig.get("role", "")
                name = sig.get("surname", "")
                date = sig.get("date", "")
                sig_parts.append(f"{role}: {name} ({date})")
            parts.append(f'<p><b>Подписи:</b> {"; ".join(sig_parts)}</p>')
        
        parts.append('</div>')
        return "\n".join(parts)
    
    def _format_ocr_json(self, ocr_json: dict) -> str:
        """Форматировать ocr_json в HTML."""
        parts = []
        
        # Описание
        if ocr_json.get("content_summary"):
            parts.append(f"<p><b>Описание:</b> {ocr_json['content_summary']}</p>")
        
        if ocr_json.get("detailed_description"):
            parts.append(f"<p>{ocr_json['detailed_description']}</p>")
        
        # Локация
        loc = ocr_json.get("location", {})
        if loc:
            zone = loc.get("zone_name", "—")
            grid = loc.get("grid_lines", "—")
            parts.append(f"<p><b>Зона:</b> {zone} | <b>Оси:</b> {grid}</p>")
        
        # Ключевые сущности
        entities = ocr_json.get("key_entities", [])
        if entities:
            entities_str = ", ".join(str(e) for e in entities[:15])
            parts.append(f"<p><b>Сущности:</b> {entities_str}</p>")
        
        # Чистый OCR текст
        if ocr_json.get("clean_ocr_text"):
            parts.append(f"<pre>{ocr_json['clean_ocr_text']}</pre>")
        
        # Если ничего не распознали — показываем JSON как есть
        if not parts:
            import json as json_module
            parts.append(f"<pre>{json_module.dumps(ocr_json, ensure_ascii=False, indent=2)}</pre>")
        
        return "\n".join(parts)
    
    def _format_analysis(self, analysis: dict) -> str:
        """Форматировать analysis в HTML"""
        parts = []
        
        if analysis.get("content_summary"):
            parts.append(f"<p><b>Описание:</b> {analysis['content_summary']}</p>")
        
        if analysis.get("detailed_description"):
            parts.append(f"<p><b>Детали:</b> {analysis['detailed_description']}</p>")
        
        loc = analysis.get("location", {})
        if loc.get("zone_name") or loc.get("grid_lines"):
            parts.append(f"<p><b>Зона:</b> {loc.get('zone_name', '—')} | <b>Оси:</b> {loc.get('grid_lines', '—')}</p>")
        
        if analysis.get("key_entities"):
            entities = ", ".join(analysis["key_entities"][:15])
            parts.append(f"<p><b>Сущности:</b> {entities}</p>")
        
        if analysis.get("clean_ocr_text"):
            parts.append(f"<pre>{analysis['clean_ocr_text']}</pre>")
        
        return "\n".join(parts) if parts else "<p>Нет данных</p>"
    
    def _apply_preview_styles(self, html: str) -> str:
        """Добавить стили для preview (полноценный CSS для WebEngine)"""
        style = """
        <style>
            * { box-sizing: border-box; }
            body { 
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                font-size: 13px; 
                line-height: 1.5;
                color: #d4d4d4; 
                background-color: #1e1e1e;
                margin: 8px;
                padding: 0;
            }
            table { border-collapse: collapse; width: 100%; margin: 12px 0; }
            th, td { border: 1px solid #444; padding: 6px 10px; text-align: left; vertical-align: top; }
            th { background-color: #2d2d2d; font-weight: 600; }
            tr:nth-child(even) { background-color: #252526; }
            tr:hover { background-color: #333; }
            h1, h2, h3, h4 { color: #569cd6; margin: 16px 0 8px 0; }
            h1 { font-size: 18px; border-bottom: 1px solid #444; padding-bottom: 4px; }
            h2 { font-size: 16px; }
            h3 { font-size: 14px; }
            h4 { font-size: 13px; }
            p { margin: 8px 0; }
            ul, ol { margin: 8px 0; padding-left: 24px; }
            li { margin: 4px 0; }
            pre { 
                background: #252526; 
                padding: 10px; 
                border-radius: 4px; 
                overflow-x: auto; 
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
                white-space: pre-wrap;
                word-wrap: break-word;
            }
            a { color: #4fc3f7; text-decoration: none; }
            a:hover { text-decoration: underline; }
            img { max-width: 100%; height: auto; }
        </style>
        """
        return f"<!DOCTYPE html><html><head><meta charset='UTF-8'>{style}</head><body>{html}</body></html>"
    
    def _on_text_changed(self):
        """Обработка изменения текста"""
        if not self._current_block_id:
            return
        
        self._is_modified = True
        self.save_btn.setEnabled(True)
        
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
                from rd_core.r2_storage import R2Storage
                from pathlib import PurePosixPath
                
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
            self.save_btn.setEnabled(False)
            
            from app.gui.toast import show_toast
            show_toast(self.window(), "Сохранено")
            
            self.content_changed.emit(self._current_block_id, new_html)
            
        except Exception as e:
            logger.error(f"Failed to save: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить:\n{e}")
    
    def clear(self):
        """Очистить виджет"""
        self._result_data = None
        self._result_path = None
        self._current_block_id = None
        self._blocks_index = {}
        self.title_label.setText("OCR Preview")
        self.block_id_label.setText("")
        self.stamp_group.hide()
        self._show_placeholder()

