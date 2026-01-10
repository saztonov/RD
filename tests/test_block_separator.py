"""
Тесты для create_block_separator() из pdf_streaming_core.
"""
import uuid

import pytest
from PIL import Image

# Генерируем валидные UUID для тестов
TEST_BLOCK_ID = str(uuid.uuid4())


def test_create_block_separator_basic():
    """Базовый тест: функция создаёт изображение корректных размеров."""
    from services.remote_ocr.server.pdf_streaming_core import create_block_separator

    block_id = TEST_BLOCK_ID
    width = 800

    result = create_block_separator(block_id, width)

    assert isinstance(result, Image.Image)
    assert result.width == width
    assert result.height == 60  # BLOCK_SEPARATOR_HEIGHT
    assert result.mode == "RGB"


def test_create_block_separator_without_system_fonts(monkeypatch):
    """
    Тест что create_block_separator() не падает без системных шрифтов.
    Патчим truetype чтобы всегда выбрасывать OSError для файлов шрифтов.
    """
    from PIL import ImageFont

    original_truetype = ImageFont.truetype

    def mock_truetype(font, size=None, **kwargs):
        # Пропускаем вызовы от load_default() (BytesIO объекты)
        if hasattr(font, "read"):
            return original_truetype(font, size, **kwargs)
        raise OSError(f"Font {font} not found")

    monkeypatch.setattr(ImageFont, "truetype", mock_truetype)

    from services.remote_ocr.server.pdf_streaming_core import create_block_separator

    block_id = str(uuid.uuid4())
    width = 600

    # Не должен падать - использует load_default()
    result = create_block_separator(block_id, width)

    assert isinstance(result, Image.Image)
    assert result.width == width
    assert result.height == 60


def test_create_block_separator_uses_bundled_font(monkeypatch):
    """
    Тест что при отсутствии arial.ttf используется bundled шрифт.
    """
    from PIL import ImageFont

    from services.remote_ocr.server.pdf_streaming_core import BUNDLED_FONT_PATH

    fonts_tried = []
    original_truetype = ImageFont.truetype

    def tracking_truetype(font, size=None, **kwargs):
        # Записываем только строковые пути к файлам
        if isinstance(font, str):
            fonts_tried.append(font)
            if font == "arial.ttf":
                raise OSError("Arial not found")
        return original_truetype(font, size, **kwargs)

    monkeypatch.setattr(ImageFont, "truetype", tracking_truetype)

    from services.remote_ocr.server.pdf_streaming_core import create_block_separator

    result = create_block_separator(str(uuid.uuid4()), 500)

    assert isinstance(result, Image.Image)
    assert "arial.ttf" in fonts_tried
    assert BUNDLED_FONT_PATH in fonts_tried
