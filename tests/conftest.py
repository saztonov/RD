"""
Pytest fixtures для тестирования PDF-кропинга.
"""
import os
import tempfile
from pathlib import Path

import fitz
import pytest


@pytest.fixture
def sample_pdf():
    """
    Создаёт временный тестовый PDF файл A4 с текстом.
    """
    # Создаём временный файл
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)

    try:
        # Создаём PDF документ
        doc = fitz.open()

        # Добавляем страницу A4 (595 x 842 points)
        page = doc.new_page(width=595, height=842)

        # Добавляем текст в разных местах
        text_items = [
            ((50, 50), "Test Header - Тестовый заголовок"),
            ((50, 100), "Sample text block for OCR testing"),
            ((50, 150), "Пример текстового блока для тестирования"),
            ((300, 300), "Center block"),
            ((50, 700), "Footer text at bottom"),
        ]

        for pos, text in text_items:
            page.insert_text(pos, text, fontsize=12)

        # Добавляем прямоугольник для визуального теста
        rect = fitz.Rect(200, 200, 400, 400)
        shape = page.new_shape()
        shape.draw_rect(rect)
        shape.finish(color=(0, 0, 0), fill=None, width=2)
        shape.commit()

        doc.save(path)
        doc.close()

        yield path
    finally:
        # Удаляем временный файл
        if os.path.exists(path):
            os.remove(path)


@pytest.fixture
def large_format_pdf():
    """
    Создаёт временный тестовый PDF файл A1 формата (большой лист).
    A1: 1684 x 2384 points (594 x 841 mm)
    """
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)

    try:
        doc = fitz.open()

        # A1 размер в points
        page = doc.new_page(width=1684, height=2384)

        # Добавляем текст
        page.insert_text((100, 100), "Large Format Test - A1", fontsize=24)
        page.insert_text((100, 200), "This is a test for large format PDF rendering", fontsize=16)

        # Добавляем несколько блоков в разных частях
        for i, (x, y) in enumerate([(200, 400), (800, 400), (200, 1200), (800, 1200)]):
            rect = fitz.Rect(x, y, x + 300, y + 200)
            shape = page.new_shape()
            shape.draw_rect(rect)
            shape.finish(color=(0, 0, 0), fill=None, width=2)
            shape.commit()
            page.insert_text((x + 10, y + 50), f"Block {i + 1}", fontsize=14)

        doc.save(path)
        doc.close()

        yield path
    finally:
        if os.path.exists(path):
            os.remove(path)
