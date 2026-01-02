"""Диалог верификации блоков - сравнение annotation.json, ocr.html, result.json"""

import json
import logging
import re
from pathlib import Path, PurePosixPath
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Tuple

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QGroupBox, QProgressBar, QMessageBox, QApplication
)
from PySide6.QtCore import Qt, QThread, Signal

logger = logging.getLogger(__name__)


@dataclass
class BlockInfo:
    """Информация о блоке"""
    id: str
    page_index: int
    block_type: str  # "text", "image"
    category_code: Optional[str] = None  # "stamp" для штампов
    
    @property
    def is_stamp(self) -> bool:
        return self.category_code == "stamp"


@dataclass
class VerificationResult:
    """Результат верификации"""
    # Блоки в annotation.json
    ann_total: int = 0
    ann_text: int = 0
    ann_image: int = 0
    ann_stamp: int = 0
    ann_blocks: List[BlockInfo] = field(default_factory=list)
    
    # Блоки в ocr.html (без штампов)
    ocr_html_blocks: Set[str] = field(default_factory=set)  # block IDs
    
    # Блоки в result.json
    result_blocks: Set[str] = field(default_factory=set)  # block IDs
    
    # Ожидаемые блоки (без штампов)
    expected_blocks: Set[str] = field(default_factory=set)
    
    # Отсутствующие блоки
    missing_in_ocr_html: List[BlockInfo] = field(default_factory=list)
    missing_in_result: List[BlockInfo] = field(default_factory=list)
    
    @property
    def is_success(self) -> bool:
        """Верификация прошла успешно?"""
        return len(self.missing_in_ocr_html) == 0 and len(self.missing_in_result) == 0


class VerificationWorker(QThread):
    """Фоновый worker для верификации"""
    
    progress = Signal(str)
    finished = Signal(object)  # VerificationResult или str (ошибка)
    
    def __init__(self, r2_key: str):
        super().__init__()
        self.r2_key = r2_key
    
    def run(self):
        try:
            result = self._verify()
            self.finished.emit(result)
        except Exception as e:
            logger.error(f"Verification failed: {e}", exc_info=True)
            self.finished.emit(f"Ошибка верификации: {e}")
    
    def _verify(self) -> VerificationResult:
        from rd_core.r2_storage import R2Storage
        
        r2 = R2Storage()
        result = VerificationResult()
        
        # Формируем ключи файлов
        pdf_path = PurePosixPath(self.r2_key)
        pdf_stem = pdf_path.stem
        pdf_parent = str(pdf_path.parent)
        
        ann_r2_key = f"{pdf_parent}/{pdf_stem}_annotation.json"
        ocr_r2_key = f"{pdf_parent}/{pdf_stem}_ocr.html"
        res_r2_key = f"{pdf_parent}/{pdf_stem}_result.json"
        
        # 1. Загружаем и парсим annotation.json
        self.progress.emit("Загрузка annotation.json...")
        ann_content = r2.download_text(ann_r2_key)
        if not ann_content:
            raise ValueError("annotation.json не найден на R2")
        
        ann_data = json.loads(ann_content)
        
        for page in ann_data.get("pages", []):
            page_num = page.get("page_number", 0)
            for block in page.get("blocks", []):
                block_id = block.get("id", "")
                block_type = block.get("block_type", "text")
                category_code = block.get("category_code")
                
                block_info = BlockInfo(
                    id=block_id,
                    page_index=page_num,
                    block_type=block_type,
                    category_code=category_code
                )
                result.ann_blocks.append(block_info)
                result.ann_total += 1
                
                if block_info.is_stamp:
                    result.ann_stamp += 1
                elif block_type == "text":
                    result.ann_text += 1
                    result.expected_blocks.add(block_id)
                elif block_type == "image":
                    result.ann_image += 1
                    result.expected_blocks.add(block_id)
        
        # 2. Загружаем и парсим ocr.html
        self.progress.emit("Загрузка ocr.html...")
        ocr_content = r2.download_text(ocr_r2_key)
        if ocr_content:
            # Ищем маркеры BLOCK: XXXX-XXXX-XXX
            block_pattern = re.compile(r'BLOCK:\s*([A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{3})')
            for match in block_pattern.finditer(ocr_content):
                result.ocr_html_blocks.add(match.group(1))
        
        # 3. Загружаем и парсим result.json
        self.progress.emit("Загрузка result.json...")
        res_content = r2.download_text(res_r2_key)
        if res_content:
            res_data = json.loads(res_content)
            for page in res_data.get("pages", []):
                for block in page.get("blocks", []):
                    block_id = block.get("id", "")
                    if block_id:
                        result.result_blocks.add(block_id)
        
        # 4. Находим отсутствующие блоки
        self.progress.emit("Анализ расхождений...")
        
        for block_info in result.ann_blocks:
            if block_info.is_stamp:
                continue  # Штампы не проверяем
            
            if block_info.id not in result.ocr_html_blocks:
                result.missing_in_ocr_html.append(block_info)
            
            if block_info.id not in result.result_blocks:
                result.missing_in_result.append(block_info)
        
        return result


