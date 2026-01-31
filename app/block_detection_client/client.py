"""HTTP клиент для Block Detection API."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

import httpx

from .exceptions import (
    BlockDetectionConnectionError,
    BlockDetectionError,
    BlockDetectionServerError,
    BlockDetectionTimeoutError,
)
from .models import DetectionResult

logger = logging.getLogger(__name__)

# Глобальный HTTP клиент с connection pooling
_http_client: httpx.Client | None = None
_client_base_url: str | None = None


def _get_http_client(base_url: str, timeout: float) -> httpx.Client:
    """Получить или создать HTTP клиент с connection pooling."""
    global _http_client, _client_base_url

    if _http_client is None or _client_base_url != base_url:
        if _http_client is not None:
            try:
                _http_client.close()
            except Exception:
                pass

        _http_client = httpx.Client(
            base_url=base_url,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
            timeout=timeout,
        )
        _client_base_url = base_url
        logger.debug(f"Создан HTTP клиент для Block Detection: {base_url}")

    return _http_client


@dataclass
class BlockDetectionClient:
    """Клиент для Block Detection API (LightOnOCR)."""

    base_url: str = field(
        default_factory=lambda: os.getenv(
            "BLOCK_DETECTION_URL", "http://localhost:8000"
        )
    )
    timeout: float = 60.0
    api_prefix: str = "/api/v1"

    def health(self) -> bool:
        """Проверить доступность API."""
        try:
            client = _get_http_client(self.base_url, timeout=5.0)
            response = client.get(f"{self.api_prefix}/health", timeout=5.0)
            if response.status_code == 200:
                data = response.json()
                return data.get("status") == "healthy" and data.get("model_loaded", False)
            return False
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.debug(f"Health check failed: {e}")
            return False
        except Exception as e:
            logger.warning(f"Health check error: {e}")
            return False

    def detect_blocks(
        self,
        image_bytes: bytes,
        filename: str = "page.png",
        content_type: str = "image/png",
    ) -> DetectionResult:
        """
        Обнаружить блоки на изображении.

        Args:
            image_bytes: Байты изображения (PNG/JPEG)
            filename: Имя файла для multipart
            content_type: MIME-тип изображения

        Returns:
            DetectionResult с обнаруженными блоками

        Raises:
            BlockDetectionConnectionError: Сервер недоступен
            BlockDetectionTimeoutError: Превышено время ожидания
            BlockDetectionServerError: Ошибка сервера
            BlockDetectionError: Другие ошибки
        """
        try:
            client = _get_http_client(self.base_url, self.timeout)

            files = {"file": (filename, image_bytes, content_type)}

            logger.debug(
                f"Отправка запроса детекции: {len(image_bytes)} байт, timeout={self.timeout}s"
            )

            response = client.post(
                f"{self.api_prefix}/detect",
                files=files,
                timeout=self.timeout,
            )

            if response.status_code >= 500:
                error_detail = self._extract_error(response)
                raise BlockDetectionServerError(
                    f"Ошибка сервера {response.status_code}: {error_detail}"
                )

            if response.status_code >= 400:
                error_detail = self._extract_error(response)
                raise BlockDetectionError(f"Ошибка запроса: {error_detail}")

            data = response.json()

            if not data.get("success", True):
                error = data.get("error", "Unknown error")
                raise BlockDetectionError(f"API вернул ошибку: {error}")

            result = DetectionResult.from_api_response(data)
            logger.info(
                f"Детекция завершена: {len(result.blocks)} блоков за {result.processing_time_ms:.0f}ms"
            )
            return result

        except httpx.ConnectError as e:
            logger.error(f"Ошибка подключения к серверу детекции: {e}")
            raise BlockDetectionConnectionError(
                f"Сервер детекции недоступен: {self.base_url}"
            ) from e

        except httpx.TimeoutException as e:
            logger.error(f"Таймаут запроса детекции: {e}")
            raise BlockDetectionTimeoutError(
                f"Превышено время ожидания ({self.timeout}s)"
            ) from e

        except (BlockDetectionError, BlockDetectionServerError):
            raise

        except Exception as e:
            logger.error(f"Неожиданная ошибка детекции: {e}", exc_info=True)
            raise BlockDetectionError(f"Ошибка детекции: {e}") from e

    def _extract_error(self, response: httpx.Response) -> str:
        """Извлечь сообщение об ошибке из ответа."""
        try:
            data = response.json()
            return data.get("detail") or data.get("error") or str(data)
        except Exception:
            return response.text[:200] if response.text else f"HTTP {response.status_code}"
