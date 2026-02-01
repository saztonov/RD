"""DeepSeek OCR Backend"""
import logging
import os
import tempfile
import time
from typing import Optional

from PIL import Image

logger = logging.getLogger(__name__)


class DeepSeekOCRError(Exception):
    """Ошибка DeepSeek OCR API (для различения от валидного результата)"""
    pass


class DeepSeekOCRBackend:
    """OCR через DeepSeek-OCR-2 API"""

    DEFAULT_URL = "https://louvred-madie-gigglier.ngrok-free.dev"
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
        Инициализация DeepSeek OCR backend.

        Args:
            api_url: URL API (по умолчанию https://louvred-madie-gigglier.ngrok-free.dev)
            mode: Режим распознавания - 'markdown' или 'text'
            timeout: Таймаут запроса в секундах (по умолчанию 120)
        """
        self.api_url = (
            api_url or os.getenv("DEEPSEEK_OCR_URL", self.DEFAULT_URL)
        ).rstrip("/")
        self.mode = mode
        self.timeout = timeout

        try:
            import requests
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry

            self.session = requests.Session()
            # Заголовок для обхода интерстициальной страницы ngrok
            self.session.headers.update({
                "ngrok-skip-browser-warning": "true"
            })
            retry = Retry(
                total=3, backoff_factor=1.0, status_forcelist=[502, 503, 504]
            )
            adapter = HTTPAdapter(
                pool_connections=5, pool_maxsize=10, max_retries=retry
            )
            self.session.mount("https://", adapter)
            self.session.mount("http://", adapter)
        except ImportError:
            raise ImportError("Требуется установить requests: pip install requests")

        logger.info(
            f"DeepSeek OCR инициализирован: url={self.api_url}, mode={self.mode}, "
            f"timeout={self.timeout}s"
        )

    def supports_pdf_input(self) -> bool:
        """DeepSeek поддерживает PDF напрямую"""
        return True

    def recognize(
        self,
        image: Optional[Image.Image],
        prompt: Optional[dict] = None,
        json_mode: bool = None,
        pdf_file_path: Optional[str] = None,
    ) -> str:
        """
        Распознать изображение или PDF через DeepSeek OCR API.

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
        # Приоритет: PDF файл, затем изображение
        if pdf_file_path and os.path.exists(pdf_file_path):
            file_path = pdf_file_path
            mime_type = "application/pdf"
            is_temp = False
            logger.debug(f"DeepSeek: используем PDF файл {pdf_file_path}")
        elif image:
            # Сохраняем во временный файл
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                image.save(tmp, format="PNG")
                file_path = tmp.name
            mime_type = "image/png"
            is_temp = True
            logger.debug(
                f"DeepSeek: сохранено изображение {image.width}x{image.height}"
            )
        else:
            logger.error("DeepSeek: нет изображения или PDF для распознавания")
            raise DeepSeekOCRError("Нет изображения или PDF для распознавания")

        try:
            # Проверка размера файла
            file_size = os.path.getsize(file_path)
            if file_size > self.MAX_FILE_SIZE:
                size_mb = file_size / 1024 / 1024
                logger.error(f"DeepSeek: файл слишком большой ({size_mb:.1f}MB)")
                raise DeepSeekOCRError(f"Файл слишком большой ({size_mb:.1f}MB > 30MB)")

            logger.info(
                f"DeepSeek OCR запрос: url={self.api_url}/ocr, "
                f"file_size={file_size}B ({file_size / 1024:.1f}KB), "
                f"mime={mime_type}, mode={self.mode}"
            )

            last_error = None
            for attempt in range(self.MAX_RETRIES):
                try:
                    with open(file_path, "rb") as f:
                        file_content = f.read()

                    files = {"file": (os.path.basename(file_path), file_content, mime_type)}
                    data = {"mode": self.mode}

                    request_start = time.time()
                    response = self.session.post(
                        f"{self.api_url}/ocr",
                        files=files,
                        data=data,
                        timeout=self.timeout,
                    )
                    request_elapsed = time.time() - request_start
                    logger.info(
                        f"DeepSeek OCR ответ: status={response.status_code}, "
                        f"elapsed={request_elapsed:.2f}s"
                    )

                    # Retry на 5xx ошибках
                    if response.status_code in self.RETRYABLE_STATUS_CODES:
                        last_error = f"HTTP {response.status_code}"
                        if attempt < self.MAX_RETRIES - 1:
                            delay = self.RETRY_DELAYS[attempt]
                            logger.warning(
                                f"DeepSeek: {response.status_code}, retry {attempt + 1}/{self.MAX_RETRIES} через {delay}s"
                            )
                            time.sleep(delay)
                            continue
                        else:
                            logger.error(
                                f"DeepSeek API error после {self.MAX_RETRIES} попыток: "
                                f"{response.status_code} - {response.text[:500]}"
                            )
                            raise DeepSeekOCRError(f"API недоступен: HTTP {response.status_code}")

                    # Другие ошибки HTTP
                    if response.status_code != 200:
                        logger.error(
                            f"DeepSeek API error: {response.status_code} - "
                            f"{response.text[:500]}"
                        )
                        raise DeepSeekOCRError(f"API error: HTTP {response.status_code}")

                    result = response.json()

                    if not result.get("success", False):
                        error = result.get("error", "Unknown error")
                        logger.error(f"DeepSeek: ошибка распознавания - {error}")
                        raise DeepSeekOCRError(f"Ошибка распознавания: {error}")

                    markdown = result.get("markdown", "")
                    pages = result.get("pages", 1)
                    logger.info(
                        f"DeepSeek OCR: распознано {len(markdown)} символов, {pages} страниц"
                    )

                    return markdown

                except DeepSeekOCRError:
                    raise
                except Exception as e:
                    last_error = str(e)
                    if attempt < self.MAX_RETRIES - 1:
                        delay = self.RETRY_DELAYS[attempt]
                        logger.warning(
                            f"DeepSeek: ошибка {e}, retry {attempt + 1}/{self.MAX_RETRIES} через {delay}s"
                        )
                        time.sleep(delay)
                    else:
                        logger.error(f"Ошибка DeepSeek OCR после {self.MAX_RETRIES} попыток: {e}", exc_info=True)
                        raise DeepSeekOCRError(f"Ошибка после {self.MAX_RETRIES} попыток: {last_error}")

            # Не должны сюда попасть, но на всякий случай
            raise DeepSeekOCRError(f"Ошибка после {self.MAX_RETRIES} попыток: {last_error}")

        finally:
            if is_temp and os.path.exists(file_path):
                os.unlink(file_path)
