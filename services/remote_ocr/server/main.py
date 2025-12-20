"""FastAPI сервер для удалённого OCR (все данные через Supabase + R2)"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware

from .settings import settings
from .storage import init_db
from .routes.jobs import router as jobs_router
from .routes.drafts import router as drafts_router

import logging
_logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle: инициализация БД (воркер запускается отдельно через Celery)"""
    init_db()
    yield


app = FastAPI(title="rd-remote-ocr", lifespan=lifespan)


class LogRequestMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "POST" and "/jobs" in str(request.url.path):
            content_type = request.headers.get("content-type", "")
            _logger.info(f"POST /jobs Content-Type: {content_type}")
        try:
            response = await call_next(request)
            if response.status_code >= 400:
                _logger.error(f"{request.method} {request.url.path} -> {response.status_code}")
            return response
        except Exception as e:
            _logger.exception(f"Exception in {request.method} {request.url.path}: {e}")
            raise


app.add_middleware(LogRequestMiddleware)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    _logger.error(f"Validation error on {request.method} {request.url.path}: {exc.errors()}")
    return JSONResponse(status_code=400, content={"detail": exc.errors()})


@app.get("/health")
def health() -> dict:
    """Health check"""
    return {"ok": True}


# Подключаем роутеры
app.include_router(jobs_router)
app.include_router(drafts_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
