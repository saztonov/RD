"""Диалог просмотра и редактирования Markdown документов"""
from __future__ import annotations

import logging
from typing import Optional, Callable

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QSplitter,
    QPlainTextEdit, QTextBrowser, QTabWidget, QWidget, QLabel,
    QMessageBox
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QTextCharFormat, QColor

logger = logging.getLogger(__name__)

# CSS стили для markdown рендеринга
MARKDOWN_CSS = """
<style>
body {
    font-family: 'Segoe UI', 'SF Pro Text', -apple-system, sans-serif;
    font-size: 14px;
    line-height: 1.6;
    color: #e0e0e0;
    background-color: #1e1e1e;
    padding: 20px;
    max-width: 100%;
}
h1, h2, h3, h4, h5, h6 {
    color: #4fc3f7;
    margin-top: 24px;
    margin-bottom: 16px;
    font-weight: 600;
}
h1 { font-size: 2em; border-bottom: 1px solid #3e3e42; padding-bottom: 8px; }
h2 { font-size: 1.5em; border-bottom: 1px solid #3e3e42; padding-bottom: 6px; }
h3 { font-size: 1.25em; }
p { margin: 16px 0; }
code {
    background-color: #2d2d2d;
    padding: 2px 6px;
    border-radius: 4px;
    font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
    font-size: 13px;
    color: #ce9178;
}
pre {
    background-color: #252526;
    padding: 16px;
    border-radius: 6px;
    overflow-x: auto;
    border: 1px solid #3e3e42;
}
pre code {
    background: none;
    padding: 0;
    color: #d4d4d4;
}
blockquote {
    border-left: 4px solid #0e639c;
    margin: 16px 0;
    padding: 8px 16px;
    background-color: #252526;
    color: #9cdcfe;
}
ul, ol { padding-left: 24px; margin: 16px 0; }
li { margin: 4px 0; }
table {
    border-collapse: collapse;
    width: 100%;
    margin: 16px 0;
}
th, td {
    border: 1px solid #3e3e42;
    padding: 10px 14px;
    text-align: left;
}
th {
    background-color: #2d2d2d;
    color: #4fc3f7;
    font-weight: 600;
}
tr:nth-child(even) { background-color: #252526; }
a { color: #3794ff; text-decoration: none; }
a:hover { text-decoration: underline; }
img { max-width: 100%; height: auto; border-radius: 4px; }
hr { border: none; border-top: 1px solid #3e3e42; margin: 24px 0; }
.block-separator {
    font-size: 24px;
    color: #000;
    margin: 16px 0 8px 0;
    font-family: 'Segoe UI', sans-serif;
}
</style>
"""


def markdown_to_html(md_text: str) -> str:
    """Конвертировать markdown в HTML"""
    import re
    try:
        import mistune
        html = mistune.html(md_text)
    except ImportError:
        # Fallback - простая замена
        html = _simple_markdown_to_html(md_text)
    
    # Преобразуем разделители BLOCK_ID в стилизованные элементы
    html = re.sub(
        r'\[\[\[BLOCK_ID:\s*([a-f0-9\-]+)\]\]\]',
        r'<div class="block-separator">BLOCK_ID: \1</div>',
        html
    )
    
    return f"<!DOCTYPE html><html><head>{MARKDOWN_CSS}</head><body>{html}</body></html>"


def _simple_markdown_to_html(md_text: str) -> str:
    """Простая конвертация markdown без библиотеки"""
    import re
    
    lines = md_text.split('\n')
    result = []
    in_code_block = False
    in_list = False
    
    for line in lines:
        # Блоки кода
        if line.startswith('```'):
            if in_code_block:
                result.append('</code></pre>')
                in_code_block = False
            else:
                result.append('<pre><code>')
                in_code_block = True
            continue
        
        if in_code_block:
            result.append(line.replace('<', '&lt;').replace('>', '&gt;'))
            continue
        
        # Заголовки
        if line.startswith('######'):
            result.append(f'<h6>{line[6:].strip()}</h6>')
        elif line.startswith('#####'):
            result.append(f'<h5>{line[5:].strip()}</h5>')
        elif line.startswith('####'):
            result.append(f'<h4>{line[4:].strip()}</h4>')
        elif line.startswith('###'):
            result.append(f'<h3>{line[3:].strip()}</h3>')
        elif line.startswith('##'):
            result.append(f'<h2>{line[2:].strip()}</h2>')
        elif line.startswith('#'):
            result.append(f'<h1>{line[1:].strip()}</h1>')
        # Списки
        elif line.strip().startswith('- ') or line.strip().startswith('* '):
            if not in_list:
                result.append('<ul>')
                in_list = True
            content = line.strip()[2:]
            result.append(f'<li>{content}</li>')
        # Горизонтальная линия
        elif line.strip() in ('---', '***', '___'):
            result.append('<hr>')
        # Пустая строка
        elif not line.strip():
            if in_list:
                result.append('</ul>')
                in_list = False
            result.append('<br>')
        else:
            if in_list:
                result.append('</ul>')
                in_list = False
            # Inline code
            line = re.sub(r'`([^`]+)`', r'<code>\1</code>', line)
            # Bold
            line = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', line)
            line = re.sub(r'__([^_]+)__', r'<strong>\1</strong>', line)
            # Italic
            line = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', line)
            line = re.sub(r'_([^_]+)_', r'<em>\1</em>', line)
            result.append(f'<p>{line}</p>')
    
    if in_list:
        result.append('</ul>')
    if in_code_block:
        result.append('</code></pre>')
    
    return '\n'.join(result)


