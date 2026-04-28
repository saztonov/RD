"""Тесты robust-парсинга в inject_pdfplumber_to_ocr_text.

Регрессия 2026-04-28: 60 WARNING'ов "Не удалось вставить pdfplumber текст
в JSON" из-за greedy regex и не-JSON ответов модели. Не-JSON ответы — это
нормально (модель вернула HTML), не ошибка.
"""

import json
import logging

from services.remote_ocr.server.worker_prompts import inject_pdfplumber_to_ocr_text


def test_pure_json_replaced():
    src = '{"ocr_text": "old", "extra": 1}'
    out = inject_pdfplumber_to_ocr_text(src, "NEW TEXT")
    parsed = json.loads(out)
    assert parsed["ocr_text"] == "NEW TEXT"
    assert parsed["extra"] == 1


def test_fenced_json_replaced_and_re_fenced():
    src = '```json\n{"ocr_text": "old", "extra": 2}\n```'
    out = inject_pdfplumber_to_ocr_text(src, "NEW")
    assert out.startswith("```json\n")
    assert out.endswith("\n```")
    inner = out.split("\n", 1)[1].rsplit("\n", 1)[0]
    parsed = json.loads(inner)
    assert parsed["ocr_text"] == "NEW"


def test_bare_fence_without_lang():
    src = '```\n{"ocr_text": "x"}\n```'
    out = inject_pdfplumber_to_ocr_text(src, "Y")
    assert "```json" in out  # всегда нормализуется к ```json
    assert "Y" in out


def test_non_json_returns_unchanged_no_warning(caplog):
    """HTML-ответ — это валидный non-JSON, должен пройти без WARNING."""
    src = "<p>Some HTML response from model</p>"
    with caplog.at_level(logging.WARNING, logger="services.remote_ocr.server.worker_prompts"):
        out = inject_pdfplumber_to_ocr_text(src, "TEXT")
    assert out == src
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not warnings, f"Не-JSON ответы НЕ должны логироваться как WARNING, было: {warnings}"


def test_malformed_json_returns_unchanged_no_warning(caplog):
    """Сломанный JSON — тоже не WARNING, а debug."""
    src = '{"ocr_text": "x" "missing": comma}'
    with caplog.at_level(logging.WARNING, logger="services.remote_ocr.server.worker_prompts"):
        out = inject_pdfplumber_to_ocr_text(src, "TEXT")
    assert out == src
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not warnings


def test_json_without_ocr_text_field_returns_unchanged():
    src = '{"only_html": "<p>x</p>"}'
    out = inject_pdfplumber_to_ocr_text(src, "TEXT")
    assert out == src


def test_empty_pdfplumber_returns_original():
    src = '{"ocr_text": "old"}'
    assert inject_pdfplumber_to_ocr_text(src, "") == src
    assert inject_pdfplumber_to_ocr_text(src, "   ") == src


def test_empty_ocr_result_returns_unchanged():
    assert inject_pdfplumber_to_ocr_text("", "TEXT") == ""
    assert inject_pdfplumber_to_ocr_text(None, "TEXT") is None
