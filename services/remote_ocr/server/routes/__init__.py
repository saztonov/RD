"""Routes для Remote OCR API"""

from services.remote_ocr.server.routes.jobs import router as jobs_router

__all__ = ["jobs_router"]
