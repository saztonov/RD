"""Async DeepSeek OCR Backend"""
import asyncio
import logging
import os
import tempfile
from typing import Optional

import httpx
from PIL import Image

from .deepseek import DeepSeekOCRError

logger = logging.getLogger(__name__)


class AsyncDeepSeekOCRBackend:
    """Асинхронный OCR через DeepSeek-OCR-2 API"""

    DEFAULT_URL = "https://youtu.pnode.site"
    MAX_FILE_SIZE = 30 * 1024 * 1024  # 30MB
    MAX_RETRIES = 3
    RETRY_DELAYS = [1, 2, 4]  # секунды (exponential backoff)
    RETRYABLE_STATUS_CODES = (502, 503, 504)

    def __init__(
        self,
        api_url: Optional[str] = None,
        mode: str = "markdown",
        timeout: int = 120,
    ):
        """
        Инициализация асинхронного DeepSeek OCR backend.

        Args:
            api_url: URL API (по умолчанию https://youtu.pnode.site)
            mode: Режим распознавания - 'markdown' или 'text'
            timeout: Таймаут запроса в секундах (по умолчанию 120)
        """
        self.api_url = (
            api_url or os.getenv("DEEPSEEK_OCR_URL", self.DEFAULT_URL)
        ).rstrip("/")
        self.mode = mode
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

        logger.info(
            f"AsyncDeepSeekOCRBackend инициализирован: url={self.api_url}, "
            f"mode={self.mode}, timeout={self.timeout}s"
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """Получить или создать httpx AsyncClient"""
        if self._client is None or self._client.is_closed:
            transport = httpx.AsyncHTTPTransport(
                retries=3,
                limits=httpx.Limits(
                    max_connections=10,
                    max_keepalive_connections=5,
                    keepalive_expiry=30.0,
                ),
            )
            self._client = httpx.AsyncClient(
                transport=transport,
                timeout=httpx.Timeout(float(self.timeout), connect=30.0),
            )
        return self._client

    async def close(self):
        """Закрыть HTTP клиент"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def supports_pdf_input(self) -> bool:
        """DeepSeek поддерживает PDF напрямую"""
        return True

    async def recognize_async(
        self,
        image: Optional[Image.Image],
        prompt: Optional[dict] = None,
        json_mode: bool = None,
        pdf_file_path: Optional[str] = None,
    ) -> str:
        """
        Асинхронно распознать изображение или PDF через DeepSeek OCR API.

        Args:
            image: PIL изображение для распознавания
            prompt: Не используется (для совместимости с протоколом)
            json_mode: Не используется (для совместимости с протоколом)
            pdf_file_path: Путь к PDF файлу (приоритет над image)

        Returns:
            Распознанный текст в формате markdown

        Raises:
            DeepSeekOCRError: При ошибке API после всех попыток retry
        """
        client = await self._get_client()

        # Приоритет: PDF файл, затем изображение
        if pdf_file_path and os.path.exists(pdf_file_path):
            file_path = pdf_file_path
            mime_type = "application/pdf"
            is_temp = False
            logger.debug(f"AsyncDeepSeek: используем PDF файл {pdf_file_path}")
        elif image:
            # Сохраняем во временный файл
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                image.save(tmp, format="PNG")
                file_path = tmp.name
            mime_type = "image/png"
            is_temp = True
            logger.debug(
                f"AsyncDeepSeek: сохранено изображение {image.width}x{image.height}"
            )
        else:
            logger.error("AsyncDeepSeek: нет изображения или PDF для распознавания")
            raise DeepSeekOCRError("Нет изображения или PDF для распознавания")

        try:
            # Проверка размера файла
            file_size = os.path.getsize(file_path)
            if file_size > self.MAX_FILE_SIZE:
                size_mb = file_size / 1024 / 1024
                logger.error(
                    f"AsyncDeepSeek: файл слишком большой ({size_mb:.1f}MB)"
                )
                raise DeepSeekOCRError(f"Файл слишком большой ({size_mb:.1f}MB > 30MB)")

            logger.info(
                f"AsyncDeepSeek: отправка запроса ({file_size / 1024:.1f}KB, "
                f"mode={self.mode})"
            )

            # Читаем файл в память для httpx
            with open(file_path, "rb") as f:
                file_content = f.read()

            last_error = None
            for attempt in range(self.MAX_RETRIES):
                try:
                    files = {"file": (os.path.basename(file_path), file_content, mime_type)}
                    data = {"mode": self.mode}

                    response = await client.post(
                        f"{self.api_url}/ocr",
                        files=files,
                        data=data,
                    )

                    # Retry на 5xx ошибках
                    if response.status_code in self.RETRYABLE_STATUS_CODES:
                        last_error = f"HTTP {response.status_code}"
                        if attempt < self.MAX_RETRIES - 1:
                            delay = self.RETRY_DELAYS[attempt]
                            logger.warning(
                                f"AsyncDeepSeek: {response.status_code}, retry {attempt + 1}/{self.MAX_RETRIES} через {delay}s"
                            )
                            await asyncio.sleep(delay)
                            continue
                        else:
                            logger.error(
                                f"AsyncDeepSeek API error после {self.MAX_RETRIES} попыток: "
                                f"{response.status_code} - {response.text[:500]}"
                            )
                            raise DeepSeekOCRError(f"API недоступен: HTTP {response.status_code}")

                    # Другие ошибки HTTP
                    if response.status_code != 200:
                        logger.error(
                            f"AsyncDeepSeek API error: {response.status_code} - "
                            f"{response.text[:500]}"
                        )
                        raise DeepSeekOCRError(f"API error: HTTP {response.status_code}")

                    result = response.json()

                    if not result.get("success", False):
                        error = result.get("error", "Unknown error")
                        logger.error(f"AsyncDeepSeek: ошибка распознавания - {error}")
                        raise DeepSeekOCRError(f"Ошибка распознавания: {error}")

                    markdown = result.get("markdown", "")
                    pages = result.get("pages", 1)
                    logger.info(
                        f"AsyncDeepSeek OCR: распознано {len(markdown)} символов, "
                        f"{pages} страниц"
                    )

                    return markdown

                except DeepSeekOCRError:
                    raise
                except httpx.TimeoutException:
                    last_error = "таймаут"
                    if attempt < self.MAX_RETRIES - 1:
                        delay = self.RETRY_DELAYS[attempt]
                        logger.warning(
                            f"AsyncDeepSeek: таймаут, retry {attempt + 1}/{self.MAX_RETRIES} через {delay}s"
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"AsyncDeepSeek OCR: таймаут после {self.MAX_RETRIES} попыток")
                        raise DeepSeekOCRError(f"Таймаут после {self.MAX_RETRIES} попыток")
                except Exception as e:
                    last_error = str(e)
                    if attempt < self.MAX_RETRIES - 1:
                        delay = self.RETRY_DELAYS[attempt]
                        logger.warning(
                            f"AsyncDeepSeek: ошибка {e}, retry {attempt + 1}/{self.MAX_RETRIES} через {delay}s"
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"Ошибка AsyncDeepSeek OCR после {self.MAX_RETRIES} попыток: {e}", exc_info=True)
                        raise DeepSeekOCRError(f"Ошибка после {self.MAX_RETRIES} попыток: {last_error}")

            # Не должны сюда попасть, но на всякий случай
            raise DeepSeekOCRError(f"Ошибка после {self.MAX_RETRIES} попыток: {last_error}")

        finally:
            if is_temp and os.path.exists(file_path):
                os.unlink(file_path)

    def __del__(self):
        """Cleanup при удалении объекта"""
        if self._client and not self._client.is_closed:
            logger.debug("AsyncDeepSeekOCRBackend: client not closed properly")
