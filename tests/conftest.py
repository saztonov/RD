"""
Fixtures для интеграционных тестов OCR.
"""
import json
import logging
import os
import sys
from pathlib import Path
from typing import List

# Добавляем packages и apps в путь
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "packages"))
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from dotenv import load_dotenv

# Загружаем .env из корня проекта
load_dotenv(Path(__file__).parent.parent / ".env")

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
# Включаем DEBUG для ключевых модулей
logging.getLogger('rd_pipeline').setLevel(logging.DEBUG)
logging.getLogger('rd_pipeline.processing').setLevel(logging.DEBUG)
logging.getLogger('rd_pipeline.ocr').setLevel(logging.DEBUG)

logger = logging.getLogger(__name__)


@pytest.fixture
def project_root() -> Path:
    """Корневая директория проекта."""
    return Path(__file__).parent.parent


@pytest.fixture
def test_data_dir(project_root) -> Path:
    """Директория с тестовыми данными."""
    return project_root / "test-ex"


@pytest.fixture
def test_pdf_path(test_data_dir) -> Path:
    """Путь к тестовому PDF."""
    pdf_path = test_data_dir / "exmpl.pdf"
    assert pdf_path.exists(), f"Тестовый PDF не найден: {pdf_path}"
    logger.info(f"Тестовый PDF: {pdf_path} ({pdf_path.stat().st_size / 1024:.1f} KB)")
    return pdf_path


@pytest.fixture
def test_annotation_path(test_data_dir) -> Path:
    """Путь к файлу аннотаций."""
    annotation_path = test_data_dir / "exmpl_annotation.json"
    assert annotation_path.exists(), f"Файл аннотаций не найден: {annotation_path}"
    return annotation_path


@pytest.fixture
def expected_html_path(test_data_dir) -> Path:
    """Путь к ожидаемому HTML результату."""
    html_path = test_data_dir / "datalab-output-exmpl.html"
    assert html_path.exists(), f"Ожидаемый HTML не найден: {html_path}"
    return html_path


@pytest.fixture
def test_blocks(test_annotation_path) -> List:
    """Загружает блоки из файла аннотаций."""
    from rd_domain.models import Block

    with open(test_annotation_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    blocks = []
    for page_data in data.get("pages", []):
        page_number = page_data.get("page_number", 0)
        page_width = page_data.get("width", 0)
        page_height = page_data.get("height", 0)

        logger.info(f"Страница {page_number}: {page_width}x{page_height} px")

        for block_data in page_data.get("blocks", []):
            block, _ = Block.from_dict(block_data, migrate_ids=False)
            blocks.append(block)

            # Логируем информацию о блоке
            height_px = block.coords_px[3] - block.coords_px[1]
            width_px = block.coords_px[2] - block.coords_px[0]
            logger.info(
                f"  Блок {block.id}: page={block.page_index}, "
                f"type={block.block_type.value}, size={width_px}x{height_px} px, "
                f"coords_norm={block.coords_norm}"
            )

    logger.info(f"Всего загружено {len(blocks)} блоков")
    return blocks


@pytest.fixture
def datalab_api_key() -> str:
    """API ключ Datalab из переменных окружения."""
    api_key = os.getenv("DATALAB_API_KEY")
    if not api_key:
        pytest.skip("DATALAB_API_KEY не установлен в .env")
    return api_key


@pytest.fixture
def datalab_backend(datalab_api_key):
    """Создаёт Datalab OCR backend."""
    from rd_pipeline.ocr.backends.datalab import DatalabOCRBackend

    backend = DatalabOCRBackend(
        api_key=datalab_api_key,
        poll_interval=3,
        poll_max_attempts=90,
        max_retries=3
    )
    logger.info("Datalab backend создан")
    return backend
