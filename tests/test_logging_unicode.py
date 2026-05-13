"""Тесты безопасного консольного handler-а на cp1251-подобных потоках.

Проверяют, что emoji (`✅`, `❌`, `⚠️`) и русский текст не валят logging,
даже если поток не умеет в Unicode (например, классический cp1251 stdout
на Windows-RU без UTF-8 reconfigure).
"""
from __future__ import annotations

import io
import logging

from app.logging_manager import _make_safe_console_handler as client_make_safe_handler
from services.remote_ocr.server.logging_config import (
    _make_safe_console_handler as server_make_safe_handler,
)


def _make_cp1251_stream() -> io.TextIOWrapper:
    """Создать поток как cp1251-консоль без поддержки reconfigure-на-utf8.

    io.TextIOWrapper позволяет reconfigure, поэтому safe-handler сначала
    переключит его на UTF-8. Чтобы поймать сценарий «reconfigure упал»,
    подменим reconfigure на бросок.
    """

    class StrictCp1251(io.TextIOWrapper):
        def reconfigure(self, *args, **kwargs):  # type: ignore[override]
            raise RuntimeError("reconfigure not supported")

    return StrictCp1251(
        io.BytesIO(),
        encoding="cp1251",
        errors="strict",
        newline="",
        write_through=True,
    )


def _emit_message(handler_factory, message: str) -> str:
    stream = _make_cp1251_stream()
    handler = handler_factory(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger(f"test.{id(stream)}")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False

    logger.info(message)
    handler.flush()
    data = stream.buffer.getvalue()
    stream.close()
    return data.decode("cp1251", errors="replace")


def test_emoji_does_not_crash_client_handler():
    """Emoji `✅` не должен валить logger клиента (cp1251 stream)."""
    out = _emit_message(client_make_safe_handler, "✅ R2Storage initialized")
    assert "R2Storage initialized" in out


def test_russian_text_does_not_crash_client_handler():
    """Русский текст должен либо записаться, либо backslash-escape без падения."""
    out = _emit_message(client_make_safe_handler, "Файл скачан из R2: ok")
    # cp1251 поддерживает кириллицу — должно записаться как есть
    assert "Файл" in out or r"Файл" in out


def test_mixed_emoji_and_russian_client():
    """Смешанная строка emoji + русский — без исключения."""
    out = _emit_message(
        client_make_safe_handler, "✅ Файл скачан ✅"
    )
    assert "Файл" in out or r"Ф" in out


def test_emoji_does_not_crash_server_handler():
    """Тот же safe-handler из server logging_config."""
    out = _emit_message(server_make_safe_handler, "✅ server start")
    assert "server start" in out