class BlockVerificationDialog(QDialog):
    """Диалог верификации блоков"""
    
    def __init__(self, node_name: str, r2_key: str, parent=None):
        super().__init__(parent)
        self.node_name = node_name
        self.r2_key = r2_key
        self._worker: Optional[VerificationWorker] = None
        
        self.setWindowTitle(f"Верификация блоков: {node_name}")
        self.setMinimumSize(600, 500)
        self.setModal(True)
        
        self._setup_ui()
        self._start_verification()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        
        # Заголовок
        title = QLabel(f"📊 Верификация блоков документа")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(title)
        
        # Прогресс
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate
        layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel("Загрузка данных...")
        self.status_label.setStyleSheet("color: #888;")
        layout.addWidget(self.status_label)
        
        # Группа: Annotation
        self.ann_group = QGroupBox("📄 Annotation.json")
        ann_layout = QVBoxLayout(self.ann_group)
        self.ann_label = QLabel()
        self.ann_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ann_layout.addWidget(self.ann_label)
        layout.addWidget(self.ann_group)
        self.ann_group.hide()
        
        # Группа: OCR HTML
        self.ocr_group = QGroupBox("🌐 OCR.html")
        ocr_layout = QVBoxLayout(self.ocr_group)
        self.ocr_label = QLabel()
        self.ocr_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ocr_layout.addWidget(self.ocr_label)
        layout.addWidget(self.ocr_group)
        self.ocr_group.hide()
        
        # Группа: Result JSON
        self.result_group = QGroupBox("📋 Result.json")
        result_layout = QVBoxLayout(self.result_group)
        self.result_label = QLabel()
        self.result_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        result_layout.addWidget(self.result_label)
        layout.addWidget(self.result_group)
        self.result_group.hide()
        
        # Результат верификации
        self.verdict_group = QGroupBox("🔍 Результат верификации")
        verdict_layout = QVBoxLayout(self.verdict_group)
        self.verdict_label = QLabel()
        self.verdict_label.setWordWrap(True)
        self.verdict_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        verdict_layout.addWidget(self.verdict_label)
        layout.addWidget(self.verdict_group)
        self.verdict_group.hide()
        
        # Детали отсутствующих блоков
        self.missing_group = QGroupBox("❌ Отсутствующие блоки")
        missing_layout = QVBoxLayout(self.missing_group)
        self.missing_text = QTextEdit()
        self.missing_text.setReadOnly(True)
        self.missing_text.setStyleSheet("""
            QTextEdit {
                background-color: #2d2d2d;
                color: #ff6b6b;
                font-family: 'Consolas', monospace;
                font-size: 11px;
            }
        """)
        self.missing_text.setMaximumHeight(200)
        missing_layout.addWidget(self.missing_text)
        layout.addWidget(self.missing_group)
        self.missing_group.hide()
        
        # Кнопки
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        
        self.copy_btn = QPushButton("📋 Копировать отчёт")
        self.copy_btn.clicked.connect(self._copy_report)
        self.copy_btn.hide()
        buttons_layout.addWidget(self.copy_btn)
        
        self.close_btn = QPushButton("Закрыть")
        self.close_btn.clicked.connect(self.close)
        buttons_layout.addWidget(self.close_btn)
        
        layout.addLayout(buttons_layout)
    
    def _start_verification(self):
        """Запустить верификацию"""
        self._worker = VerificationWorker(self.r2_key)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()
    
    def _on_progress(self, message: str):
        self.status_label.setText(message)
    
    def _on_finished(self, result):
        self.progress_bar.hide()
        
        if isinstance(result, str):
            # Ошибка
            self.status_label.setText(f"❌ {result}")
            self.status_label.setStyleSheet("color: #ff6b6b;")
            return
        
        self._result = result
        self._display_result(result)
    
    def _display_result(self, r: VerificationResult):
        """Отобразить результат верификации"""
        self.status_label.hide()
        
        # Annotation stats
        self.ann_label.setText(
            f"<b>Всего блоков:</b> {r.ann_total}<br>"
            f"<b>Текстовых:</b> {r.ann_text}<br>"
            f"<b>Изображений:</b> {r.ann_image}<br>"
            f"<b>Штампов (code=stamp):</b> {r.ann_stamp}"
        )
        self.ann_group.show()
        
        # OCR HTML stats
        self.ocr_label.setText(
            f"<b>Найдено блоков:</b> {len(r.ocr_html_blocks)}<br>"
            f"<span style='color: #888;'>(штампы не включаются в ocr.html)</span>"
        )
        self.ocr_group.show()
        
        # Result JSON stats
        self.result_label.setText(
            f"<b>Найдено блоков:</b> {len(r.result_blocks)}"
        )
        self.result_group.show()
        
        # Вердикт
        expected_count = len(r.expected_blocks)
        
        if r.is_success:
            self.verdict_label.setText(
                f"<span style='color: #4ade80; font-size: 16px;'>✅ Верификация пройдена</span><br><br>"
                f"Все {expected_count} блоков (без штампов) найдены в итоговых документах."
            )
        else:
            missing_ocr = len(r.missing_in_ocr_html)
            missing_res = len(r.missing_in_result)
            self.verdict_label.setText(
                f"<span style='color: #ff6b6b; font-size: 16px;'>❌ Обнаружены расхождения</span><br><br>"
                f"<b>Ожидалось блоков (без штампов):</b> {expected_count}<br>"
                f"<b>Отсутствует в ocr.html:</b> {missing_ocr}<br>"
                f"<b>Отсутствует в result.json:</b> {missing_res}"
            )
            
            # Детали отсутствующих блоков
            lines = []
            
            if r.missing_in_ocr_html:
                lines.append("=== Отсутствуют в ocr.html ===")
                for b in r.missing_in_ocr_html:
                    lines.append(f"  Стр. {b.page_index + 1}: {b.id} ({b.block_type})")
            
            if r.missing_in_result:
                if lines:
                    lines.append("")
                lines.append("=== Отсутствуют в result.json ===")
                for b in r.missing_in_result:
                    lines.append(f"  Стр. {b.page_index + 1}: {b.id} ({b.block_type})")
            
            self.missing_text.setPlainText("\n".join(lines))
            self.missing_group.show()
        
        self.verdict_group.show()
        self.copy_btn.show()
    
    def _copy_report(self):
        """Скопировать отчёт в буфер обмена"""
        if not hasattr(self, '_result'):
            return
        
        r = self._result
        lines = [
            f"Верификация блоков: {self.node_name}",
            f"R2 Key: {self.r2_key}",
            "",
            "=== Annotation.json ===",
            f"Всего блоков: {r.ann_total}",
            f"Текстовых: {r.ann_text}",
            f"Изображений: {r.ann_image}",
            f"Штампов: {r.ann_stamp}",
            "",
            "=== OCR.html ===",
            f"Найдено блоков: {len(r.ocr_html_blocks)}",
            "",
            "=== Result.json ===",
            f"Найдено блоков: {len(r.result_blocks)}",
            "",
            "=== Результат ===",
        ]
        
        if r.is_success:
            lines.append("✅ Верификация пройдена")
        else:
            lines.append("❌ Обнаружены расхождения")
            
            if r.missing_in_ocr_html:
                lines.append("")
                lines.append("Отсутствуют в ocr.html:")
                for b in r.missing_in_ocr_html:
                    lines.append(f"  Стр. {b.page_index + 1}: {b.id} ({b.block_type})")
            
            if r.missing_in_result:
                lines.append("")
                lines.append("Отсутствуют в result.json:")
                for b in r.missing_in_result:
                    lines.append(f"  Стр. {b.page_index + 1}: {b.id} ({b.block_type})")
        
        QApplication.clipboard().setText("\n".join(lines))
        
        from app.gui.toast import show_toast
        show_toast(self, "Отчёт скопирован")
    
    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait()
        super().closeEvent(event)
