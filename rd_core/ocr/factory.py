"""Фабрика для создания OCR движков"""
import logging
from rd_core.ocr.base import OCRBackend

logger = logging.getLogger(__name__)


def create_ocr_engine(backend: str = "dummy", **kwargs) -> OCRBackend:
    """
    Фабрика для создания OCR движка
    
    Args:
        backend: тип движка ('openrouter', 'datalab' или 'dummy')
        **kwargs: дополнительные параметры для движка
    
    Returns:
        Экземпляр OCR движка
    """
    if backend == "openrouter":
        from rd_core.ocr.openrouter import OpenRouterBackend
        return OpenRouterBackend(**kwargs)
    elif backend == "datalab":
        from rd_core.ocr.datalab import DatalabOCRBackend
        return DatalabOCRBackend(**kwargs)
    elif backend == "dummy":
        from rd_core.ocr.dummy import DummyOCRBackend
        return DummyOCRBackend()
    else:
        logger.warning(f"Неизвестный backend '{backend}', используется dummy")
        from rd_core.ocr.dummy import DummyOCRBackend
        return DummyOCRBackend()