class MarkdownEditorDialog(QDialog):
    """Немодальное окно для просмотра и редактирования Markdown"""
    
    markdown_saved = Signal(str)  # Сигнал при сохранении: новый текст
    
    def __init__(
        self, 
        title: str,
        markdown_text: str,
        save_callback: Optional[Callable[[str], bool]] = None,
        parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle(f"📝 {title}")
        self.setMinimumSize(900, 700)
        self.resize(1100, 800)
        
        # Делаем окно немодальным
        self.setModal(False)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, False)
        self.setAttribute(Qt.WA_DeleteOnClose)
        
        self._original_text = markdown_text
        self._save_callback = save_callback
        self._modified = False
        self._update_timer = QTimer()
        self._update_timer.setSingleShot(True)
        self._update_timer.timeout.connect(self._update_preview)
        
        self._setup_ui()
        self._load_content(markdown_text)
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Toolbar
        toolbar = QWidget()
        toolbar.setStyleSheet("background-color: #2d2d2d; border-bottom: 1px solid #3e3e42;")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 8, 10, 8)
        
        self._status_label = QLabel("Просмотр")
        self._status_label.setStyleSheet("color: #888; font-size: 12px;")
        toolbar_layout.addWidget(self._status_label)
        
        toolbar_layout.addStretch()
        
        btn_style = """
            QPushButton {
                background-color: #3e3e42;
                color: #e0e0e0;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: 500;
            }
            QPushButton:hover { background-color: #505054; }
            QPushButton:pressed { background-color: #0e639c; }
            QPushButton:disabled { background-color: #2d2d2d; color: #666; }
        """
        
        self._save_btn = QPushButton("💾 Сохранить")
        self._save_btn.setStyleSheet(btn_style.replace("#3e3e42", "#0e639c"))
        self._save_btn.clicked.connect(self._save)
        self._save_btn.setEnabled(False)
        toolbar_layout.addWidget(self._save_btn)
        
        self._reset_btn = QPushButton("↻ Сбросить")
        self._reset_btn.setStyleSheet(btn_style)
        self._reset_btn.clicked.connect(self._reset)
        self._reset_btn.setEnabled(False)
        toolbar_layout.addWidget(self._reset_btn)
        
        layout.addWidget(toolbar)
        
        # Табы: Просмотр / Редактирование / Разделённый вид
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane { border: none; }
            QTabBar::tab {
                background-color: #2d2d2d;
                color: #888;
                padding: 10px 20px;
                border: none;
                border-bottom: 2px solid transparent;
            }
            QTabBar::tab:selected {
                color: #e0e0e0;
                border-bottom: 2px solid #0e639c;
            }
            QTabBar::tab:hover { color: #e0e0e0; }
        """)
        
        # Tab 1: Просмотр
        self._preview = QTextBrowser()
        self._preview.setOpenExternalLinks(True)
        self._preview.setStyleSheet("""
            QTextBrowser {
                background-color: #1e1e1e;
                color: #e0e0e0;
                border: none;
                padding: 10px;
            }
        """)
        self._tabs.addTab(self._preview, "👁 Просмотр")
        
        # Tab 2: Редактирование
        self._editor = QPlainTextEdit()
        self._editor.setFont(QFont("Cascadia Code", 11))
        self._editor.setTabStopDistance(40)
        self._editor.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: none;
                padding: 10px;
                selection-background-color: #264f78;
            }
        """)
        self._editor.textChanged.connect(self._on_text_changed)
        self._tabs.addTab(self._editor, "✏️ Редактирование")
        
        # Tab 3: Split view
        split_widget = QWidget()
        split_layout = QHBoxLayout(split_widget)
        split_layout.setContentsMargins(0, 0, 0, 0)
        
        splitter = QSplitter(Qt.Horizontal)
        
        self._split_editor = QPlainTextEdit()
        self._split_editor.setFont(QFont("Cascadia Code", 11))
        self._split_editor.setTabStopDistance(40)
        self._split_editor.setStyleSheet(self._editor.styleSheet())
        self._split_editor.textChanged.connect(self._on_split_text_changed)
        
        self._split_preview = QTextBrowser()
        self._split_preview.setOpenExternalLinks(True)
        self._split_preview.setStyleSheet(self._preview.styleSheet())
        
        splitter.addWidget(self._split_editor)
        splitter.addWidget(self._split_preview)
        splitter.setSizes([500, 500])
        
        split_layout.addWidget(splitter)
        self._tabs.addTab(split_widget, "⚡ Разделённый")
        
        # Синхронизация между редакторами при переключении табов
        self._tabs.currentChanged.connect(self._on_tab_changed)
        
        layout.addWidget(self._tabs)
    
    def _load_content(self, text: str):
        """Загрузить контент"""
        self._editor.setPlainText(text)
        self._split_editor.setPlainText(text)
        self._update_preview()
        self._modified = False
        self._update_status()
    
    def _on_text_changed(self):
        """Текст изменён в основном редакторе"""
        self._modified = self._editor.toPlainText() != self._original_text
        self._update_status()
        self._update_timer.start(500)  # Debounce update
    
    def _on_split_text_changed(self):
        """Текст изменён в split редакторе"""
        text = self._split_editor.toPlainText()
        self._modified = text != self._original_text
        self._update_status()
        # Синхронизируем с основным редактором
        if self._editor.toPlainText() != text:
            self._editor.blockSignals(True)
            self._editor.setPlainText(text)
            self._editor.blockSignals(False)
        self._update_timer.start(300)
    
    def _on_tab_changed(self, index: int):
        """Переключение таба - синхронизация"""
        current_text = self._editor.toPlainText()
        
        if index == 2:  # Split view
            if self._split_editor.toPlainText() != current_text:
                self._split_editor.blockSignals(True)
                self._split_editor.setPlainText(current_text)
                self._split_editor.blockSignals(False)
        
        self._update_preview()
    
    def _update_preview(self):
        """Обновить превью"""
        if self._tabs.currentIndex() == 2:
            text = self._split_editor.toPlainText()
            html = markdown_to_html(text)
            self._split_preview.setHtml(html)
        else:
            text = self._editor.toPlainText()
            html = markdown_to_html(text)
            self._preview.setHtml(html)
    
    def _update_status(self):
        """Обновить статус"""
        if self._modified:
            self._status_label.setText("● Изменено")
            self._status_label.setStyleSheet("color: #dcdcaa; font-size: 12px;")
            self._save_btn.setEnabled(True)
            self._reset_btn.setEnabled(True)
        else:
            self._status_label.setText("Сохранено")
            self._status_label.setStyleSheet("color: #4ec9b0; font-size: 12px;")
            self._save_btn.setEnabled(False)
            self._reset_btn.setEnabled(False)
    
    def _save(self):
        """Сохранить изменения"""
        text = self._editor.toPlainText()
        
        if self._save_callback:
            try:
                if self._save_callback(text):
                    self._original_text = text
                    self._modified = False
                    self._update_status()
                    self.markdown_saved.emit(text)
                else:
                    QMessageBox.warning(self, "Ошибка", "Не удалось сохранить документ")
            except Exception as e:
                logger.error(f"Save failed: {e}")
                QMessageBox.critical(self, "Ошибка", f"Ошибка сохранения: {e}")
        else:
            self._original_text = text
            self._modified = False
            self._update_status()
            self.markdown_saved.emit(text)
    
    def _reset(self):
        """Сбросить изменения"""
        if self._modified:
            reply = QMessageBox.question(
                self, "Сброс изменений",
                "Вы уверены, что хотите сбросить все изменения?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self._load_content(self._original_text)
    
    def closeEvent(self, event):
        """Проверка несохранённых изменений при закрытии"""
        if self._modified:
            reply = QMessageBox.question(
                self, "Несохранённые изменения",
                "Документ был изменён. Сохранить перед закрытием?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel
            )
            if reply == QMessageBox.Save:
                self._save()
                event.accept()
            elif reply == QMessageBox.Discard:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()



