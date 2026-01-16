"""Factory for creating OCR engines."""

import logging

from rd_pipeline.ocr.ports import OCRBackend

logger = logging.getLogger(__name__)


def create_ocr_engine(backend: str = "dummy", **kwargs) -> OCRBackend:
    """
    Factory for creating OCR engine.

    Args:
        backend: engine type ('openrouter', 'datalab' or 'dummy')
        **kwargs: additional parameters for engine

    Returns:
        OCR engine instance
    """
    if backend == "openrouter":
        from rd_pipeline.ocr.backends.openrouter import OpenRouterBackend

        return OpenRouterBackend(**kwargs)
    elif backend == "datalab":
        from rd_pipeline.ocr.backends.datalab import DatalabOCRBackend

        return DatalabOCRBackend(**kwargs)
    elif backend == "dummy":
        from rd_pipeline.ocr.backends.dummy import DummyOCRBackend

        return DummyOCRBackend()
    else:
        logger.warning(f"Unknown backend '{backend}', using dummy")
        from rd_pipeline.ocr.backends.dummy import DummyOCRBackend

        return DummyOCRBackend()
